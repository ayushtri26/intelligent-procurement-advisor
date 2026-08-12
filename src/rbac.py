"""Role-based access control, backed by real Google/OIDC sign-in.

Identity comes from Streamlit's native ``st.login()``/``st.user`` (OIDC) —
see app.py's login gate. Role is never chosen by the user; it is derived
automatically from the authenticated name via `assign_role_from_name()`.
When no identity provider is configured in `.streamlit/secrets.toml`
(local development without Google OAuth set up yet), the app falls back to
a clearly-labeled demo identity so the rest of the app remains testable —
see app.py's `_auth_configured()`.
"""
from __future__ import annotations

import streamlit as st

from src import audit

ROLES = ["Administrator", "Procurement Manager", "Executive", "Auditor", "Vendor"]
DEFAULT_ROLE = "Administrator"

# Case-insensitive substring match against the authenticated user's name.
# First match wins; any name that matches none of these becomes Administrator.
ROLE_NAME_MAP: dict[str, str] = {
    "MAHA": "Procurement Manager",
    "AYUSH": "Procurement Manager",
    "ANIL": "Procurement Manager",
    "AAKAUSH": "Procurement Manager",
    "SUPRIYA": "Procurement Manager",
}
FALLBACK_ROLE = "Administrator"

ALL_PAGE_KEYS = [
    "dashboard", "vendors", "tenders", "contracts", "approvals",
    "ai_assistant", "document_intelligence", "recommendations", "anomalies",
    "vendor_analytics", "spend_analytics", "risk_analytics",
    "audit_logs", "activity_timeline", "user_activity",
    "users", "roles", "settings",
]

# Which pages each role can see in the sidebar navigation.
PAGE_PERMISSIONS: dict[str, set[str]] = {
    "Administrator": set(ALL_PAGE_KEYS),
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
MANAGER_APPROVAL_ROLES = {"Administrator", "Procurement Manager"}
DIRECTOR_APPROVAL_ROLES = {"Administrator", "Executive"}
# Roles allowed to edit scoring weights (others see the sliders disabled).
WEIGHT_EDIT_ROLES = {"Administrator", "Procurement Manager"}
# Roles allowed to create tenders and edit/duplicate Draft tenders.
TENDER_MANAGE_ROLES = {"Administrator", "Procurement Manager"}


def assign_role_from_name(name: str) -> str:
    """Deterministically derive a role from an authenticated display name.

    Case-insensitive substring match against ROLE_NAME_MAP; any name that
    doesn't contain one of the mapped strings anywhere becomes the fallback
    role. This is the single reusable place that owns this logic — nothing
    else in the UI should hardcode a name->role rule.
    """
    upper_name = (name or "").upper()
    for needle, role in ROLE_NAME_MAP.items():
        if needle in upper_name:
            return role
    return FALLBACK_ROLE


def set_user(name: str, email: str, is_real_login: bool) -> None:
    """Establish the session's authenticated identity exactly once (called
    from app.py's login gate right after Google sign-in succeeds, or right
    after the demo-mode fallback form is submitted). Role is derived
    automatically — never passed in, never user-selectable."""
    role = assign_role_from_name(name)
    st.session_state.user = {"name": name, "email": email, "role": role}
    st.session_state._real_login = is_real_login
    audit.log_action("User Login", "Administration", name, new=f"{name} ({role})", status="Success")


def init_identity() -> None:
    """Defensive fallback so any code path reading current_role()/current_user_name()
    before the login gate has run never crashes. Does not log — set_user() owns that."""
    if "user" not in st.session_state:
        st.session_state.user = {"name": "", "email": "", "role": DEFAULT_ROLE}


def current_role() -> str:
    return st.session_state.get("user", {}).get("role", DEFAULT_ROLE)


def current_user_name() -> str:
    return st.session_state.get("user", {}).get("name", "")


def current_user_email() -> str:
    return st.session_state.get("user", {}).get("email", "")


def current_user_initials() -> str:
    parts = [p for p in current_user_name().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def can_access(page_key: str, role: str | None = None) -> bool:
    role = role or current_role()
    return page_key in PAGE_PERMISSIONS.get(role, set())


def can_approve_manager_stage(role: str | None = None) -> bool:
    return (role or current_role()) in MANAGER_APPROVAL_ROLES


def can_approve_director_stage(role: str | None = None) -> bool:
    return (role or current_role()) in DIRECTOR_APPROVAL_ROLES


def can_edit_weights(role: str | None = None) -> bool:
    return (role or current_role()) in WEIGHT_EDIT_ROLES


def can_manage_tenders(role: str | None = None) -> bool:
    return (role or current_role()) in TENDER_MANAGE_ROLES


def render_identity_control() -> None:
    """Top-bar 'Signed in as' control — read-only identity (role is assigned
    automatically at login, not user-selectable) plus Logout."""
    init_identity()
    user = st.session_state.user

    label = f"{user['name']} · {user['role']}"
    with st.popover(label, icon=":material/account_circle:", use_container_width=False):
        st.caption("Signed in as")
        st.markdown(f"**{user['name']}**")
        if user.get("email"):
            st.caption(user["email"])
        st.badge(user["role"], color="blue")
        st.caption("Role is assigned automatically from your account and can't be changed here.")
        st.divider()
        if st.button("Log out", icon=":material/logout:", use_container_width=True):
            audit.log_action("User Logout", "Administration", user["name"], status="Success")
            if hasattr(st, "logout") and st.session_state.get("_real_login"):
                st.logout()
            else:
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
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
