"""Approvals — two-stage (Manager then Director) human approval workflow.

No vendor is ever approved automatically. This extends the original
single-shot approval into two sequential, role-gated confirmations, each
producing its own audit entry and advancing the tender's workflow stage
(src/workflow.py). The underlying evidence (build_recommendation_bundle) is
the same deterministic bundle used everywhere else in the app.
"""
from datetime import datetime

import streamlit as st

from src import audit, rbac, ui_components, workflow
from src.analytics_tools import build_recommendation_bundle

ranked_df = st.session_state.ranked_df
vendor_options = st.session_state.vendor_options

st.title("Approvals")
st.caption("No vendor is approved automatically. A person must explicitly review the evidence and confirm each stage.")

ui_components.stepper(workflow.TENDER_STAGES, workflow.stage_index())
st.write("")

approval_options = ["— Select a vendor —"] + vendor_options.tolist()
choice = st.selectbox("Select the vendor to route through approval", approval_options, key="approval_choice")

if choice != "— Select a vendor —":
    choice_id = choice.split(" — ")[0]
    choice_row = ranked_df.loc[ranked_df["vendor_id"] == choice_id].iloc[0]
    choice_bundle = build_recommendation_bundle(ranked_df, choice_row, "Selected by reviewer for approval.")
    vendor_label = f"{choice_row['vendor_name']} ({choice_row['vendor_id']})"

    with st.expander("Review evidence before approving", expanded=True):
        st.write(f"**Overall score:** {choice_row['overall_score']:.1f}/100 · Rank #{int(choice_row['rank'])} · Confidence: {choice_bundle['confidence']}")
        st.write("**Key reasons:** " + "; ".join(choice_bundle["key_reasons"]))
        if choice_bundle["risks"]:
            st.write("**Risks:** " + "; ".join(choice_bundle["risks"]))
        st.write("**Due diligence:** " + "; ".join(choice_bundle["due_diligence"]))

    if choice_row["is_anomalous"]:
        st.warning("This vendor is flagged as anomalous. Review the risks carefully before approving.", icon=":material/warning:")

    same_vendor = st.session_state.manager_approval_record and st.session_state.manager_approval_record.get("vendor_id") == choice_id

    # --- Stage 1: Manager Approval ---------------------------------------
    st.subheader("Stage 1 · Manager Approval")
    if not rbac.can_approve_manager_stage():
        st.caption(f"Requires Procurement Manager or Administrator role (current role: {rbac.current_role()}).")
    elif same_vendor:
        rec = st.session_state.manager_approval_record
        st.success(f"Approved by {rec['reviewer']} on {rec['timestamp']}", icon=":material/check_circle:")
    else:
        mgr_reviewer = st.text_input("Reviewer name", key="mgr_reviewer_name", placeholder="e.g. Priya Shah, Procurement Manager")
        mgr_reason = st.text_area("Approval reason / justification", key="mgr_reason")
        st.session_state.manager_reviewed_ack = st.checkbox("I have reviewed the AI recommendation.", value=st.session_state.manager_reviewed_ack, key="mgr_ack")
        mgr_disabled = not st.session_state.manager_reviewed_ack or not mgr_reviewer.strip()
        if mgr_disabled:
            st.caption("Enter a reviewer name and check the review acknowledgement to enable this stage.")
        if st.button("Confirm Manager Approval", type="primary", disabled=mgr_disabled, key="mgr_confirm"):
            st.session_state.manager_approval_record = {
                "vendor_id": choice_id, "vendor": vendor_label,
                "reason": mgr_reason.strip() or "; ".join(choice_bundle["key_reasons"]),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "reviewer": mgr_reviewer.strip(),
            }
            workflow.mark_manager_approved(vendor_label)
            audit.log_action("Manager Approval Granted", "Procurement", vendor_label, status="Success")
            st.rerun()

    # --- Stage 2: Director Approval ----------------------------------------
    st.subheader("Stage 2 · Director Approval")
    if not same_vendor:
        st.caption("Awaiting Manager Approval for this vendor.")
    elif not rbac.can_approve_director_stage():
        st.caption(f"Requires Executive or Administrator role (current role: {rbac.current_role()}).")
    else:
        director_done = st.session_state.director_approval_record and st.session_state.director_approval_record.get("vendor_id") == choice_id
        if director_done:
            rec = st.session_state.director_approval_record
            st.success(f"Approved by {rec['reviewer']} on {rec['timestamp']}", icon=":material/check_circle:")
        else:
            dir_reviewer = st.text_input("Reviewer name", key="dir_reviewer_name", placeholder="e.g. Alex Kim, VP Procurement")
            dir_reason = st.text_area("Approval reason / justification", key="dir_reason")
            st.session_state.director_reviewed_ack = st.checkbox("I have reviewed the AI recommendation and Manager approval.", value=st.session_state.director_reviewed_ack, key="dir_ack")
            dir_disabled = not st.session_state.director_reviewed_ack or not dir_reviewer.strip()
            if dir_disabled:
                st.caption("Enter a reviewer name and check the review acknowledgement to enable final approval.")
            if st.button("Confirm Director Approval", type="primary", disabled=dir_disabled, key="dir_confirm"):
                record = {
                    "vendor_id": choice_id, "vendor": vendor_label,
                    "reason": dir_reason.strip() or "; ".join(choice_bundle["key_reasons"]),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "reviewer": dir_reviewer.strip(),
                    "decision": "Approved",
                }
                st.session_state.director_approval_record = record
                st.session_state.approved_vendor = choice_id
                st.session_state.approval_record = record
                workflow.mark_director_approved(vendor_label)
                audit.log_action("Director Approval Granted", "Procurement", vendor_label, status="Success")
                st.rerun()

    # Scoped to the currently-selected vendor (choice_id) so switching the
    # dropdown never shows a stale approval summary for a different vendor.
    director_matches_choice = (
        st.session_state.director_approval_record
        and st.session_state.director_approval_record.get("vendor_id") == choice_id
    )
    if director_matches_choice:
        record = st.session_state.director_approval_record
        st.header("Final Approval")
        st.success(f"Approved Vendor: {record['vendor']}", icon=":material/check_circle:")
        with st.container(border=True):
            st.markdown("#### Approval Summary")
            sc1, sc2 = st.columns(2)
            sc1.write(f"**Vendor:** {record['vendor']}")
            sc1.write(f"**Manager Reviewer:** {st.session_state.manager_approval_record['reviewer']}")
            sc1.write(f"**Director Reviewer:** {record['reviewer']}")
            sc2.write(f"**Timestamp:** {record['timestamp']}")
            sc2.write(f"**Decision:** {record['decision']}")
            st.write(f"**Reason:** {record['reason']}")

        already_awarded = any(a["vendor_id"] == choice_id for a in st.session_state.awarded_vendors)
        if already_awarded:
            st.info("This vendor has already been awarded the contract. See Contracts.")
        elif st.button("Confirm Award", type="primary", icon=":material/task_alt:"):
            workflow.mark_awarded(choice_row["vendor_name"], choice_row["vendor_id"])
            st.rerun()

        if st.button("Reset this vendor's approval"):
            if st.session_state.approved_vendor == choice_id:
                st.session_state.approved_vendor = None
                st.session_state.approval_record = None
            st.session_state.manager_approval_record = None
            st.session_state.director_approval_record = None
            st.session_state.manager_reviewed_ack = False
            st.session_state.director_reviewed_ack = False
            st.rerun()
