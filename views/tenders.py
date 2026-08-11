"""Tenders — the implicit single-tender workflow stepper and its activity
timeline. The "tender" is the currently loaded vendor CSV; stage advancement
is handled by src/workflow.py and reflects real events (data uploaded,
analysis complete, approvals) rather than being independently editable."""
import streamlit as st

from src import audit, ui_components, workflow

st.title("Tenders")

new_name = st.text_input("Tender name", value=st.session_state.tender_name)
if new_name != st.session_state.tender_name:
    old_name = st.session_state.tender_name
    st.session_state.tender_name = new_name
    audit.log_action("Tender Renamed", "Procurement", new_name, previous=old_name, new=new_name)
    st.rerun()

st.subheader(f"Current Tender: {st.session_state.tender_name}")
ui_components.stepper(workflow.TENDER_STAGES, workflow.stage_index())
st.caption(f"Current stage: **{workflow.stage_name()}**")

st.header("Activity Timeline")
events = audit.events_for_object(st.session_state.tender_name)
timeline_events = [
    {"title": f"{e['Action']} — {e['Affected Object']}", "meta": f"{e['Timestamp']} · {e['Username']} ({e['Role']})"}
    for e in reversed(events)
]
ui_components.timeline(timeline_events)
