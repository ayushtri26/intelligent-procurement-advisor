"""Implicit single-tender approval workflow state machine.

The app models exactly one "current tender" — the currently loaded vendor
CSV — moving through a fixed sequence of stages. Stage advancement is
idempotent (calling advance_stage with a stage already reached is a no-op)
so it can safely be called on every rerun as pipeline steps complete.
"""
from __future__ import annotations

import streamlit as st

from src import audit

TENDER_STAGES = [
    "Draft",
    "Uploaded",
    "AI Analysis",
    "Manager Approval",
    "Director Approval",
    "Approved",
    "Awarded",
]

DEFAULT_TENDER_NAME = "Q3 Vendor Evaluation Tender"


def init_workflow() -> None:
    if "tender_stage_index" not in st.session_state:
        st.session_state.tender_stage_index = 0
    if "tender_name" not in st.session_state:
        st.session_state.tender_name = DEFAULT_TENDER_NAME
    if "awarded_vendors" not in st.session_state:
        st.session_state.awarded_vendors = []


def stage_index() -> int:
    init_workflow()
    return st.session_state.tender_stage_index


def stage_name() -> str:
    return TENDER_STAGES[stage_index()]


def advance_stage(target_stage: str, detail: str | None = None) -> None:
    """Move the tender forward to `target_stage` if it isn't already there or past it.

    The audit entry's Affected Object is always the tender name (not `detail`)
    so that views/tenders.py's activity timeline — which filters the audit
    log by tender-name substring — actually finds these events; `detail`
    (e.g. vendor count, recommended vendor name) is folded into New Value
    instead, where it's still visible in Audit Logs / Activity Timeline.
    """
    init_workflow()
    target_idx = TENDER_STAGES.index(target_stage)
    if target_idx > st.session_state.tender_stage_index:
        prev = TENDER_STAGES[st.session_state.tender_stage_index]
        st.session_state.tender_stage_index = target_idx
        new_value = f"{target_stage} ({detail})" if detail else target_stage
        audit.log_action(
            "Tender Stage Advanced",
            "Procurement",
            st.session_state.get("tender_name", DEFAULT_TENDER_NAME),
            previous=prev,
            new=new_value,
        )


def mark_data_uploaded(vendor_count: int) -> None:
    advance_stage("Uploaded", f"{vendor_count} vendors loaded")


def mark_ai_analysis_complete(top_vendor_name: str) -> None:
    advance_stage("AI Analysis", f"Top recommendation: {top_vendor_name}")


def mark_manager_approved(vendor_name: str) -> None:
    advance_stage("Manager Approval", vendor_name)


def mark_director_approved(vendor_name: str) -> None:
    advance_stage("Director Approval", vendor_name)
    advance_stage("Approved", vendor_name)


def mark_awarded(vendor_name: str, vendor_id: str) -> None:
    advance_stage("Awarded", vendor_name)
    init_workflow()
    from datetime import datetime

    st.session_state.awarded_vendors.append(
        {
            "vendor_name": vendor_name,
            "vendor_id": vendor_id,
            "awarded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    audit.log_action("Contract Awarded", "Procurement", f"{vendor_name} ({vendor_id})", status="Success")


def is_stage_reached(stage: str) -> bool:
    return stage_index() >= TENDER_STAGES.index(stage)
