"""Session-scoped audit logging.

There is no database in this app, so the audit trail lives in
st.session_state (matching the persistence model already used for
chat_history, approvals, etc.) and can be exported to CSV for a durable
record. Deliberately reads the current user/role directly from
st.session_state rather than importing src.rbac, to avoid a circular import
(rbac imports this module to log login events).
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

AUDIT_COLUMNS = [
    "Timestamp", "Username", "Role", "Action", "Module", "Affected Object",
    "Previous Value", "New Value", "IP Address", "Browser", "Status",
]

PLACEHOLDER_IP = "127.0.0.1 (local session)"
PLACEHOLDER_BROWSER = "Local Streamlit session"


def _ensure_log() -> None:
    if "audit_log" not in st.session_state:
        st.session_state.audit_log = []


def log_action(
    action: str,
    module: str,
    affected_object: str,
    previous=None,
    new=None,
    status: str = "Success",
) -> None:
    """Append one audit entry. Never raises — a logging failure must not break the app."""
    try:
        _ensure_log()
        st.session_state.audit_log.append(
            {
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Username": st.session_state.get("current_user_name", "Unknown"),
                "Role": st.session_state.get("current_role", "Unknown"),
                "Action": action,
                "Module": module,
                "Affected Object": affected_object,
                "Previous Value": "" if previous is None else str(previous),
                "New Value": "" if new is None else str(new),
                "IP Address": PLACEHOLDER_IP,
                "Browser": PLACEHOLDER_BROWSER,
                "Status": status,
            }
        )
    except Exception:
        pass


def get_audit_df() -> pd.DataFrame:
    """Most-recently-logged entries first. Timestamps only have second
    resolution, so entries logged within the same second would tie under a
    plain sort — reversing insertion order before a stable sort breaks that
    tie in favor of the most-recently-appended entry, without needing
    sub-second precision."""
    _ensure_log()
    if not st.session_state.audit_log:
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    df = pd.DataFrame(list(reversed(st.session_state.audit_log)))
    return df[AUDIT_COLUMNS].sort_values("Timestamp", ascending=False, kind="stable").reset_index(drop=True)


def export_csv(df: pd.DataFrame | None = None) -> bytes:
    df = df if df is not None else get_audit_df()
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def events_for_object(affected_object: str) -> list[dict]:
    """Audit entries mentioning a given object (vendor name/ID, tender, etc.), oldest first."""
    df = get_audit_df()
    if df.empty:
        return []
    matches = df[df["Affected Object"].astype(str).str.contains(str(affected_object), case=False, na=False)]
    return matches.sort_values("Timestamp").to_dict(orient="records")
