"""User Activity — the audit log grouped and filterable by user."""
import streamlit as st

from src import audit, ui_components

st.title("User Activity")

df = audit.get_audit_df()
if df.empty:
    ui_components.empty_state("No Activity Yet", "Actions will appear here as you use the app.")
else:
    summary = df.groupby(["Username", "Role"]).size().reset_index(name="Action Count").sort_values("Action Count", ascending=False)
    st.subheader("Actions per User")
    ui_components.data_table(summary)

    st.subheader("Drill into a user")
    chosen = st.selectbox("User", sorted(df["Username"].unique().tolist()))
    user_df = df[df["Username"] == chosen]
    st.caption(f"{len(user_df)} action(s) by {chosen}")
    ui_components.data_table(user_df)
