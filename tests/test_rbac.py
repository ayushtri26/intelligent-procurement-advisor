"""Tests for simulated role-based access control (src/rbac.py)."""
import streamlit as st

from src import rbac


def setup_function():
    st.session_state.clear()


def test_init_identity_sets_defaults():
    rbac.init_identity()
    assert rbac.current_role() == rbac.DEFAULT_ROLE
    assert rbac.current_user_name() == rbac.DEFAULT_USER_NAME


def test_admin_can_access_every_page():
    for page in rbac.ALL_PAGE_KEYS:
        assert rbac.can_access(page, role="Admin")


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


def test_no_role_can_access_administration_except_admin():
    admin_only_pages = {"users", "roles", "settings"}
    for role in rbac.ROLES:
        if role == "Admin":
            continue
        for page in admin_only_pages:
            assert not rbac.can_access(page, role=role), f"{role} should not access {page}"


def test_manager_and_director_approval_gates():
    assert rbac.can_approve_manager_stage("Procurement Manager")
    assert rbac.can_approve_manager_stage("Admin")
    assert not rbac.can_approve_manager_stage("Executive")
    assert not rbac.can_approve_manager_stage("Auditor")

    assert rbac.can_approve_director_stage("Executive")
    assert rbac.can_approve_director_stage("Admin")
    assert not rbac.can_approve_director_stage("Procurement Manager")


def test_weight_edit_permission():
    assert rbac.can_edit_weights("Admin")
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


def test_filter_pages_admin_sees_everything():
    pages_by_section = {
        "Dashboard": [("dashboard", "DASH_PAGE")],
        "Administration": [("settings", "SETTINGS_PAGE")],
    }
    filtered = rbac.filter_pages(pages_by_section, role="Admin")
    assert filtered["Dashboard"] == ["DASH_PAGE"]
    assert filtered["Administration"] == ["SETTINGS_PAGE"]
