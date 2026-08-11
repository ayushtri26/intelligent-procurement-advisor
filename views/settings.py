"""Settings — vendor weight reference, notification preferences, theme,
export defaults, and AI parameters.

Note on weights: the sidebar sliders (Scoring Configuration) are the single
source of truth for scoring weights — Streamlit does not allow two separate
widget instances to share one `key` within the same script run, and the
sidebar already renders on every page. The sliders below mirror the current
values read-only for visibility; edit them from the sidebar.
"""
import streamlit as st

from src import agent, audit
from src.analytics_tools import FEATURE_LABELS
from src.feature_engineering import FEATURE_COLUMNS

st.title("Settings")

st.header("Vendor Weight Configuration (reference)")
st.caption("Read-only here — adjust live from the **Scoring Configuration** panel in the sidebar.")
for feature in FEATURE_COLUMNS:
    st.slider(
        FEATURE_LABELS[feature], 0.0, 1.0,
        value=st.session_state.get(f"weight_{feature}", 0.0),
        key=f"settings_weight_display_{feature}", disabled=True,
    )

st.header("Notification Settings")
for category in list(st.session_state.notification_settings.keys()):
    new_val = st.checkbox(category, value=st.session_state.notification_settings[category], key=f"notif_setting_{category}")
    if new_val != st.session_state.notification_settings[category]:
        st.session_state.notification_settings[category] = new_val
        audit.log_action("Notification Setting Changed", "Administration", category, new=new_val)

st.header("Theme")
theme_choice = st.selectbox("Preferred accent", ["System", "Light", "Dark"], key="theme_preference_input")
st.caption("Full light/dark theme switching is available via the Streamlit menu (⋮ top right) → Settings → Theme.")

st.header("Export Settings")
st.selectbox("Default report format", ["PDF", "CSV"], key="default_export_format")

st.header("AI Parameters")
current_cap = st.session_state.ai_max_iterations_override or agent.MAX_ITERATIONS
new_cap = st.number_input(
    "Max tool-call iterations per AI Assistant question", min_value=1, max_value=20, value=current_cap,
    help="Caps how many tool calls the Claude agent can make while answering a single question, to prevent runaway loops.",
)
if new_cap != current_cap:
    st.session_state.ai_max_iterations_override = int(new_cap)
    audit.log_action("AI Parameter Changed", "Administration", "max_iterations", previous=current_cap, new=int(new_cap))
    st.rerun()
