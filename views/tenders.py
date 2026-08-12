"""Tenders — full details of the selected tender (from the tender
repository, src/tender_repository.py), its tender-specific recommended
vendor (from the centralized src/recommendation_engine.py object), the
implicit single-tender workflow stepper, and its activity timeline.

Tender SELECTION happens once, globally, in the sidebar Tender Workspace
(src/tender_context.py) — this page only displays and edits the currently
selected tender; it does not maintain its own selector."""
import streamlit as st

from src import audit, rbac, tender_form, tender_repository, ui_components, workflow

tender = st.session_state.selected_tender
recommendation = st.session_state.recommendation
tender_id = st.session_state.selected_tender_id
can_manage = rbac.can_manage_tenders()
is_draft = tender.get("status") == "Draft"

st.title("Tenders")

# --------------------------------------------------------------------------
# Header — identity, status, and actions.
# --------------------------------------------------------------------------
head_l, head_r = st.columns([3, 2])
with head_l:
    st.subheader(tender["title"])
    st.caption(f"{tender_id} · {tender.get('category', 'N/A')}")
with head_r:
    _status_tone = {
        "Draft": "neutral", "Open": "info", "Under Evaluation": "warning",
        "Awaiting Approval": "warning", "Awarded": "success", "Closed": "neutral",
    }.get(tender.get("status"), "neutral")
    ui_components.status_badge(tender.get("status", "Draft"), tone=_status_tone)
    btn_edit, btn_dup = st.columns(2)
    with btn_edit:
        if st.button("Edit Tender", icon=":material/edit:", disabled=not (can_manage and is_draft), use_container_width=True):
            tender_form.render_tender_dialog(edit_tender_id=tender_id)
    with btn_dup:
        if st.button("Duplicate Tender", icon=":material/content_copy:", disabled=not can_manage, use_container_width=True):
            new_id = tender_repository.duplicate_tender(tender_id, rbac.current_user_name())
            audit.log_action("Tender Created", "Procurement", f"Duplicated from {tender['title']}", new=new_id, status="Success")
            st.session_state.selected_tender_id = new_id
            st.session_state["tw_tender_select"] = new_id
            st.toast("Tender duplicated as a new Draft.", icon=":material/check_circle:")
            st.rerun()
    if not is_draft and can_manage:
        st.caption("Only Draft tenders can be edited.")

st.write("")
ui_components.stepper(workflow.TENDER_STAGES, workflow.stage_index())
st.caption(f"Current stage: **{workflow.stage_name()}**")

# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------
st.header("Overview")
with st.container(border=True):
    o1, o2, o3, o4 = st.columns(4)
    o1.metric("Budget", f"{tender.get('currency', 'USD')} {tender.get('budget', 0):,.0f}")
    o2.metric("Quantity", f"{tender.get('quantity', 0):,}")
    o3.metric("Submission Deadline", tender.get("submission_deadline") or "N/A")
    o4.metric("Eligible Vendor Category", ", ".join(tender.get("vendor_category_match", [])))
    m1, m2, m3 = st.columns(3)
    m1.write(f"**Created by:** {tender.get('created_by', 'N/A')}")
    m2.write(f"**Created:** {tender.get('created_at', 'N/A')}")
    m3.write(f"**Last modified:** {tender.get('last_modified_at', 'N/A')}")
    if tender.get("description"):
        st.caption(tender["description"])

st.header("Requirements")
with st.container(border=True):
    req_col, mand_col = st.columns(2)
    with req_col:
        st.markdown("**Technical requirements**")
        for r in tender.get("technical_requirements", []) or ["None specified"]:
            st.markdown(f"- {r}")
    with mand_col:
        st.markdown("**Mandatory requirements**")
        for r in tender.get("mandatory_requirements", []) or ["None specified"]:
            st.markdown(f"- {r}")

    st.markdown("**Certifications:** " + (", ".join(tender.get("certifications", [])) or "None specified"))

    d1, d2, d3 = st.columns(3)
    d1.write(f"**Delivery requirement:** {tender.get('delivery_requirement', 'N/A')}")
    d2.write(f"**Delivery location:** {tender.get('delivery_location', 'N/A')}")
    d3.write(f"**Min. on-time delivery:** {tender.get('minimum_on_time_delivery', 'N/A')}%")

    w1, w2, w3 = st.columns(3)
    w1.write(f"**Warranty:** {tender.get('warranty_requirement', 'N/A')}")
    w2.write(f"**SLA:** {tender.get('sla_requirement', 'N/A')}")
    w3.write(f"**Support:** {tender.get('support_requirement', 'N/A')}")

    st.markdown("**Evaluation criteria weighting**")
    ec_cols = st.columns(len(tender["evaluation_criteria"]))
    for col, (dim, weight) in zip(ec_cols, tender["evaluation_criteria"].items()):
        col.metric(dim.replace("_", " ").title(), f"{weight * 100:.0f}%")

# --------------------------------------------------------------------------
# Recommendation
# --------------------------------------------------------------------------
st.header("Recommended Vendor for This Tender")
if recommendation["vendor_id"]:
    with st.container(border=True):
        rc1, rc2 = st.columns([3, 1])
        with rc1:
            st.markdown(f"**{recommendation['vendor_name']}** ({recommendation['vendor_id']})")
            st.caption(recommendation["reasoning"])
        with rc2:
            st.metric("Score", f"{recommendation['final_score']:.1f} / 100")
        ui_components.status_badge(
            recommendation["eligibility_status"],
            tone="success" if recommendation["eligibility_status"] == "Qualified" else "warning",
        )
    if len(recommendation["ranking"]) > 1:
        with st.expander(f"Full ranking for this tender ({len(recommendation['ranking'])} vendor(s))"):
            ui_components.data_table(recommendation["ranking"])
else:
    st.warning(recommendation["risks"][0] if recommendation["risks"] else "No eligible vendor found.", icon=":material/warning:")
    closest = recommendation.get("closest_matches") or []
    if closest:
        st.markdown("**Closest Matches**")
        for c in closest:
            st.markdown(f"- {c['vendor_name']} — {c['match_pct']:.0f}% requirement match")
        st.caption("Consider expanding the supplier pool or modifying non-mandatory requirements.")

st.header("Activity Timeline")
events = audit.events_for_object(tender["title"])
timeline_events = [
    {"title": f"{e['Action']} — {e['Affected Object']}", "meta": f"{e['Timestamp']} · {e['Username']} ({e['Role']})"}
    for e in reversed(events)
]
ui_components.timeline(timeline_events)
