"""Tender data store — the single source of truth for "which tenders exist".

No database in this app (same session-state persistence model used
everywhere else — audit log, notifications, approvals), so the repository
lives in st.session_state, seeded once from src.tenders_data.SEED_TENDERS.
User-created tenders (src/tender_form.py) are added here and are from that
point on indistinguishable from the seed tenders — every reader (the
sidebar dropdown, src/recommendation_engine.py, views/tenders.py) goes
through this module, never a hardcoded tender list.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from src.tenders_data import DEFAULT_TENDER_ID, SEED_TENDERS


def init_repository() -> None:
    if "tenders" not in st.session_state:
        st.session_state.tenders = {tid: dict(t) for tid, t in SEED_TENDERS.items()}


def get_all_tenders() -> list[dict]:
    """All tenders, most recently modified first."""
    init_repository()
    return sorted(st.session_state.tenders.values(), key=lambda t: t.get("last_modified_at", ""), reverse=True)


def get_tender(tender_id: str) -> dict | None:
    init_repository()
    return st.session_state.tenders.get(tender_id)


def get_tender_or_default(tender_id: str) -> dict:
    """Same as get_tender, but falls back to the default seed tender instead
    of None — for callers (e.g. the recommendation pipeline) that always
    need a valid tender to operate on."""
    return get_tender(tender_id) or get_tender(DEFAULT_TENDER_ID)


def tender_options() -> dict[str, str]:
    """{tender_id: display_label} for the sidebar dropdown, built fresh from
    whatever is currently in the repository — never a static list."""
    init_repository()
    return {t["tender_id"]: t["title"] for t in get_all_tenders()}


def generate_tender_id() -> str:
    """TND-<year>-NNNN, unique within the current repository. Never derived
    from the title — titles can repeat or change without touching identity."""
    init_repository()
    year = datetime.now().year
    prefix = f"TND-{year}-"
    existing_nums = [
        int(tid[len(prefix):]) for tid in st.session_state.tenders
        if tid.startswith(prefix) and tid[len(prefix):].isdigit()
    ]
    next_num = max(existing_nums, default=0) + 1
    candidate = f"{prefix}{next_num:04d}"
    # Defensive: guarantee uniqueness even if numbers were ever created out of order.
    while candidate in st.session_state.tenders:
        next_num += 1
        candidate = f"{prefix}{next_num:04d}"
    return candidate


def create_tender(tender: dict) -> str:
    """Insert a new tender and return its assigned id."""
    init_repository()
    tender_id = tender.get("tender_id") or generate_tender_id()
    tender["tender_id"] = tender_id
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tender.setdefault("created_at", now)
    tender["last_modified_at"] = now
    tender.setdefault("status", "Draft")
    tender.setdefault("source", "User Created")
    st.session_state.tenders[tender_id] = tender
    return tender_id


def update_tender(tender_id: str, updates: dict) -> None:
    init_repository()
    if tender_id not in st.session_state.tenders:
        return
    st.session_state.tenders[tender_id].update(updates)
    st.session_state.tenders[tender_id]["last_modified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def set_status(tender_id: str, status: str) -> None:
    update_tender(tender_id, {"status": status})


def duplicate_tender(tender_id: str, created_by: str) -> str | None:
    """Clone a tender as a new Draft with a fresh id — used by 'Duplicate Tender'."""
    source = get_tender(tender_id)
    if source is None:
        return None
    clone = dict(source)
    clone.pop("tender_id", None)
    clone["title"] = f"{source['title']} (Copy)"
    clone["status"] = "Draft"
    clone["source"] = "User Created"
    clone["created_by"] = created_by
    return create_tender(clone)
