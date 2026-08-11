"""Tests for role-based access control and login-derived role assignment (src/rbac.py)."""
import streamlit as st

from src import rbac


def setup_function():
    st.session_state.clear()


def test_init_identity_sets_safe_defaults_when_no_user_yet():
    rbac.init_identity()
    assert rbac.current_role() == rbac.DEFAULT_ROLE
    assert rbac.current_user_name() == ""


def test_set_user_derives_role_and_stores_identity():
    rbac.set_user("Ayush Tripathi", "ayush@example.com", is_real_login=True)
    assert rbac.current_user_name() == "Ayush Tripathi"
    assert rbac.current_user_email() == "ayush@example.com"
    assert rbac.current_role() == "Procurement Manager"


def test_set_user_logs_a_login_audit_event():
    from src import audit

    rbac.set_user("Someone Else", "someone@example.com", is_real_login=True)
    df = audit.get_audit_df()
    assert len(df) == 1
    assert df.iloc[0]["Action"] == "User Login"


def test_assign_role_from_name_matches_every_mapped_name():
    for needle, expected_role in rbac.ROLE_NAME_MAP.items():
        assert rbac.assign_role_from_name(needle.title() + " Someone") == expected_role


def test_assign_role_from_name_is_case_insensitive():
    assert rbac.assign_role_from_name("ayush tripathi") == "Procurement Manager"
    assert rbac.assign_role_from_name("AYUSH TRIPATHI") == "Procurement Manager"


def test_assign_role_from_name_matches_anywhere_in_string():
    assert rbac.assign_role_from_name("Maha Sharma") == "Procurement Manager"
    assert rbac.assign_role_from_name("Dr. Anil Kumar") == "Procurement Manager"


def test_assign_role_from_name_falls_back_to_administrator():
    assert rbac.assign_role_from_name("Jordan Lee") == "Administrator"
    assert rbac.assign_role_from_name("") == "Administrator"
    assert rbac.assign_role_from_name(None) == "Administrator"


def test_administrator_can_access_every_page():
    for page in rbac.ALL_PAGE_KEYS:
        assert rbac.can_access(page, role="Administrator")


def test_vendor_role_is_heavily_restricted():
    assert rbac.can_access("dashboard", role="Vendor")
    assert not rbac.can_access("audit_logs", role="Vendor")
    assert not rbac.can_access("settings", role="Vendor")
    assert not rbac.can_access("approvals", role="Vendor")


def test_auditor_has_full_governance_access():
    for page in ["audit_logs", "activity_timeline", "user_activity"]:
        assert rbac.can_access(page, role="Auditor")
    assert not rbac.can_access("settings", role="Auditor")
    assert not rbac.can_access("approvals", role="Auditor")


def test_no_role_can_access_administration_except_administrator():
    admin_only_pages = {"users", "roles", "settings"}
    for role in rbac.ROLES:
        if role == "Administrator":
            continue
        for page in admin_only_pages:
            assert not rbac.can_access(page, role=role), f"{role} should not access {page}"


def test_manager_and_director_approval_gates():
    assert rbac.can_approve_manager_stage("Procurement Manager")
    assert rbac.can_approve_manager_stage("Administrator")
    assert not rbac.can_approve_manager_stage("Executive")
    assert not rbac.can_approve_manager_stage("Auditor")

    assert rbac.can_approve_director_stage("Executive")
    assert rbac.can_approve_director_stage("Administrator")
    assert not rbac.can_approve_director_stage("Procurement Manager")


def test_weight_edit_permission():
    assert rbac.can_edit_weights("Administrator")
    assert rbac.can_edit_weights("Procurement Manager")
    assert not rbac.can_edit_weights("Executive")
    assert not rbac.can_edit_weights("Auditor")
    assert not rbac.can_edit_weights("Vendor")


def test_filter_pages_drops_pages_and_empty_sections():
    pages_by_section = {
        "Dashboard": [("dashboard", "DASH_PAGE")],
        "Administration": [("settings", "SETTINGS_PAGE"), ("users", "USERS_PAGE")],
    }
    filtered = rbac.filter_pages(pages_by_section, role="Vendor")
    assert "Dashboard" in filtered
    assert filtered["Dashboard"] == ["DASH_PAGE"]
    assert "Administration" not in filtered  # Vendor can't see any Administration page -> section dropped


def test_filter_pages_administrator_sees_everything():
    pages_by_section = {
        "Dashboard": [("dashboard", "DASH_PAGE")],
        "Administration": [("settings", "SETTINGS_PAGE")],
    }
    filtered = rbac.filter_pages(pages_by_section, role="Administrator")
    assert filtered["Dashboard"] == ["DASH_PAGE"]
    assert filtered["Administration"] == ["SETTINGS_PAGE"]
