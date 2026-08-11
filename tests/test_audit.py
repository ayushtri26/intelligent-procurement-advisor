"""Tests for the session-scoped audit log (src/audit.py)."""
import pandas as pd
import streamlit as st

from src import audit


def setup_function():
    st.session_state.clear()


def test_log_action_appends_all_required_fields():
    st.session_state.user = {"name": "Test User", "email": "test@example.com", "role": "Administrator"}
    audit.log_action("Vendor Viewed", "Procurement", "V001 — Test Vendor", previous="old", new="new", status="Success")

    df = audit.get_audit_df()
    assert len(df) == 1
    row = df.iloc[0]
    for col in audit.AUDIT_COLUMNS:
        assert col in df.columns
    assert row["Username"] == "Test User"
    assert row["Role"] == "Administrator"
    assert row["Action"] == "Vendor Viewed"
    assert row["Module"] == "Procurement"
    assert row["Affected Object"] == "V001 — Test Vendor"
    assert row["Previous Value"] == "old"
    assert row["New Value"] == "new"
    assert row["Status"] == "Success"
    assert row["IP Address"]
    assert row["Browser"]


def test_get_audit_df_empty_has_correct_columns():
    df = audit.get_audit_df()
    assert df.empty
    assert list(df.columns) == audit.AUDIT_COLUMNS


def test_audit_df_sorted_most_recent_first():
    audit.log_action("Action One", "Procurement", "obj1")
    audit.log_action("Action Two", "Procurement", "obj2")
    df = audit.get_audit_df()
    assert df.iloc[0]["Action"] == "Action Two"
    assert df.iloc[1]["Action"] == "Action One"


def test_export_csv_roundtrip():
    audit.log_action("Export Test", "Governance", "obj")
    csv_bytes = audit.export_csv()
    assert isinstance(csv_bytes, bytes)
    text = csv_bytes.decode("utf-8")
    assert "Export Test" in text
    assert "Timestamp" in text


def test_log_action_never_raises_on_bad_status_value():
    # status is just stored as-is; ensure no exception even with unusual input
    audit.log_action("Weird", "Module", object(), status="Success")
    df = audit.get_audit_df()
    assert len(df) == 1


def test_events_for_object_filters_by_substring():
    audit.log_action("Tender Uploaded", "Procurement", "Q3 Vendor Evaluation Tender")
    audit.log_action("Vendor Viewed", "Procurement", "Everest Logistics Partners")
    matches = audit.events_for_object("Q3 Vendor")
    assert len(matches) == 1
    assert matches[0]["Action"] == "Tender Uploaded"


def test_events_for_object_no_match_returns_empty():
    audit.log_action("Vendor Viewed", "Procurement", "Everest Logistics Partners")
    assert audit.events_for_object("Nonexistent Tender") == []
