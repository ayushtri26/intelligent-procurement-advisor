"""Audit Logs — searchable, filterable record of every logged action this
session, with CSV export. See src/audit.py for the logging mechanism."""
import streamlit as st

from src import audit, ui_components

st.title("Audit Logs")
st.caption("Every significant action in this session is logged here. There is no backend database — this log is session-scoped; export to CSV for a durable record.")

df = audit.get_audit_df()

if df.empty:
    ui_components.empty_state("No Audit Entries Yet", "Actions like uploads, approvals, and weight changes will appear here as you use the app.")
else:
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        user_filter = st.selectbox("User", ["All"] + sorted(df["Username"].unique().tolist()))
    with f2:
        action_filter = st.selectbox("Action", ["All"] + sorted(df["Action"].unique().tolist()))
    with f3:
        module_filter = st.selectbox("Module", ["All"] + sorted(df["Module"].unique().tolist()))
    with f4:
        date_filter = st.date_input("Date", value=None)

    filtered = df.copy()
    if user_filter != "All":
        filtered = filtered[filtered["Username"] == user_filter]
    if action_filter != "All":
        filtered = filtered[filtered["Action"] == action_filter]
    if module_filter != "All":
        filtered = filtered[filtered["Module"] == module_filter]
    if date_filter:
        filtered = filtered[filtered["Timestamp"].str.startswith(str(date_filter))]

    st.caption(f"Showing {len(filtered)} of {len(df)} entries.")
    ui_components.data_table(filtered)

    st.download_button("Export to CSV", audit.export_csv(filtered), file_name="audit_log.csv", mime="text/csv", icon=":material/download:")

with st.expander("Responsible AI"):
    st.markdown(
        """
- **Human in the loop:** No vendor is ever auto-approved. Every recommendation ends with an explicit two-stage human review-and-approve step (Procurement → Approvals), each gated by a reviewer acknowledgement checkbox.
- **Explainable scoring:** Every recommendation traces back to visible per-feature scores and weights (Vendors → Vendor Inspection) — nothing is a black box.
- **Transparent weighting:** Scoring weights are sidebar-editable (role-permitting) and always visible; confidence/risk formulas are documented, simple, and deterministic (see `src/dashboard.py`).
- **Deterministic calculations:** All scores, rankings, and anomaly flags are computed by fixed Python/scikit-learn logic (`src/vendor_scoring.py`, `src/anomaly_detection.py`) — the LLM never calculates a number, only narrates results already computed elsewhere.
- **No automatic vendor approval:** The AI agent and the deterministic assistant can only recommend. `src/agent.py`'s system prompt explicitly forbids implying approval.
- **Document-grounded responses:** Document-derived claims are retrieved via the local RAG pipeline (AI Workspace → Document Intelligence) and cited with filename, page, and chunk id.
- **Bias considerations:** Scoring weights reflect whatever priorities are configured. If weights are set to systematically disadvantage a vendor category, this system will faithfully reflect that bias — weight configuration is a governance decision, not a neutral default.
- **Failure modes:** The Isolation Forest anomaly detector can both under- and over-flag vendors, especially with small vendor pools; treat flags as a prompt to investigate, not a verdict. The Claude agent falls back to the deterministic assistant on any API failure, and the chat clearly labels which path produced each answer.
- **Missing data handling:** Missing numeric fields are median-imputed and the affected vendor is tagged internally — this lowers that vendor's confidence rating and is surfaced in its due-diligence checklist.
- **This audit log is a demo control, not a security boundary:** roles and identity are self-declared (no real authentication exists), so this log demonstrates governance UX rather than providing tamper-proof evidence.
"""
    )
