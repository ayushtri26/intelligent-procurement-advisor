"""Global tender workspace — the ONE tender selector for the whole app.

Rendered once, at the top of the sidebar (visually pushed above the nav
menu by the flex-order CSS rule in src/ui_components.py), so the selected
tender is visible and changeable regardless of which page the user is on.
No individual page maintains its own tender selector — every page reads
st.session_state.selected_tender_id / .selected_tender / .recommendation,
which app.py recomputes from src.tender_repository / src.recommendation_engine
right after this function runs.
"""
from __future__ import annotations

import streamlit as st

from src import audit, rbac, tender_form, tender_repository, ui_components

_STATUS_TONE = {
    "Draft": "neutral",
    "Open": "info",
    "Under Evaluation": "warning",
    "Awaiting Approval": "warning",
    "Awarded": "success",
    "Closed": "neutral",
}


def render_tender_workspace() -> None:
    """Flat (borderless) section, no "Tender Workspace" heading — starts
    straight at the field users touch most often. Switching tenders is far
    more common than creating one, so the dropdown/status lead and Create
    New Tender follows as a lower-emphasis secondary action."""
    options = tender_repository.tender_options()
    ids = list(options.keys())
    if not ids:
        st.markdown('<div class="sb-field-label">Current Tender</div>', unsafe_allow_html=True)
        st.caption("No tenders yet.")
    else:
        prev_id = st.session_state.get("selected_tender_id")
        if prev_id not in options:
            prev_id = ids[0]

        st.markdown('<div class="sb-field-label">Current Tender</div>', unsafe_allow_html=True)
        selected_id = st.selectbox(
            "Current Tender", ids, index=ids.index(prev_id),
            format_func=lambda tid: options[tid], key="tw_tender_select",
            label_visibility="collapsed",
        )

        tender = tender_repository.get_tender(selected_id)
        if tender:
            status = tender.get("status", "Draft")
            ui_components.sidebar_status_pill(status, tone=_STATUS_TONE.get(status, "neutral"))

        if selected_id != prev_id:
            st.session_state.selected_tender_id = selected_id
            audit.log_action(
                "Tender Selected", "Procurement", options[selected_id],
                previous=options.get(prev_id, prev_id), status="Success",
            )
            st.rerun()

    if rbac.can_manage_tenders():
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        if st.button("Create New Tender", icon=":material/add:", use_container_width=True, key="tw_create_btn", type="secondary"):
            tender_form.render_tender_dialog()
