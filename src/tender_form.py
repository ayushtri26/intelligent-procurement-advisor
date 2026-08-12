"""Create / Edit Tender — a professional modal (st.dialog) form covering all
seven tender sections, optional AI-assisted drafting, and the write path
into src.tender_repository. The AI step only ever proposes values into the
same editable widgets a human would use — nothing is auto-saved, and the
procurement manager must still click Create/Save Changes.
"""
from __future__ import annotations

import json
import re

import streamlit as st

from src import audit, llm_service, tender_repository, ui_components
from src.tenders_data import CURRENCIES, DEFAULT_EVALUATION_CRITERIA, PROCUREMENT_TYPES, TENDER_STATUSES

_FALLBACK_CATEGORIES = ["Electronics", "Furniture", "Logistics", "Raw Materials"]

_AI_PROMPT_TEMPLATE = """You are a procurement analyst. Based on the buyer's description below, propose \
structured tender details. Respond with ONLY a single valid JSON object (no markdown fences, no commentary) \
with exactly these keys:

{{
  "title": "short tender title",
  "category": "one of: {categories}",
  "description": "1-2 sentence description",
  "technical_requirements": ["...", "..."],
  "mandatory_requirements": ["...", "..."],
  "certifications": ["...", "..."],
  "delivery_requirement": "short delivery timeline description",
  "warranty_requirement": "short warranty description",
  "evaluation_criteria": {{"technical_compliance": 0-100, "price": 0-100, "delivery": 0-100, "past_performance": 0-100, "warranty": 0-100, "risk": 0-100}}
}}

The six evaluation_criteria values must sum to exactly 100. Buyer's description:
\"\"\"{description}\"\"\"
"""


