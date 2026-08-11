"""Simulated role-based access control.

There is no real backend or authentication in this app — this module
provides a session-state "who's signed in as what role" concept purely so
the navigation, approval workflow, and settings can behave differently per
role for demo purposes. Nothing here is a security boundary.
"""
from __future__ import annotations

import streamlit as st

from src import audit

ROLES = ["Admin", "Procurement Manager", "Executive", "Auditor", "Vendor"]
DEFAULT_ROLE = "Procurement Manager"
DEFAULT_USER_NAME = "Ayush Tripathi"

ALL_PAGE_KEYS = [
    "dashboard", "vendors", "tenders", "contracts", "approvals",
    "ai_assistant", "document_intelligence", "recommendations", "anomalies",
    "vendor_analytics", "spend_analytics", "risk_analytics",
    "audit_logs", "activity_timeline", "user_activity",
    "users", "roles", "settings",
]

# Which pages each role can see in the sidebar navigation.
PAGE_PERMISSIONS: dict[str, set[str]] = {
    "Admin": set(ALL_PAGE_KEYS),
    "Procurement Manager": {
        "dashboard", "vendors", "tenders", "contracts", "approvals",
        "ai_assistant", "document_intelligence", "recommendations", "anomalies",
        "vendor_analytics", "spend_analytics", "risk_analytics",
        "activity_timeline",
    },
    "Executive": {
        "dashboard", "recommendations", "approvals",
        "vendor_analytics", "spend_analytics", "risk_analytics",
        "activity_timeline",
    },
    "Auditor": {
        "dashboard", "vendors", "anomalies", "risk_analytics",
        "audit_logs", "activity_timeline", "user_activity",
    },
    "Vendor": {"dashboard"},
}

# Roles allowed to perform each approval stage (used inside views/approvals.py).
MANAGER_APPROVAL_ROLES = {"Admin", "Procurement Manager"}
DIRECTOR_APPROVAL_ROLES = {"Admin", "Executive"}
# Roles allowed to edit scoring weights (others see the sliders disabled).
WEIGHT_EDIT_ROLES = {"Admin", "Procurement Manager"}


def init_identity() -> None:
    if "current_role" not in st.session_state:
        st.session_state.current_role = DEFAULT_ROLE
    if "current_user_name" not in st.session_state:
        st.session_state.current_user_name = DEFAULT_USER_NAME


def current_role() -> str:
    return st.session_state.get("current_role", DEFAULT_ROLE)


def current_user_name() -> str:
    return st.session_state.get("current_user_name", DEFAULT_USER_NAME)


def can_access(page_key: str, role: str | None = None) -> bool:
    role = role or current_role()
    return page_key in PAGE_PERMISSIONS.get(role, set())


def can_approve_manager_stage(role: str | None = None) -> bool:
    return (role or current_role()) in MANAGER_APPROVAL_ROLES


def can_approve_director_stage(role: str | None = None) -> bool:
    return (role or current_role()) in DIRECTOR_APPROVAL_ROLES


def can_edit_weights(role: str | None = None) -> bool:
    return (role or current_role()) in WEIGHT_EDIT_ROLES


def render_identity_control() -> None:
    """Top-bar 'Signed in as' control. Switching role/name logs a User Login audit event."""
    init_identity()
    prev_role = st.session_state.current_role
    prev_name = st.session_state.current_user_name

    label = f"{st.session_state.current_user_name} · {st.session_state.current_role}"
    with st.popover(label, icon=":material/account_circle:", use_container_width=False):
        st.caption("Signed in as")
        new_name = st.text_input("Name", value=st.session_state.current_user_name, key="identity_name_input")
        new_role = st.selectbox("Role", ROLES, index=ROLES.index(st.session_state.current_role), key="identity_role_input")
        st.badge(new_role, color="blue")
        st.divider()
        theme = st.selectbox("Theme", ["System", "Light", "Dark"], key="identity_theme_input")
        if st.button("Reset session (clears all data)", icon=":material/restart_alt:"):
            # A full wipe makes a "User Logout" audit entry pointless (it would
            # be destroyed by the same click), so this is a plain reset, not a
            # logged action.
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    if new_name != prev_name or new_role != prev_role:
        st.session_state.current_user_name = new_name
        st.session_state.current_role = new_role
        audit.log_action(
            "User Login",
            "Administration",
            new_name,
            previous=f"{prev_name} ({prev_role})",
            new=f"{new_name} ({new_role})",
            status="Success",
        )
        st.rerun()


def filter_pages(pages_by_section: dict[str, list], role: str | None = None) -> dict[str, list]:
    """Given {section_title: [(page_key, StreamlitPage), ...]}, return only pages the role can see,
    dropping any section that ends up empty."""
    role = role or current_role()
    filtered: dict[str, list] = {}
    for section, entries in pages_by_section.items():
        visible = [page for key, page in entries if can_access(key, role)]
        if visible:
            filtered[section] = visible
    return filtered
