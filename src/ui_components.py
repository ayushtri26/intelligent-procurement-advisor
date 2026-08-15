"""Reusable Streamlit rendering components shared across every page.

Nothing here computes a business fact — every function takes already-computed
values (scores, records, log rows) and renders them consistently. This is the
single source for the light-enterprise-shell visual language: cards, badges,
sparklines, donut charts, activity rows, and the small inline line-icon set
used inside custom-styled HTML (nav-page icons still use Streamlit's native
Material Symbols via `icon=":material/...:"`, which is Streamlit's own
consistent line-icon system — the SVG set below covers the handful of spots
where an icon needs to sit inside a custom-styled div instead).
"""
from __future__ import annotations

import base64

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Color system (mirrors .streamlit/config.toml — duplicated here because
# Plotly figures and raw HTML/CSS can't read the Streamlit theme at runtime).
# ---------------------------------------------------------------------------
TEXT_PRIMARY = "#0F172A"
TEXT_SECONDARY = "#64748B"
TEXT_MUTED = "#94A3B8"
BORDER = "#E2E8F0"
SURFACE = "#FFFFFF"
SURFACE_SUBTLE = "#F8FAFC"

BLUE = "#3B82F6"
GREEN = "#22C55E"
AMBER = "#F59E0B"
RED = "#EF4444"
PURPLE = "#7C6DE3"
SLATE = "#94A3B8"

_TONE_TO_BADGE_COLOR = {
    "success": "green", "positive": "green",
    "warning": "orange",
    "danger": "red", "critical": "red", "error": "red",
    "info": "blue", "primary": "blue",
    "neutral": "gray",
}
_HEX_BY_TONE = {"success": "#16A34A", "warning": "#F59E0B", "danger": "#EF4444"}
_LINE_BY_TONE = {"success": GREEN, "warning": AMBER, "danger": RED, "info": BLUE, "neutral": SLATE}

# ---------------------------------------------------------------------------
# Small inline line-icon set (Lucide-style: 24x24 viewBox, thin stroke).
# ---------------------------------------------------------------------------
_ICONS = {
    "trending-up": '<polyline points="3 17 9 11 13 15 21 7"></polyline><polyline points="14 7 21 7 21 14"></polyline>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"></path><circle cx="10" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M17 3.13a4 4 0 0 1 0 7.75"></path>',
    "shield-alert": '<path d="M12 2 4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6z"></path><line x1="12" y1="8" x2="12" y2="13"></line><line x1="12" y1="16" x2="12" y2="16.2"></line>',
    "clock": '<circle cx="12" cy="12" r="9"></circle><polyline points="12 7 12 12 16 14"></polyline>',
    "award": '<circle cx="12" cy="8" r="6"></circle><path d="M8.5 13.5 7 22l5-3 5 3-1.5-8.5"></path>',
    "pie-chart": '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path>',
    "activity": '<polyline points="2 12 6 12 9 4 13 20 16 12 22 12"></polyline>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"></path>',
    "search": '<circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
    "help-circle": '<circle cx="12" cy="12" r="9"></circle><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5"></path><line x1="12" y1="17" x2="12" y2="17.2"></line>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"></polyline>',
    "check": '<polyline points="20 6 9 17 4 12"></polyline>',
    "check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>',
    "upload-cloud": '<path d="M16 16 12 12 8 16"></path><line x1="12" y1="12" x2="12" y2="21"></line><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"></path>',
    "file-check": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M9 15l2 2 4-4"></path>',
    "arrow-right": '<line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline>',
    "alert-triangle": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12" y2="17.02"></line>',
    "lightbulb": '<path d="M9 18h6"></path><path d="M10 22h4"></path><path d="M12 2a6 6 0 0 0-4 10.5c.6.6 1 1.5 1 2.5h6c0-1 .4-1.9 1-2.5A6 6 0 0 0 12 2z"></path>',
    "circle-dot": '<circle cx="12" cy="12" r="9"></circle><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"></circle>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline>',
}

# Official multi-color Google "G" mark — the one icon in this file that isn't
# a single-stroke line icon, since Google's own brand guidelines require the
# real four-color mark (not a monochrome substitute) on "Continue with
# Google" buttons.
_GOOGLE_G_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18">'
    '<path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"/>'
    '<path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>'
    '<path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"/>'
    '<path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>'
    "</svg>"
)