def _vendor_category_options() -> list[str]:
    ranked_df = st.session_state.get("ranked_df")
    if ranked_df is not None and "category" in ranked_df.columns:
        return sorted(ranked_df["category"].dropna().unique().tolist())
    return _FALLBACK_CATEGORIES


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            text = brace_match.group(0)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def generate_tender_draft(description: str) -> dict | None:
    """Ask Claude to propose structured tender details from a free-text
    description. Returns None on any failure — the form is left blank/as-is
    and the user fills it in manually; this never blocks tender creation."""
    client = llm_service.get_client()
    if client is None or not description.strip():
        return None
    prompt = _AI_PROMPT_TEMPLATE.format(categories=", ".join(_vendor_category_options()), description=description.strip())
    try:
        response = client.messages.create(
            model=llm_service.get_model(),
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
    except Exception:
        return None
    return _extract_json(text)


def _list_editor(label: str, state_key: str, counter_key: str, placeholder: str) -> None:
    """Renders a dynamically add/removable list of single-line text inputs,
    backed by st.session_state[state_key] = [{"id": int, "text": str}, ...].
    Uses a stable per-item id (not list index) as the widget key so removing
    an item from the middle never reuses another item's stale widget state."""
    items = st.session_state[state_key]
    remove_id = None
    for item in items:
        row_l, row_r = st.columns([6, 1])
        item["text"] = row_l.text_input(
            label, value=item["text"], key=f"{state_key}_{item['id']}",
            placeholder=placeholder, label_visibility="collapsed",
        )
        if row_r.button("Remove", icon=":material/close:", key=f"{state_key}_rm_{item['id']}", use_container_width=True):
            remove_id = item["id"]
    if remove_id is not None:
        st.session_state[state_key] = [i for i in items if i["id"] != remove_id]
    if st.button(f"Add {label[:-1] if label.endswith('s') else label}", icon=":material/add:", key=f"{state_key}_add"):
        next_id = st.session_state[counter_key]
        st.session_state[state_key].append({"id": next_id, "text": ""})
        st.session_state[counter_key] = next_id + 1


def _init_draft(edit_tender: dict | None) -> None:
    if st.session_state.get("_tf_initialized"):
        return
    t = edit_tender or {}
    st.session_state.tf_title = t.get("title", "")
    st.session_state.tf_description = t.get("description", "")
    st.session_state.tf_category = t.get("category") if t.get("category") in _vendor_category_options() else _vendor_category_options()[0]
    st.session_state.tf_department = t.get("department", "")
    st.session_state.tf_procurement_type = t.get("procurement_type", PROCUREMENT_TYPES[0])
    st.session_state.tf_budget = float(t.get("budget", 0) or 0)
    st.session_state.tf_currency = t.get("currency", "USD")
    st.session_state.tf_quantity = int(t.get("quantity", 0) or 0)
    st.session_state.tf_deadline_text = t.get("submission_deadline", "")
    st.session_state.tf_start_text = t.get("contract_start_date", "")
    st.session_state.tf_duration = t.get("contract_duration", "")
    st.session_state.tf_delivery_requirement = t.get("delivery_requirement", "")
    st.session_state.tf_delivery_location = t.get("delivery_location", "")
    st.session_state.tf_min_otd = int(t.get("minimum_on_time_delivery", 90) or 90)
    st.session_state.tf_warranty = t.get("warranty_requirement", "")
    st.session_state.tf_sla = t.get("sla_requirement", "")
    st.session_state.tf_support = t.get("support_requirement", "")

    st.session_state._tf_mandatory_items = [{"id": i, "text": v} for i, v in enumerate(t.get("mandatory_requirements", []))]
    st.session_state._tf_mandatory_next_id = len(st.session_state._tf_mandatory_items)
    st.session_state._tf_cert_items = [{"id": i, "text": v} for i, v in enumerate(t.get("certifications", []))]
    st.session_state._tf_cert_next_id = len(st.session_state._tf_cert_items)
    st.session_state._tf_tech_items = [{"id": i, "text": v} for i, v in enumerate(t.get("technical_requirements", []))]
    st.session_state._tf_tech_next_id = len(st.session_state._tf_tech_items)

    weights = t.get("evaluation_criteria", DEFAULT_EVALUATION_CRITERIA)
    for dim in DEFAULT_EVALUATION_CRITERIA:
        st.session_state[f"tf_w_{dim}"] = round(weights.get(dim, DEFAULT_EVALUATION_CRITERIA[dim]) * 100)

    st.session_state._tf_initialized = True


def _apply_ai_draft(draft: dict) -> None:
    st.session_state.tf_title = draft.get("title") or st.session_state.tf_title
    st.session_state.tf_description = draft.get("description") or st.session_state.tf_description
    if draft.get("category") in _vendor_category_options():
        st.session_state.tf_category = draft["category"]
    st.session_state.tf_delivery_requirement = draft.get("delivery_requirement") or st.session_state.tf_delivery_requirement
    st.session_state.tf_warranty = draft.get("warranty_requirement") or st.session_state.tf_warranty

    for key, items_key, next_id_key in [
        ("technical_requirements", "_tf_tech_items", "_tf_tech_next_id"),
        ("mandatory_requirements", "_tf_mandatory_items", "_tf_mandatory_next_id"),
        ("certifications", "_tf_cert_items", "_tf_cert_next_id"),
    ]:
        values = [v for v in draft.get(key, []) if isinstance(v, str) and v.strip()]
        if values:
            st.session_state[items_key] = [{"id": i, "text": v} for i, v in enumerate(values)]
            st.session_state[next_id_key] = len(values)

    weights = draft.get("evaluation_criteria") or {}
    if weights and abs(sum(float(v) for v in weights.values()) - 100) < 1.5:
        for dim in DEFAULT_EVALUATION_CRITERIA:
            if dim in weights:
                st.session_state[f"tf_w_{dim}"] = round(float(weights[dim]))


def _build_tender_dict(edit_tender: dict | None) -> dict:
    weights = {dim: st.session_state[f"tf_w_{dim}"] / 100 for dim in DEFAULT_EVALUATION_CRITERIA}
    mandatory = [i["text"].strip() for i in st.session_state._tf_mandatory_items if i["text"].strip()]
    certifications = [i["text"].strip() for i in st.session_state._tf_cert_items if i["text"].strip()]
    technical = [i["text"].strip() for i in st.session_state._tf_tech_items if i["text"].strip()]
    tender = dict(edit_tender) if edit_tender else {}
    tender.update({
        "title": st.session_state.tf_title.strip(),
        "description": st.session_state.tf_description.strip(),
        "category": st.session_state.tf_category,
        "vendor_category_match": [st.session_state.tf_category],
        "department": st.session_state.tf_department.strip(),
        "procurement_type": st.session_state.tf_procurement_type,
        "budget": st.session_state.tf_budget,
        "currency": st.session_state.tf_currency,
        "quantity": st.session_state.tf_quantity,
        "submission_deadline": st.session_state.tf_deadline_text,
        "contract_start_date": st.session_state.tf_start_text,
        "contract_duration": st.session_state.tf_duration.strip(),
        "technical_requirements": technical,
        "mandatory_requirements": mandatory,
        "certifications": certifications,
        "delivery_requirement": st.session_state.tf_delivery_requirement.strip(),
        "delivery_location": st.session_state.tf_delivery_location.strip(),
        "minimum_on_time_delivery": st.session_state.tf_min_otd,
        "warranty_requirement": st.session_state.tf_warranty.strip(),
        "sla_requirement": st.session_state.tf_sla.strip(),
        "support_requirement": st.session_state.tf_support.strip(),
        "evaluation_criteria": weights,
        "min_certifications": max(len(certifications), 1),
        "min_quality_rating": 6.5,
    })
    return tender


def _reset_form_state() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith("tf_") or key.startswith("_tf_"):
            del st.session_state[key]


@st.dialog("Tender Details", width="large")
def render_tender_dialog(edit_tender_id: str | None = None) -> None:
    edit_tender = tender_repository.get_tender(edit_tender_id) if edit_tender_id else None
    is_edit = edit_tender is not None
    _init_draft(edit_tender)

    if not is_edit:
        st.markdown("**Describe what you want to procure**")
        st.text_area(
            "Description", key="tf_ai_description", label_visibility="collapsed", height=90,
            placeholder=(
                "We need 500 business laptops with 16GB RAM, i7 processors, 512GB SSDs, "
                "three-year warranty, delivery within 30 days and a total budget of $250,000."
            ),
        )
        if st.button("Generate Tender Details", icon=":material/auto_awesome:", key="tf_ai_generate"):
            if not llm_service.get_api_key():
                st.warning("No Claude API key configured — fill in the details manually below.", icon=":material/warning:")
            else:
                with st.spinner("Drafting tender details..."):
                    draft = generate_tender_draft(st.session_state.tf_ai_description)
                if draft:
                    _apply_ai_draft(draft)
                    st.success("Draft proposed below — review and edit before saving.", icon=":material/check_circle:")
                else:
                    st.warning("Could not generate a draft — fill in the details manually below.", icon=":material/warning:")
        st.divider()

    st.markdown("##### Basic Information")
    st.text_input("Tender Title *", key="tf_title")
    st.text_area("Tender Description", key="tf_description", height=70)
    bc1, bc2, bc3 = st.columns(3)
    bc1.selectbox("Procurement Category *", _vendor_category_options(), key="tf_category")
    bc2.text_input("Department / Business Unit", key="tf_department")
    bc3.selectbox("Procurement Type", PROCUREMENT_TYPES, key="tf_procurement_type")

    st.markdown("##### Commercial Details")
    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.number_input("Estimated Budget", min_value=0.0, step=100.0, key="tf_budget")
    cc2.selectbox("Currency", CURRENCIES, key="tf_currency")
    cc3.number_input("Quantity", min_value=0, step=1, key="tf_quantity")
    cc4.text_input("Contract Duration", key="tf_duration", placeholder="e.g. 3 years")
    dc1, dc2 = st.columns(2)
    dc1.text_input("Bid Submission Deadline", key="tf_deadline_text", placeholder="YYYY-MM-DD")
    dc2.text_input("Expected Contract Start Date", key="tf_start_text", placeholder="YYYY-MM-DD")

    st.markdown("##### Delivery Requirements")
    dr1, dr2, dr3 = st.columns(3)
    dr1.text_input("Required Delivery Timeline", key="tf_delivery_requirement", placeholder="e.g. Within 45 days")
    dr2.text_input("Delivery Location", key="tf_delivery_location")
    dr3.number_input("On-Time Delivery Requirement (%)", min_value=0, max_value=100, key="tf_min_otd")

    st.markdown("##### Mandatory Requirements")
    _list_editor("Mandatory Requirements", "_tf_mandatory_items", "_tf_mandatory_next_id", "e.g. Minimum 16GB RAM")

    st.markdown("##### Certifications")
    _list_editor("Certifications", "_tf_cert_items", "_tf_cert_next_id", "e.g. ISO 9001")

    with st.expander("Technical Requirements (optional detail)"):
        _list_editor("Technical Requirements", "_tf_tech_items", "_tf_tech_next_id", "e.g. 15-inch display")

    st.markdown("##### Warranty / Service Requirements")
    wc1, wc2, wc3 = st.columns(3)
    wc1.text_input("Warranty Requirement", key="tf_warranty")
    wc2.text_input("Service-Level Agreement", key="tf_sla")
    wc3.text_input("Support Requirement", key="tf_support")

    st.markdown("##### Evaluation Criteria")
    st.caption("Scoring weights for this tender — must total 100%.")
    wcols = st.columns(6)
    dims = list(DEFAULT_EVALUATION_CRITERIA)
    labels = ["Technical Compliance", "Price", "Delivery", "Past Performance", "Warranty", "Risk"]
    for col, dim, label in zip(wcols, dims, labels):
        col.number_input(label, min_value=0, max_value=100, step=1, key=f"tf_w_{dim}")
    total_weight = sum(st.session_state[f"tf_w_{dim}"] for dim in dims)
    if total_weight == 100:
        ui_components.status_badge(f"Total: {total_weight}%", tone="success")
    else:
        ui_components.status_badge(f"Total: {total_weight}% (must equal 100%)", tone="danger")

    st.divider()
    can_submit = bool(st.session_state.tf_title.strip()) and total_weight == 100
    submit_label = "Save Changes" if is_edit else "Create Tender"
    col_cancel, col_submit = st.columns([1, 1])
    if col_cancel.button("Cancel", use_container_width=True):
        _reset_form_state()
        st.rerun()
    if col_submit.button(submit_label, type="primary", icon=":material/check:", use_container_width=True, disabled=not can_submit):
        tender = _build_tender_dict(edit_tender)
        if is_edit:
            tender_repository.update_tender(edit_tender_id, tender)
            audit.log_action("Tender Updated", "Procurement", tender["title"], previous=edit_tender.get("title"), new=tender["title"], status="Success")
            new_id = edit_tender_id
        else:
            new_id = tender_repository.create_tender(tender)
            audit.log_action("Tender Created", "Procurement", tender["title"], new=new_id, status="Success")
        _reset_form_state()
        st.session_state.selected_tender_id = new_id
        st.session_state["tw_tender_select"] = new_id
        st.toast("Tender created successfully." if not is_edit else "Tender updated successfully.", icon=":material/check_circle:")
        st.switch_page("views/dashboard.py")
    if not can_submit:
        st.caption("Enter a tender title and make sure evaluation weights total 100% before saving.")
