"""Contracts — vendors approved and awarded this session. There is no
separate contract entity in the data model; a contract record is created the
moment a vendor completes the full approval workflow and is awarded
(see src/workflow.py mark_awarded)."""
import pandas as pd
import streamlit as st

from src import audit, ui_components

ranked_df = st.session_state.ranked_df
awarded = st.session_state.awarded_vendors

st.title("Contracts")
st.caption("Vendors that have completed the full approval workflow and been formally awarded this session.")

if not awarded:
    ui_components.empty_state(
        "No Contracts Awarded Yet",
        "Complete Manager and Director approval for a vendor in Approvals, then confirm the award to see it here.",
    )
else:
    df = pd.DataFrame(awarded)
    scores = ranked_df.set_index("vendor_id")["overall_score"]
    df["overall_score"] = df["vendor_id"].map(scores)
    ui_components.data_table(df.rename(columns={"vendor_name": "Vendor", "vendor_id": "Vendor ID", "awarded_at": "Awarded At", "overall_score": "Overall Score"}))

    st.header("Contract Activity")
    events = audit.get_audit_df()
    contract_events = events[events["Action"] == "Contract Awarded"]
    timeline_events = [
        {"title": f"Contract Awarded — {row['Affected Object']}", "meta": f"{row['Timestamp']} · {row['Username']} ({row['Role']})"}
        for _, row in contract_events.iterrows()
    ]
    ui_components.timeline(timeline_events)