def google_icon_data_uri() -> str:
    """Base64 data URI for the Google "G" mark, for use as a CSS background-image
    (Streamlit's native st.button icon= param only accepts emoji/Material icons,
    not custom SVG, so the real button stays a functional st.button and this
    is injected via CSS rather than replacing it with a fake clickable div)."""
    encoded = base64.b64encode(_GOOGLE_G_SVG.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def icon_svg(name: str, size: int = 16, color: str = "currentColor", stroke_width: float = 1.75) -> str:
    inner = _ICONS.get(name, _ICONS["circle-dot"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round" style="vertical-align:middle;display:inline-block;flex-shrink:0">{inner}</svg>'
    )


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------------------
# Global CSS — light enterprise shell, card shadows, chrome trimming.
# Targets Streamlit's documented stable data-testid hooks rather than
# generated/hashed class names wherever one exists.
# ---------------------------------------------------------------------------
GLOBAL_CSS = f"""
<style>
[data-testid="stHeader"] {{ height: 2.25rem; background: transparent; }}
.block-container {{ padding-top: 1.1rem; padding-bottom: 2.5rem; max-width: 1600px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; color: {TEXT_PRIMARY}; }}

/* Sidebar content added via `with st.sidebar:` always renders below the
   native nav menu (stSidebarNav) in the DOM, regardless of code order —
   Streamlit gives st.navigation() a fixed slot. The Tender Workspace block
   needs to sit ABOVE the nav (below the logo), so we flex-reorder the three
   direct children of the sidebar using their stable, documented testids
   rather than any generated/hashed class name. stSidebarHeader (logo) keeps
   its default order (first); all custom `st.sidebar` content is pushed
   above stSidebarNav as one group — Tender Workspace renders first within
   that group purely by call order in app.py.  */
[data-testid="stSidebarContent"] {{ display: flex; flex-direction: column; }}
[data-testid="stSidebarUserContent"] {{ order: 1; }}
[data-testid="stSidebarNav"] {{ order: 2; }}

/* Card shadow/border applied to every bordered st.container() */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{ }}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{ border-radius: 10px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{
    box-shadow: 0 1px 2px rgba(15,23,42,0.04);
    border-radius: 10px;
}}

.kpi2-card {{ display:flex; flex-direction:column; height:100%; }}
.kpi2-head {{ display:flex; align-items:flex-start; justify-content:space-between; }}
.kpi2-label {{ font-size: 12px; font-weight: 500; color: {TEXT_SECONDARY}; }}
.kpi2-iconwrap {{ width: 30px; height: 30px; border-radius: 8px; display:flex; align-items:center; justify-content:center; flex-shrink:0; }}
.kpi2-value {{ font-size: 26px; font-weight: 600; color: {TEXT_PRIMARY}; line-height:1.2; margin-top: 6px; }}
.kpi2-sub {{ font-size: 12px; color: {TEXT_MUTED}; margin-top: 2px; }}

.kpi-label {{ font-size: 12px; font-weight: 500; color: {TEXT_SECONDARY}; margin-bottom: 0.2rem; letter-spacing: 0.01em; }}
.kpi-value {{ font-size: 22px; font-weight: 600; line-height: 1.25; color: {TEXT_PRIMARY}; }}

.pipeline-step {{ text-align:center; padding: 0.5rem 0.15rem; border-radius: 8px; background: {SURFACE_SUBTLE}; font-weight:500; font-size:0.72rem; border: 1px solid {BORDER}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: {TEXT_SECONDARY}; }}
.pipeline-step.active {{ background: {_hex_to_rgba('#2563EB', 0.08)}; border: 1px solid #2563EB; color: #1D4ED8; font-weight: 600; }}
.pipeline-step.pending {{ color: {TEXT_MUTED}; }}
.pipeline-arrow {{ text-align:center; font-size:1.1rem; color: {TEXT_MUTED}; padding-top:0.45rem; }}

.notif-card {{ border-radius: 8px; padding: 0.55rem 0.85rem; margin-bottom: 0.35rem; border: 1px solid {BORDER}; background: {SURFACE}; }}
.notif-card.unread {{ background: {_hex_to_rgba('#2563EB', 0.05)}; border-color: {_hex_to_rgba('#2563EB', 0.3)}; }}
.notif-card .notif-title {{ font-weight: 600; font-size: 0.86rem; color: {TEXT_PRIMARY}; }}
.notif-card .notif-meta {{ font-size: 0.72rem; color: {TEXT_MUTED}; }}

.timeline-item {{ display:flex; gap: 0.7rem; padding: 0.3rem 0; }}
.timeline-dot {{ width: 8px; height: 8px; border-radius: 50%; background: #2563EB; margin-top: 0.4rem; flex-shrink:0; }}
.timeline-body .timeline-title {{ font-weight: 500; font-size: 0.86rem; color: {TEXT_PRIMARY}; }}
.timeline-body .timeline-meta {{ font-size: 0.72rem; color: {TEXT_MUTED}; }}

.chart-legend {{ display:flex; flex-direction:column; gap: 6px; margin-top: 8px; }}
.legend-row {{ display:flex; align-items:center; gap: 8px; font-size: 12px; color: {TEXT_SECONDARY}; }}
.legend-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink:0; }}
.legend-label {{ flex-grow:1; }}
.legend-value {{ font-weight: 600; color: {TEXT_PRIMARY}; }}

.act-row {{ display:flex; align-items:center; gap: 10px; padding: 8px 0; border-bottom: 1px solid {BORDER}; font-size: 12.5px; }}
.act-row:last-child {{ border-bottom: none; }}
.act-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink:0; }}
.act-main {{ flex-grow: 1; min-width:0; }}
.act-title {{ font-weight: 500; color: {TEXT_PRIMARY}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.act-sub {{ color: {TEXT_MUTED}; font-size: 11.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.act-user {{ color: {TEXT_SECONDARY}; font-size: 11.5px; width: 110px; flex-shrink:0; text-align:left; }}
.act-time {{ color: {TEXT_MUTED}; font-size: 11.5px; width: 78px; flex-shrink:0; text-align:right; }}

.alert-row {{ display:flex; align-items:flex-start; gap: 10px; padding: 9px 0; border-bottom: 1px solid {BORDER}; }}
.alert-row:last-child {{ border-bottom: none; }}
.alert-iconwrap {{ width: 28px; height: 28px; border-radius: 8px; display:flex; align-items:center; justify-content:center; flex-shrink:0; margin-top:1px; }}
.alert-main {{ flex-grow: 1; min-width: 0; }}
.alert-title {{ font-weight: 600; font-size: 12.5px; color: {TEXT_PRIMARY}; }}
.alert-sub {{ font-size: 11.5px; color: {TEXT_SECONDARY}; margin-top: 1px; }}
.alert-time {{ font-size: 11px; color: {TEXT_MUTED}; margin-top: 2px; }}

.reason-row {{ display:flex; align-items:flex-start; gap: 8px; font-size: 12.5px; color: {TEXT_SECONDARY}; padding: 3px 0; }}

.welcome-title {{ font-size: 24px; font-weight: 600; color: {TEXT_PRIMARY}; line-height:1.25; }}
.welcome-sub {{ font-size: 13px; color: {TEXT_SECONDARY}; margin-top: 2px; }}

.section-link {{ font-size: 12px; color: #2563EB; font-weight: 500; text-decoration:none; }}

/* ---------------------------------------------------------------------
   Sidebar — text branding, compact Tender Workspace card, compact nav,
   and a bottom-pinned profile footer. Colors are alpha-blended against
   the existing dark-navy [theme.sidebar] background (.streamlit/config.toml)
   rather than hardcoded, so this stays correct if that palette ever shifts.
   --------------------------------------------------------------------- */
[data-testid="stSidebar"] {{ position: relative; width: 268px !important; }}
/* One natural scroll region for the WHOLE sidebar body — custom Data/
   Scoring content AND the native nav together. Previously only
   stSidebarNav scrolled internally while this container clipped
   everything above it with overflow:hidden, which is exactly why
   Scoring Configuration was unreachable once the Data section grew past
   viewport height. padding-bottom reserves clearance so the last item
   never sits behind the absolutely-positioned pinned profile footer. */
[data-testid="stSidebarContent"] {{ height: 100vh; overflow-y: auto; overflow-x: hidden; padding-bottom: 76px; }}
[data-testid="stSidebarUserContent"] {{ flex: 0 0 auto; padding-bottom: 0; }}
[data-testid="stSidebarNav"] {{ flex: 0 0 auto; }}

/* Native collapse button — moved out of its own reserved header row and
   onto the same line as the brand title, right-aligned. stSidebarHeader
   sits outside stSidebarContent's flex flow, so pulling it out via
   absolute positioning lets stSidebarContent's own content start right
   at the top with no leftover blank header space. */
[data-testid="stSidebarHeader"] {{ position: absolute; top: 10px; right: 8px; left: auto; width: auto; height: auto; z-index: 10; background: transparent; }}

/* Shared left edge for every custom sidebar block AND the native nav —
   this is the single source of truth for the sidebar's alignment grid.
   Note: stSidebarUserContent renders ALL custom `st.sidebar` content as
   ONE combined wrapper div (not one per widget), so this padding applies
   uniformly to the whole block — per-row overrides must live on the
   inner element itself, never on a `> div` ancestor selector. */
:root {{ --sb-gutter: 20px; }}
[data-testid="stSidebarUserContent"] > div {{ padding-left: var(--sb-gutter); padding-right: var(--sb-gutter); }}
[data-testid="stSidebarNavLink"] {{ margin-left: 8px; margin-right: 8px; padding-left: calc(var(--sb-gutter) - 8px) !important; }}
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] {{ padding-left: var(--sb-gutter); padding-right: 8px; }}

.sb-brand {{ margin: 6px 0 10px 0; }}
.sb-brand-title {{ font-size: 18px; font-weight: 600; color: #F8FAFC; line-height: 1.28; letter-spacing: -0.015em; }}

.sb-section-label {{ font-size: 10.5px; font-weight: 500; letter-spacing: 0.05em; text-transform: uppercase; color: rgba(203,213,225,0.5); margin-bottom: 8px; }}
.sb-field-label {{ font-size: 11px; color: rgba(203,213,225,0.55); margin: 4px 0 7px 0; }}

.sb-status-dot {{ width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }}

/* Compact "Vendor Data" / "Scoring Configuration" subsections inside Data */
.sb-subhead {{ font-size: 12px; font-weight: 600; color: rgba(241,245,249,0.92); letter-spacing: 0.01em; margin: 2px 0 6px 0; }}
.sb-data-status {{ display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: rgba(203,213,225,0.75); margin: 0 0 6px 0; }}
.sb-data-status svg {{ flex-shrink: 0; }}

/* Vendor Data buttons sit closer together than the general sidebar-button
   rhythm — this is the two-button "Upload CSV" / "Sample Dataset" pair. */
.st-key-upload_popover, .st-key-use_sample_btn {{ margin-bottom: -6px; }}

/* Compact scoring sliders — label + live percentage share one row (the
   native per-thumb value badge, stSliderThumbValue, tracks the thumb's X
   position and can't be pinned to the row's right edge, so it's hidden
   here and the row above is a custom, session_state-driven readout
   instead); label_visibility="collapsed" removes the native label so
   only this custom row + the bare track remain, tightly stacked. */
.sb-slider-row {{ display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 0 0 2px 0; }}
.sb-slider-label {{ font-size: 12px; color: rgba(226,232,240,0.85); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }}
.sb-slider-value {{ font-size: 12px; font-weight: 600; color: #93C5FD; font-variant-numeric: tabular-nums; flex-shrink: 0; }}
[data-testid="stSidebar"] [data-testid="stSlider"] {{ margin-bottom: -14px; }}
[data-testid="stSidebar"] [data-testid="stSliderThumbValue"],
[data-testid="stSidebar"] [data-testid="stTickBarMin"],
[data-testid="stSidebar"] [data-testid="stTickBarMax"] {{ display: none !important; }}

.sb-weight-total {{ display: flex; align-items: center; justify-content: space-between; padding: 7px 10px; border-radius: 8px; font-size: 12px; font-weight: 500; margin: 10px 0 2px 0; }}
.sb-weight-total.ok {{ background: rgba(34,197,94,0.12); color: #86EFAC; }}
.sb-weight-total.warn {{ background: rgba(245,158,11,0.12); color: #FCD34D; }}
.sb-weight-total-left {{ display: flex; align-items: center; gap: 6px; }}
.sb-weight-total-value {{ font-weight: 700; }}
.sb-weight-total-note {{ font-size: 10.5px; color: rgba(252,211,77,0.85); margin: 4px 2px 6px 2px; line-height: 1.4; }}

.st-key-reset_weights_btn {{ margin-top: -8px; }}
.st-key-reset_weights_btn button {{
    background: transparent !important; border: none !important; color: rgba(203,213,225,0.55) !important;
    font-size: 11.5px !important; white-space: nowrap !important; text-decoration: underline;
    text-underline-offset: 2px; min-height: 26px !important; height: 26px !important; padding: 0 !important;
}}
.st-key-reset_weights_btn button:hover {{ color: #F1F5F9 !important; background: transparent !important; }}
.st-key-apply_weights_btn button {{ min-height: 34px !important; font-size: 12.5px !important; white-space: nowrap !important; }}
.st-key-upload_popover button {{ font-size: 12.5px !important; min-height: 34px !important; }}
.st-key-use_sample_btn button {{ font-size: 12.5px !important; min-height: 34px !important; }}

.sb-api-status {{ display: flex; align-items: center; justify-content: space-between; font-size: 11.5px; color: rgba(203,213,225,0.55); padding: 4px 2px; margin-top: 2px; }}
.sb-api-status-right {{ display: flex; align-items: center; gap: 6px; }}

/* Data & Scoring — a plain utility row, the same height/hover treatment
   as a nav item, no border or card of its own. */
[data-testid="stSidebar"] [data-testid="stExpander"],
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ border: none !important; background: transparent !important; box-shadow: none !important; }}
[data-testid="stSidebar"] [data-testid="stExpander"] > div {{ background: transparent !important; }}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    padding: 8px 4px; min-height: 36px; border-radius: 8px; display: flex; align-items: center; background: transparent !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{ background-color: rgba(255,255,255,0.06) !important; }}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {{ font-size: 12.5px !important; color: rgba(203,213,225,0.75) !important; }}
[data-testid="stSidebar"] [data-testid="stExpanderDetails"] {{ padding-top: 4px; background: transparent !important; }}

[data-testid="stSidebar"] [data-testid="stBaseButton-primary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {{ min-height: 38px; border-radius: 8px; font-weight: 500; }}
[data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div {{ min-height: 40px; border-radius: 8px; }}
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] span {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

/* Create New Tender — a subtle secondary action, not a dominant CTA; it
   now follows the dropdown/status instead of leading, since switching
   tenders happens far more often than creating one. */
.st-key-tw_create_btn button {{
    background: transparent !important;
    border: 1px solid rgba(96,165,250,0.35) !important;
    color: #93C5FD !important;
    font-size: 13px !important;
    white-space: nowrap !important;
}}
.st-key-tw_create_btn button:hover {{
    background: rgba(96,165,250,0.08) !important;
    border-color: rgba(96,165,250,0.55) !important;
    color: #BFDBFE !important;
}}

[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] {{ margin-top: 20px; }}
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"]:first-child {{ margin-top: 16px; }}
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] p {{ font-size: 10.5px !important; font-weight: 500 !important; letter-spacing: 0.05em; text-transform: uppercase; color: rgba(203,213,225,0.5) !important; }}

[data-testid="stSidebarNavLink"] {{ border-radius: 8px; min-height: 36px; margin-top: 1px; margin-bottom: 1px; transition: background-color 0.12s ease; }}
[data-testid="stSidebarNavLink"]:hover {{ background-color: rgba(255,255,255,0.055) !important; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background-color: rgba(37,99,235,0.10) !important; box-shadow: inset 2px 0 0 0 #3B82F6; }}
[data-testid="stSidebarNavLink"][aria-current="page"] p {{ color: #F8FAFC !important; font-weight: 600 !important; }}
[data-testid="stSidebarNavLink"][aria-current="page"] [data-testid="stIconMaterial"] {{ color: #F8FAFC !important; }}

[data-testid="stSidebarCollapseButton"] button {{ border: none !important; background: transparent !important; color: rgba(203,213,225,0.55) !important; }}
[data-testid="stSidebarCollapseButton"] button:hover {{ background-color: rgba(255,255,255,0.08) !important; color: #F1F5F9 !important; }}

/* position:fixed (not absolute) — stSidebarContent is now the scrolling
   element (see the scroll fix above), and this footer lives INSIDE it in
   the DOM (stSidebarUserContent is one flat wrapper for all custom sidebar
   content). An absolutely-positioned descendant still scrolls along with
   its scrolling ancestor even though its containing block is further up
   the tree, which is exactly why the profile row was drifting upward on
   scroll. Fixed positioning anchors it to the viewport instead, so it
   stays visually pinned regardless of the content's scroll offset; the
   explicit width (matching the sidebar's own width) replaces `right: 0`,
   since that would otherwise span the full browser viewport rather than
   just the sidebar's 268px column. */
.st-key-sidebar_profile_footer {{ position: fixed; left: 0; bottom: 0; width: 268px; background: #071A33; border-top: 1px solid rgba(255,255,255,0.08); padding: 10px var(--sb-gutter) 12px var(--sb-gutter); z-index: 20; }}
.sb-profile-row {{ display: flex; align-items: center; gap: 10px; }}
.sb-profile-avatar {{ width: 32px; height: 32px; border-radius: 50%; background: rgba(37,99,235,0.25); color: #93C5FD; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; flex-shrink: 0; }}
.sb-profile-name {{ font-size: 12.5px; font-weight: 600; color: #F1F5F9; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.sb-profile-role {{ font-size: 11px; color: rgba(203,213,225,0.6); line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

/* The sidebar profile popover portals outside [data-testid="stSidebar"], so
   its plain text (unlike buttons/badges) falls back to the light-theme's
   dark text color and becomes unreadable against the dark popover surface.
   st.container(key="sidebar_profile_popover") gives it a stable, globally
   scoped hook to force readable colors regardless of where it portals to. */
.st-key-sidebar_profile_popover p, .st-key-sidebar_profile_popover strong {{ color: #E2E8F0 !important; }}
.st-key-sidebar_profile_popover [data-testid="stCaptionContainer"] p {{ color: rgba(226,232,240,0.62) !important; }}
</style>
"""


def inject_global_css() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Badges & buttons
# ---------------------------------------------------------------------------

def status_badge(label: str, tone: str = "neutral", icon: str | None = None) -> None:
    """Render a compact native badge. `tone`: success/warning/danger/info/neutral."""
    st.badge(label, color=_TONE_TO_BADGE_COLOR.get(tone, "gray"), icon=icon)


def primary_button(label: str, icon: str | None = None, key: str | None = None, use_container_width: bool = False) -> bool:
    return st.button(label, icon=icon, type="primary", key=key, use_container_width=use_container_width)


def secondary_button(label: str, icon: str | None = None, key: str | None = None, use_container_width: bool = False) -> bool:
    return st.button(label, icon=icon, type="secondary", key=key, use_container_width=use_container_width)


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------

def kpi_card(label: str, value: str, sub: str | None = None) -> None:
    """Render one KPI card's contents. Call inside a bordered st.container() —
    this function renders no box of its own, so nothing nests inside another box."""
    st.markdown(f'<div class="kpi-label">{label}</div><div class="kpi-value">{value}</div>', unsafe_allow_html=True)
    if sub:
        st.caption(sub)


def kpi_card_v2(label: str, value: str, sub: str, icon: str, spark_values: list[float] | None = None,
                 tone: str = "info", key: str | None = None) -> None:
    """Compact KPI card: label + icon badge on top, large metric, supporting
    text, and a small sparkline along the bottom. Call inside a bordered
    st.container() — renders no box of its own."""
    color = _LINE_BY_TONE.get(tone, BLUE)
    st.markdown(
        f'<div class="kpi2-card">'
        f'<div class="kpi2-head"><span class="kpi2-label">{label}</span>'
        f'<span class="kpi2-iconwrap" style="background:{_hex_to_rgba(color, 0.12)}">{icon_svg(icon, size=15, color=color)}</span></div>'
        f'<div class="kpi2-value">{value}</div>'
        f'<div class="kpi2-sub">{sub}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if spark_values:
        render_sparkline(spark_values, color=color, key=key)


# ---------------------------------------------------------------------------
# Charts — sparklines & donuts
# ---------------------------------------------------------------------------

PLOTLY_CONFIG = {"displayModeBar": False}


def style_chart(fig: go.Figure, height: int | None = None) -> go.Figure:
    """Apply the light-shell chart look (white background, Inter font, tight
    margins, no mode bar) to a Plotly figure built elsewhere in the app."""
    layout_kwargs = dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color=TEXT_SECONDARY, size=12),
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(font=dict(size=11)),
    )
    if height is not None:
        layout_kwargs["height"] = height
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER)
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER)
    return fig


