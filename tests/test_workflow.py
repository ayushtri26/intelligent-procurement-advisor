"""Tests for the implicit-tender workflow state machine (src/workflow.py)."""
import streamlit as st

from src import workflow


def setup_function():
    st.session_state.clear()


def test_init_workflow_starts_at_draft():
    workflow.init_workflow()
    assert workflow.stage_name() == "Draft"
    assert workflow.stage_index() == 0


def test_advance_stage_moves_forward():
    workflow.init_workflow()
    workflow.advance_stage("AI Analysis")
    assert workflow.stage_name() == "AI Analysis"
    assert workflow.stage_index() == workflow.TENDER_STAGES.index("AI Analysis")


def test_advance_stage_is_idempotent_never_moves_backward():
    workflow.init_workflow()
    workflow.advance_stage("Director Approval")
    idx_after_first = workflow.stage_index()
    workflow.advance_stage("Uploaded")  # earlier stage — must not regress
    assert workflow.stage_index() == idx_after_first


def test_mark_data_uploaded_and_ai_analysis_complete():
    workflow.init_workflow()
    workflow.mark_data_uploaded(30)
    assert workflow.is_stage_reached("Uploaded")
    workflow.mark_ai_analysis_complete("Everest Logistics Partners")
    assert workflow.is_stage_reached("AI Analysis")


def test_manager_then_director_approval_sequence():
    workflow.init_workflow()
    workflow.mark_manager_approved("Vendor A")
    assert workflow.is_stage_reached("Manager Approval")
    assert not workflow.is_stage_reached("Director Approval")

    workflow.mark_director_approved("Vendor A")
    assert workflow.is_stage_reached("Director Approval")
    assert workflow.is_stage_reached("Approved")


def test_mark_awarded_records_contract_and_advances_stage():
    workflow.init_workflow()
    workflow.mark_awarded("Everest Logistics Partners", "V005")
    assert workflow.stage_name() == "Awarded"
    assert len(st.session_state.awarded_vendors) == 1
    record = st.session_state.awarded_vendors[0]
    assert record["vendor_id"] == "V005"
    assert record["vendor_name"] == "Everest Logistics Partners"
    assert "awarded_at" in record


def test_advance_stage_logs_audit_entry_against_tender_name():
    from src import audit

    workflow.init_workflow()
    workflow.advance_stage("Uploaded", detail="30 vendors loaded")
    df = audit.get_audit_df()
    assert len(df) == 1
    assert df.iloc[0]["Action"] == "Tender Stage Advanced"
    # Affected Object must be the tender name (not the detail string) so
    # views/tenders.py's timeline filter (audit.events_for_object) finds it.
    assert df.iloc[0]["Affected Object"] == workflow.DEFAULT_TENDER_NAME
    assert df.iloc[0]["Previous Value"] == "Draft"
    assert "Uploaded" in df.iloc[0]["New Value"]
    assert "30 vendors loaded" in df.iloc[0]["New Value"]


def test_advance_stage_events_are_findable_via_events_for_object():
    from src import audit

    workflow.init_workflow()
    workflow.mark_data_uploaded(30)
    workflow.mark_ai_analysis_complete("Everest Logistics Partners")
    matches = audit.events_for_object(st.session_state.tender_name)
    assert len(matches) == 2


def test_is_stage_reached_false_for_future_stage():
    workflow.init_workflow()
    assert not workflow.is_stage_reached("Awarded")
