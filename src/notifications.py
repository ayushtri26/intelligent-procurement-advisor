"""Rule-based notification generation.

Every rule here reads already-computed state (ranked_df, workflow, chat
activity) — no new business logic. Notifications are deduplicated by a
stable id per underlying fact (e.g. one "High Risk Vendor" notification per
vendor id) so re-running the rules on every Streamlit rerun doesn't spam
duplicates; genuinely new facts (a score that actually changed) still
produce a new entry.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st


def _ensure() -> None:
    if "notifications" not in st.session_state:
        st.session_state.notifications = []
    if "_notif_seen_ids" not in st.session_state:
        st.session_state._notif_seen_ids = set()
    if "_notif_last_top_score" not in st.session_state:
        st.session_state._notif_last_top_score = None


def _add(category: str, title: str, message: str, meta: str, notif_id: str) -> None:
    _ensure()
    if notif_id in st.session_state._notif_seen_ids:
        return
    st.session_state._notif_seen_ids.add(notif_id)
    st.session_state.notifications.insert(
        0,
        {
            "id": notif_id,
            "category": category,
            "title": title,
            "message": message,
            "meta": meta,
            "read": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def sync_from_ranked_df(ranked_df: pd.DataFrame) -> None:
    """Call once per rerun after the pipeline is computed. Generates High Risk
    Vendor and Score Updated notifications idempotently."""
    if ranked_df is None or ranked_df.empty:
        return
    _ensure()

    anomalous = ranked_df[ranked_df.get("is_anomalous", False) == True]  # noqa: E712
    for _, row in anomalous.iterrows():
        _add(
            "High Risk Vendor",
            f"High Risk Vendor: {row['vendor_name']}",
            f"{row['vendor_name']} ({row['vendor_id']}) is flagged as a statistical anomaly.",
            f"Overall score {row['overall_score']:.1f}/100",
            notif_id=f"high-risk-{row['vendor_id']}",
        )

    top = ranked_df.sort_values("overall_score", ascending=False).iloc[0]
    prev = st.session_state._notif_last_top_score
    if prev is not None and abs(float(top["overall_score"]) - prev) > 0.05:
        _add(
            "Score Updated",
            "Score Updated",
            f"{top['vendor_name']}'s overall score changed from {prev:.1f} to {top['overall_score']:.1f}.",
            "The top recommendation may have changed.",
            notif_id=f"score-update-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        )
    st.session_state._notif_last_top_score = float(top["overall_score"])


def notify_tender_deadline(days_remaining: int = 5) -> None:
    _add(
        "Tender Deadline",
        "Tender Deadline Approaching",
        "The current tender's evaluation window closes soon.",
        f"Illustrative deadline: {days_remaining} day(s) remaining",
        notif_id="tender-deadline-static",
    )


def sync_contract_expiry(awarded_vendors: list[dict]) -> None:
    for c in awarded_vendors:
        _add(
            "Contract Expiry",
            f"Contract Expiry Reminder: {c['vendor_name']}",
            "Illustrative: contract assumed to run 12 months from the award date.",
            f"Awarded {c['awarded_at']}",
            notif_id=f"contract-expiry-{c['vendor_id']}",
        )


def notify_ai_recommendation_ready(vendor_name: str) -> None:
    _add(
        "AI Recommendation Ready",
        "AI Recommendation Ready",
        f"A new recommendation is available: {vendor_name}.",
        "View in AI Workspace → Recommendations",
        notif_id=f"ai-rec-{vendor_name}-{datetime.now().strftime('%Y%m%d%H%M')}",
    )


def mark_read(notif_id: str) -> None:
    _ensure()
    for n in st.session_state.notifications:
        if n["id"] == notif_id:
            n["read"] = True


def mark_all_read() -> None:
    _ensure()
    for n in st.session_state.notifications:
        n["read"] = True


def unread_count() -> int:
    _ensure()
    return sum(1 for n in st.session_state.notifications if not n["read"])


def get_notifications() -> list[dict]:
    _ensure()
    return st.session_state.notifications