def _sparkline_figure(values: list[float], color: str) -> go.Figure:
    fig = go.Figure(
        go.Scatter(
            y=values, mode="lines", line=dict(color=color, width=1.75, shape="spline", smoothing=0.35),
            fill="tozeroy", fillcolor=_hex_to_rgba(color, 0.10), hoverinfo="skip",
        )
    )
    fig.update_layout(
        height=34, margin=dict(l=0, r=0, t=2, b=0),
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False, fixedrange=True), yaxis=dict(visible=False, fixedrange=True),
    )
    return fig


def render_sparkline(values: list[float], color: str = BLUE, key: str | None = None) -> None:
    st.plotly_chart(
        _sparkline_figure(values, color), use_container_width=True,
        config={"displayModeBar": False, "staticPlot": True}, key=key,
    )


def donut_chart(labels: list[str], values: list[float], colors: list[str], center_value: str, center_label: str,
                 height: int = 200, key: str | None = None) -> None:
    fig = go.Figure(
        go.Pie(
            labels=labels, values=values, hole=0.7, sort=False, direction="clockwise",
            marker=dict(colors=colors, line=dict(color=SURFACE, width=2)),
            textinfo="none", hoverinfo="label+percent",
        )
    )
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8), showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        annotations=[dict(
            text=f"<b>{center_value}</b><br><span style='font-size:11px;color:{TEXT_MUTED}'>{center_label}</span>",
            showarrow=False, font=dict(size=20, color=TEXT_PRIMARY, family="Inter, sans-serif"),
        )],
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=key)


