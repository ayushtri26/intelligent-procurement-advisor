"""Activity Timeline — a global chronological view of everything logged this
session, built entirely from the audit log."""
import streamlit as st

from src import audit, ui_components

st.title("Activity Timeline")
st.caption("Chronological view of every logged action this session.")

df = audit.get_audit_df()
if df.empty:
    ui_components.empty_state("No Activity Yet", "Actions will appear here as you use the app.")
else:
    limit = st.slider("Show most recent N events", 5, min(200, len(df)), min(50, len(df)))
    subset = df.head(limit)
    events = [
        {"title": f"{row['Action']} — {row['Affected Object']}", "meta": f"{row['Timestamp']} · {row['Username']} ({row['Role']}) · {row['Module']}"}
        for _, row in subset.iterrows()
    ]
    ui_components.timeline(events)
