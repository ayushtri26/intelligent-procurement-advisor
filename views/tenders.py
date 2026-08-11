"""Tenders — the selected tender's structured requirements (from the tender
registry, src/tenders_data.py), its tender-specific recommended vendor (from
the centralized src/recommendation_engine.py object), the implicit
single-tender workflow stepper, and its activity timeline.

Tender SELECTION itself happens in the sidebar (Data & Scoring -> Tender)
since it drives the whole recommendation pipeline computed once in app.py;
this page displays the selected tender's detail and lets you rename it for
this session (the rename is cosmetic only — it does not change which
registry tender/category/requirements are being evaluated)."""
import streamlit as st

from src import audit, ui_components, workflow

tender = st.session_state.selected_tender
recommendation = st.session_state.recommendation

st.title("Tenders")

new_name = st.text_input("Tender name (this session only)", value=st.session_state.tender_name)
if new_name != st.session_state.tender_name:
    old_name = st.session_state.tender_name
    st.session_state.tender_custom_names[st.session_state.selected_tender_id] = new_name
    st.session_state.tender_name = new_name
    audit.log_action("Tender Renamed", "Procurement", new_name, previous=old_name, new=new_name)
    st.rerun()

st.caption(f"Registry tender: {tender['title']} · Category: {tender['category']} · Select a different tender from the sidebar (Data & Scoring).")
ui_components.stepper(workflow.TENDER_STAGES, workflow.stage_index())
st.caption(f"Current stage: **{workflow.stage_name()}**")

st.header("Tender Requirements")
with st.container(border=True):
    c1, c2, c3 = st.columns(3)
    c1.metric("Budget", f"${tender['budget']:,.0f}")
    c2.metric("Quantity", f"{tender['quantity']:,}")
    c3.metric("Eligible Vendor Category", ", ".join(tender["vendor_category_match"]))

    req_col, mand_col = st.columns(2)
    with req_col:
        st.markdown("**Technical requirements**")
        for r in tender["technical_requirements"]:
            st.markdown(f"- {r}")
    with mand_col:
        st.markdown("**Mandatory requirements**")
        for r in tender["mandatory_requirements"]:
            st.markdown(f"- {r}")

    st.markdown("**Certifications required:** " + ", ".join(tender["certifications"]))
    st.markdown(f"**Delivery requirement:** {tender['delivery_requirement']}")
    st.markdown(f"**Warranty requirement:** {tender['warranty_requirement']}")

    st.markdown("**Evaluation criteria weighting**")
    ec_cols = st.columns(len(tender["evaluation_criteria"]))
    for col, (dim, weight) in zip(ec_cols, tender["evaluation_criteria"].items()):
        col.metric(dim.replace("_", " ").title(), f"{weight * 100:.0f}%")

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
    st.warning("No eligible vendor found for this tender's category or mandatory requirements.", icon=":material/warning:")

st.header("Activity Timeline")
events = audit.events_for_object(st.session_state.tender_name)
timeline_events = [
    {"title": f"{e['Action']} — {e['Affected Object']}", "meta": f"{e['Timestamp']} · {e['Username']} ({e['Role']})"}
    for e in reversed(events)
]
ui_components.timeline(timeline_events)