def chart_legend(items: list[dict]) -> None:
    """items: [{'label': str, 'value': str|int, 'color': hex}]"""
    html = ['<div class="chart-legend">']
    for it in items:
        html.append(
            f'<div class="legend-row"><span class="legend-dot" style="background:{it["color"]}"></span>'
            f'<span class="legend-label">{it["label"]}</span><span class="legend-value">{it["value"]}</span></div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Activity table & alert list
# ---------------------------------------------------------------------------

def activity_table(rows: list[dict]) -> None:
    """rows: [{'title': str, 'sub': str, 'user': str, 'time': str, 'tone': str}]"""
    if not rows:
        st.caption("No recent activity.")
        return
    html = ["<div>"]
    for r in rows:
        color = _LINE_BY_TONE.get(r.get("tone", "info"), BLUE)
        html.append(
            '<div class="act-row">'
            f'<span class="act-dot" style="background:{color}"></span>'
            '<div class="act-main">'
            f'<div class="act-title">{r["title"]}</div>'
            f'<div class="act-sub">{r["sub"]}</div>'
            '</div>'
            f'<div class="act-user">{r["user"]}</div>'
            f'<div class="act-time">{r["time"]}</div>'
            '</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def alert_list(items: list[dict]) -> None:
    """items: [{'icon': str, 'title': str, 'sub': str, 'time': str, 'tone': str}]"""
    if not items:
        st.caption("No alerts right now.")
        return
    html = ["<div>"]
    for it in items:
        color = _LINE_BY_TONE.get(it.get("tone", "info"), BLUE)
        html.append(
            '<div class="alert-row">'
            f'<span class="alert-iconwrap" style="background:{_hex_to_rgba(color, 0.12)}">{icon_svg(it["icon"], size=14, color=color)}</span>'
            '<div class="alert-main">'
            f'<div class="alert-title">{it["title"]}</div>'
            f'<div class="alert-sub">{it["sub"]}</div>'
            f'<div class="alert-time">{it["time"]}</div>'
            '</div>'
            '</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def reason_list(reasons: list[str], icon: str = "check-circle", color: str = GREEN) -> None:
    html = []
    for r in reasons:
        html.append(f'<div class="reason-row">{icon_svg(icon, size=14, color=color)}<span>{r}</span></div>')
    st.markdown("".join(html), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Misc (tables, timeline, stepper, score panel, empty state)
# ---------------------------------------------------------------------------

def data_table(df: pd.DataFrame, **kwargs) -> None:
    """Thin wrapper around st.dataframe with the app's standard defaults."""
    kwargs.setdefault("use_container_width", True)
    kwargs.setdefault("hide_index", True)
    st.dataframe(df, **kwargs)


def notification_card(title: str, message: str, meta: str, unread: bool = True) -> None:
    css_class = "notif-card unread" if unread else "notif-card"
    st.markdown(
        f'<div class="{css_class}"><div class="notif-title">{title}</div>'
        f'<div>{message}</div><div class="notif-meta">{meta}</div></div>',
        unsafe_allow_html=True,
    )


def timeline(events: list[dict]) -> None:
    """`events`: list of {title, meta} dicts, already in display order."""
    if not events:
        st.caption("No activity recorded yet.")
        return
    html = ['<div class="timeline">']
    for e in events:
        html.append(
            f'<div class="timeline-item"><div class="timeline-dot"></div>'
            f'<div class="timeline-body"><div class="timeline-title">{e["title"]}</div>'
            f'<div class="timeline-meta">{e["meta"]}</div></div></div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def stepper(stages: list[str], current_index: int) -> None:
    """Render a horizontal stage stepper. `current_index` is the highest stage reached (0-based)."""
    cols = st.columns(len(stages) * 2 - 1)
    for i, stage in enumerate(stages):
        idx = i * 2
        with cols[idx]:
            cls = "pipeline-step active" if i <= current_index else "pipeline-step pending"
            st.markdown(f'<div class="{cls}">{stage}</div>', unsafe_allow_html=True)
        if idx + 1 < len(cols):
            with cols[idx + 1]:
                st.markdown('<div class="pipeline-arrow">&rarr;</div>', unsafe_allow_html=True)


def score_panel(feature_labels: dict[str, str], contributions: list[dict]) -> None:
    """Render score-contribution bars. `contributions`: list of {label, score} dicts."""
    for c in contributions:
        bar_col, val_col = st.columns([5, 1])
        bar_col.progress(min(int(c["score"]), 100), text=c["label"])
        val_col.caption(f"{c['score']:.0f}")


def audit_row_badge(status: str) -> None:
    status_badge(status, tone="success" if status == "Success" else "danger")


def confidence_tone(pct: float) -> str:
    if pct >= 75:
        return "success"
    if pct >= 50:
        return "warning"
    return "danger"


def confidence_color(pct: float) -> str:
    """Hex value for contexts that can't use a badge (Plotly gauges/bars)."""
    return _HEX_BY_TONE[confidence_tone(pct)]


def confidence_label_tone(label: str) -> str:
    """Map a High/Medium/Low confidence label (src.analytics_tools.classify_confidence) to a badge tone."""
    return {"High": "success", "Medium": "warning", "Low": "danger"}.get(label, "neutral")


def empty_state(title: str, caption: str) -> None:
    with st.container(border=True):
        st.markdown(f"##### {title}")
        st.caption(caption)


# ---------------------------------------------------------------------------
# Sidebar chrome — text branding, section labels, and compact status rows.
# ---------------------------------------------------------------------------

def render_sidebar_branding() -> None:
    """Left-aligned text-only wordmark rendered as the first sidebar element,
    replacing the old st.logo() image lockup. No subtitle, no icon — the
    native collapse button (repositioned via CSS) shares this same row."""
    st.markdown('<div class="sb-brand"><div class="sb-brand-title">Intelligent Procurement Advisor</div></div>', unsafe_allow_html=True)


def sidebar_weight_total(total_pct: int, valid: bool) -> None:
    """Compact one-line 'Total Weight  100%' row for the Scoring Configuration
    panel. When not valid (off 100%), adds a small note — informational, not
    a hard block, since compute_overall_score() already auto-normalizes any
    positive weight combination to 100% (see src/vendor_scoring.py)."""
    tone_class = "ok" if valid else "warn"
    icon = "check-circle" if valid else "alert-triangle"
    st.markdown(
        f'<div class="sb-weight-total {tone_class}">'
        f'<span class="sb-weight-total-left">{icon_svg(icon, size=14, color="currentColor")}<span>Total Weight</span></span>'
        f'<span class="sb-weight-total-value">{total_pct}%</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if not valid:
        st.markdown(
            '<div class="sb-weight-total-note">Weights are automatically normalized to 100% when scores are computed.</div>',
            unsafe_allow_html=True,
        )


def sidebar_status_row(label: str, connected: bool, connected_label: str = "Connected", disconnected_label: str = "Fallback mode") -> None:
    """Compact single-line system status row (e.g. 'Claude API  ● Connected')."""
    color = GREEN if connected else SLATE
    text = connected_label if connected else disconnected_label
    st.markdown(
        f'<div class="sb-api-status"><span>{label}</span>'
        f'<span class="sb-api-status-right"><span class="sb-status-dot" style="background:{color}"></span>{text}</span></div>',
        unsafe_allow_html=True,
    )
