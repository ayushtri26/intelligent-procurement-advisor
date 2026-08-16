"""Intelligent Procurement Advisor — enterprise shell / router.

Run with: streamlit run app.py

This file owns everything that must be shared across every page: page
config, global CSS, session-state init, the data-source + scoring sidebar
controls, the deterministic vendor pipeline (computed once per rerun and
stashed in st.session_state), the top bar (search / notifications /
identity), and role-filtered multi-page navigation via st.navigation. Every
individual page lives under views/ and reads its inputs from
st.session_state — none of them re-run the pipeline themselves.

No scoring, anomaly-detection, RAG, or agent logic lives in this file or was
changed anywhere in this refactor — see src/vendor_scoring.py,
src/anomaly_detection.py, src/rag.py, src/agent.py (all untouched).
"""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src import audit, notifications, rbac, recommendation_engine, search, tender_context, tender_repository, ui_components, workflow
from src.analytics_tools import FEATURE_LABELS, add_recommendation_categories, build_recommendation_bundle
from src.anomaly_detection import detect_anomalies
from src.data_processing import coerce_numeric_columns, load_csv, rows_with_missing_mask, validate_vendor_data
from src import dashboard as dashboard_metrics
from src.feature_engineering import FEATURE_COLUMNS, engineer_features
from src.llm_service import get_api_key
from src.vendor_scoring import DEFAULT_WEIGHTS, compute_overall_score, rank_vendors

load_dotenv()

SAMPLE_PATH = "data/sample_vendors.csv"

st.set_page_config(page_title="Intelligent Procurement Advisor", page_icon=":material/inventory_2:", layout="wide")
ui_components.inject_global_css()


# --------------------------------------------------------------------------
# Login gate — Google/OIDC sign-in via Streamlit's native st.login(). Nothing
# below this block renders until the user is authenticated. The "Explore
# Demo" option is a secondary, always-available identity path (not a
# configuration fallback) so the app stays testable without exposing any
# setup detail to end users — see .streamlit/secrets.toml.example for the
# real Google OAuth setup.
#
# There is no password-based auth anywhere in this app — real identity comes
# exclusively from Google OIDC (or the demo path above), and role is derived
# automatically from the signed-in name (src/rbac.py). The separate "Admin
# Portal" screen is therefore a distinct, distinctly-styled entry point
# rather than a second credential system: it triggers the exact same
# st.login() call, just presented as its own secure-looking surface per the
# design brief, with no fabricated password check and no demo path (an
# admin identity is reachable via demo on the main screen, since any name
# not in ROLE_NAME_MAP falls back to Administrator).
# --------------------------------------------------------------------------
def _auth_configured() -> bool:
    try:
        return bool(st.secrets.get("auth", {}).get("client_id"))
    except Exception:
        return False


def _auth_shell_css() -> None:
    google_icon = ui_components.google_icon_data_uri()
    st.markdown(
        f"""
        <style>
        [data-testid="stSidebar"] {{ display: none; }}
        [data-testid="stHeader"] {{ background: transparent; }}
        [data-testid="stMainBlockContainer"] {{ padding-top: 4vh; padding-bottom: 4vh; }}
        [data-testid="stAppViewContainer"] {{
            background:
                radial-gradient(ellipse 560px 420px at 50% 38%, rgba(37,99,235,0.04), rgba(37,99,235,0) 70%),
                #F5F7FA;
        }}

        .auth-badge {{
            width: 60px; height: 60px; border-radius: 15px;
            background: linear-gradient(155deg, #2458A6, #174A8B);
            display: flex; align-items: center; justify-content: center;
            margin: 0 auto 14px auto; box-shadow: 0 6px 16px rgba(23,74,139,0.28);
        }}
        .auth-badge.admin {{ background: linear-gradient(155deg, #1E293B, #0B1526); box-shadow: 0 6px 16px rgba(15,23,42,0.35); }}
        .auth-badge svg {{ width: 28px; height: 28px; }}

        .auth-brand {{ font-size: 13px; font-weight: 700; color: #2458A6; text-align: center;
            text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 6px; }}

        .auth-title {{ font-size: 21px; font-weight: 700; color: #0F2744; text-align: center; line-height: 1.3; }}
        .auth-subtitle {{ font-size: 13px; color: #5F6F82; text-align: center; margin-top: 5px; margin-bottom: 20px; line-height: 1.5; }}

        .auth-divider-row {{ display: flex; align-items: center; gap: 12px; margin: 16px 0; }}
        .auth-divider-line {{ flex: 1; height: 1px; background: #E5EAF0; }}
        .auth-divider-text {{ font-size: 11.5px; color: #94A3B8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }}

        .auth-secondary-heading {{ text-align: center; font-size: 13.5px; font-weight: 600; color: #183B66; margin-top: 2px; }}
        .auth-secondary-caption {{ text-align: center; font-size: 12px; color: #8896A8; margin-top: 3px; margin-bottom: 12px; line-height: 1.4; }}
        .auth-security-note {{ text-align: center; font-size: 11.5px; color: #8A98AA; margin-top: 16px; line-height: 1.5; }}

        .auth-admin-label {{ text-align: center; font-size: 12.5px; font-weight: 600; color: #64748B; margin-bottom: 8px; }}

        .st-key-login_card, .st-key-admin_card {{
            border: 1px solid #E2E8F0 !important; border-radius: 16px !important;
            box-shadow: 0 12px 36px rgba(15, 23, 42, 0.08) !important;
            padding: 32px 32px 26px 32px !important; background: #FFFFFF !important;
            max-width: 460px; margin: 0 auto;
        }}
        .st-key-admin_card {{ border-color: #1E293B !important; }}

        .st-key-login_card [data-testid="stBaseButton-primary"],
        .st-key-admin_card [data-testid="stBaseButton-primary"],
        .st-key-login_card [data-testid="stBaseButton-secondary"],
        .st-key-admin_card [data-testid="stBaseButton-secondary"] {{
            min-height: 44px !important; border-radius: 10px !important; font-weight: 600 !important; font-size: 14px !important;
        }}
        .st-key-admin_card [data-testid="stBaseButton-primary"] {{ background-color: #0F172A !important; border-color: #0F172A !important; }}
        .st-key-admin_card [data-testid="stBaseButton-primary"]:hover {{ background-color: #1E293B !important; }}

        .st-key-login_card [data-testid="stBaseButton-secondary"]:hover,
        .st-key-admin_card [data-testid="stBaseButton-secondary"]:hover {{
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06) !important;
        }}
        .st-key-login_card button:focus-visible, .st-key-admin_card button:focus-visible {{
            outline: 3px solid rgba(37, 99, 235, 0.18) !important; outline-offset: 1px;
        }}

        .st-key-google_btn button {{
            position: relative; padding-left: 38px !important;
            background-color: #FFFFFF !important; color: #172B4D !important; border: 1px solid #D8E0EA !important;
        }}
        .st-key-google_btn button p {{ padding-left: 4px; }}
        .st-key-google_btn button:hover {{ background-color: #F8FAFC !important; border-color: #B9C7D8 !important; }}
        .st-key-google_btn button::before {{
            content: ""; position: absolute; left: 15px; top: 50%; transform: translateY(-50%);
            width: 18px; height: 18px;
            background-image: url("{google_icon}"); background-size: contain; background-repeat: no-repeat;
        }}

        .st-key-login_demo_open_wrap button, .st-key-admin_demo_open_wrap button,
        .st-key-login_demo_confirm_wrap button, .st-key-admin_demo_confirm_wrap button {{
            background-color: #F8FAFC !important; border: 1px solid #C9D5E3 !important; color: #234A75 !important;
        }}
        .st-key-login_demo_open_wrap button:hover, .st-key-admin_demo_open_wrap button:hover,
        .st-key-login_demo_confirm_wrap button:hover, .st-key-admin_demo_confirm_wrap button:hover {{
            background-color: #EEF4FA !important; border-color: #AEBFD2 !important;
        }}

        .st-key-admin_link_btn button {{
            background: #F8FAFC !important; border: 1px solid #CBD5E1 !important; color: #16395F !important;
            font-weight: 600 !important; min-height: 42px !important; box-shadow: none !important;
        }}
        .st-key-admin_link_btn button:hover {{ border-color: #9FB3C8 !important; background: #EEF3F8 !important; }}

        .st-key-back_to_login_btn button {{
            background: transparent !important; border: none !important; color: #475569 !important;
            font-weight: 600 !important; min-height: 34px !important; box-shadow: none !important;
        }}
        .st-key-back_to_login_btn button:hover {{ color: #174A8B !important; text-decoration: underline; }}

        @media (max-width: 640px) {{
            .st-key-login_card, .st-key-admin_card {{ padding: 24px 18px 20px 18px !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _auth_badge(admin: bool = False) -> None:
    icon_svg = Path("assets/logo_icon.svg").read_text(encoding="utf-8")
    cls = "auth-badge admin" if admin else "auth-badge"
    st.markdown(f'<div class="{cls}">{icon_svg}</div>', unsafe_allow_html=True)


def _demo_mode_block(key_prefix: str) -> None:
    """Secondary, de-emphasized demo access — same underlying identity as
    before (rbac.set_user with is_real_login=False), just presented as a
    lightweight secondary path rather than the primary sign-in method."""
    st.markdown(
        '<div class="auth-secondary-heading">Explore Demo</div>'
        '<div class="auth-secondary-caption">Preview the procurement workspace using sample data.</div>',
        unsafe_allow_html=True,
    )
    open_key = f"_{key_prefix}_demo_open"
    if not st.session_state.get(open_key):
        with st.container(key=f"{key_prefix}_demo_open_wrap"):
            if st.button("Explore Demo →", key=f"{key_prefix}_demo_open_btn", use_container_width=True):
                st.session_state[open_key] = True
                st.rerun()
    else:
        demo_name = st.text_input(
            "Your name", key=f"{key_prefix}_demo_login_name",
            placeholder="e.g. Ayush Tripathi", label_visibility="collapsed",
        )
        with st.container(key=f"{key_prefix}_demo_confirm_wrap"):
            if st.button(
                "Continue as demo user", key=f"{key_prefix}_demo_login_btn",
                use_container_width=True, disabled=not demo_name.strip(),
            ):
                rbac.set_user(demo_name.strip(), "", is_real_login=False)
                st.rerun()


def _render_login_screen(auth_ready: bool) -> None:
    _auth_shell_css()
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        with st.container(key="login_card", border=True):
            _auth_badge()
            st.markdown(
                '<div class="auth-brand">Intelligent Procurement Advisor</div>'
                '<div class="auth-title">Welcome back</div>'
                '<div class="auth-subtitle">Sign in to access your procurement intelligence workspace.</div>',
                unsafe_allow_html=True,
            )

            if auth_ready:
                with st.container(key="google_btn"):
                    if st.button("Continue with Google", type="primary", use_container_width=True):
                        st.login()
                st.markdown(
                    '<div class="auth-divider-row"><div class="auth-divider-line"></div>'
                    '<div class="auth-divider-text">or</div><div class="auth-divider-line"></div></div>',
                    unsafe_allow_html=True,
                )

            _demo_mode_block("login")

            st.markdown(
                '<div class="auth-divider-row" style="margin-top:22px;"><div class="auth-divider-line"></div></div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="auth-admin-label">Administrator?</div>', unsafe_allow_html=True)
            with st.container(key="admin_link_btn"):
                if st.button("Access Admin Portal →", icon=":material/lock:", use_container_width=True, key="_go_admin_portal"):
                    st.session_state._show_admin_portal = True
                    st.rerun()


def _render_admin_portal_screen(auth_ready: bool) -> None:
    _auth_shell_css()
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        with st.container(key="admin_card", border=True):
            _auth_badge(admin=True)
            st.markdown(
                '<div class="auth-title">Admin Portal</div>'
                '<div class="auth-subtitle">Restricted access for authorized system administrators.</div>',
                unsafe_allow_html=True,
            )

            if auth_ready:
                if st.button("Continue Securely", type="primary", use_container_width=True, key="_admin_continue_btn"):
                    st.login()

            with st.container(key="back_to_login_btn"):
                if st.button("← Back to User Sign In", use_container_width=True, key="_back_to_login"):
                    st.session_state._show_admin_portal = False
                    st.rerun()

            st.markdown(
                '<div class="auth-security-note">Protected administrative environment. Administrative '
                "activity may be logged for security and audit purposes.</div>",
                unsafe_allow_html=True,
            )


_google_ready = _auth_configured()
if _google_ready and bool(getattr(st.user, "is_logged_in", False)) and "user" not in st.session_state:
    rbac.set_user(st.user.get("name", "Unknown"), st.user.get("email", ""), is_real_login=True)

if "user" not in st.session_state:
    if st.session_state.get("_show_admin_portal"):
        _render_admin_portal_screen(_google_ready)
    else:
        _render_login_screen(_google_ready)
    st.stop()

# --------------------------------------------------------------------------
# Session-state init — existing keys preserved verbatim so no state/behavior
# from the previous single-page version is lost.
# --------------------------------------------------------------------------
_DEFAULTS = {
    "raw_df": None,
    "chat_history": [],
    "approved_vendor": None,
    "approval_record": None,
    "manager_approval_record": None,
    "director_approval_record": None,
    "knowledge_base": None,
    "kb_report": None,
    "kb_last_upload": None,
    "reviewed_ack": False,
    "manager_reviewed_ack": False,
    "director_reviewed_ack": False,
    "favorite_vendor_ids": [],
    "favorite_reports": [],
    "favorite_searches": [],
    "ai_max_iterations_override": None,
    "notification_settings": {
        "High Risk Vendor": True,
        "Score Updated": True,
        "AI Recommendation Ready": True,
        "Tender Deadline": True,
        "Contract Expiry": True,
    },
}
for _key, _default in _DEFAULTS.items():
    if _key not in st.session_state:
        st.session_state[_key] = _default

rbac.init_identity()
workflow.init_workflow()

tender_repository.init_repository()
if "selected_tender_id" not in st.session_state:
    st.session_state.selected_tender_id = tender_repository.DEFAULT_TENDER_ID

if st.session_state.knowledge_base is None:
    from src import rag

    st.session_state.knowledge_base = rag.KnowledgeBase()

if "assistant_context" not in st.session_state:
    from src import procurement_assistant as pa

    st.session_state.assistant_context = pa.new_conversation_context()

# --------------------------------------------------------------------------
# Navigation — built (but not yet rendered) before the sidebar controls below
# so the nav widget appears at the top of the sidebar, per Streamlit's
# documented "shared shell" multi-page pattern (code before pg.run() executes
# on every page load; the object is created here, .run() happens at the end).
# --------------------------------------------------------------------------
PAGES_BY_SECTION = {
    "MAIN": [("dashboard", st.Page("views/dashboard.py", title="Dashboard", icon=":material/space_dashboard:", default=True))],
    "PROCUREMENT": [
        ("vendors", st.Page("views/vendors.py", title="Vendors", icon=":material/storefront:")),
        ("tenders", st.Page("views/tenders.py", title="Tenders", icon=":material/description:")),
        ("contracts", st.Page("views/contracts.py", title="Contracts", icon=":material/assignment_turned_in:")),
        ("approvals", st.Page("views/approvals.py", title="Approvals", icon=":material/check_circle:")),
    ],
    "AI WORKSPACE": [
        ("ai_assistant", st.Page("views/ai_assistant.py", title="AI Assistant", icon=":material/chat:")),
        ("document_intelligence", st.Page("views/document_intelligence.py", title="Document Intelligence", icon=":material/library_books:")),
        ("recommendations", st.Page("views/recommendations.py", title="Recommendations", icon=":material/insights:")),
        ("anomalies", st.Page("views/anomalies.py", title="Anomalies", icon=":material/report_problem:")),
    ],
    "ANALYTICS": [
        ("vendor_analytics", st.Page("views/vendor_analytics.py", title="Vendor Analytics", icon=":material/bar_chart:")),
        ("spend_analytics", st.Page("views/spend_analytics.py", title="Spend Analytics", icon=":material/payments:")),
        ("risk_analytics", st.Page("views/risk_analytics.py", title="Risk Analytics", icon=":material/monitoring:")),
    ],
    "GOVERNANCE": [
        ("audit_logs", st.Page("views/audit_logs.py", title="Audit Logs", icon=":material/fact_check:")),
        ("activity_timeline", st.Page("views/activity_timeline.py", title="Activity Timeline", icon=":material/history:")),
        ("user_activity", st.Page("views/user_activity.py", title="User Activity", icon=":material/group:")),
    ],
    "ADMINISTRATION": [
        ("users", st.Page("views/users.py", title="Users", icon=":material/person:")),
        ("roles", st.Page("views/roles.py", title="Roles", icon=":material/admin_panel_settings:")),
        ("settings", st.Page("views/settings.py", title="Settings", icon=":material/settings:")),
    ],
}
filtered_pages = rbac.filter_pages(PAGES_BY_SECTION, rbac.current_role())
pg = st.navigation(filtered_pages)

# --------------------------------------------------------------------------
# Sidebar — global tender workspace (pushed above the nav menu by the
# flex-order CSS rule in ui_components.GLOBAL_CSS), then Data (vendor data
# source + Scoring Configuration — the vendor-scoring-weights control — kept
# open by default so it stays discoverable rather than collapsing away).
# --------------------------------------------------------------------------
with st.sidebar:
    ui_components.render_sidebar_branding()
    tender_context.render_tender_workspace()

    with st.expander("Data", icon=":material/tune:", expanded=False, key="data_section"):
        # --- Vendor Data ----------------------------------------------------
        st.markdown('<div class="sb-subhead">Vendor Data</div>', unsafe_allow_html=True)

        if st.session_state.raw_df is not None:
            source_name = st.session_state.get("_data_source_name", "dataset")
            st.markdown(
                f'<div class="sb-data-status">{ui_components.icon_svg("check-circle", size=13, color="#4ADE80")}'
                f'<span>{source_name} &middot; {len(st.session_state.raw_df)} records</span></div>',
                unsafe_allow_html=True,
            )

        with st.popover("Upload CSV", icon=":material/upload:", use_container_width=True, key="upload_popover"):
            uploaded = st.file_uploader("Upload vendor CSV", type="csv", label_visibility="collapsed")
            if uploaded is not None:
                st.session_state.raw_df = load_csv(uploaded)
                st.session_state._data_source_name = uploaded.name
                audit.log_action("Tender Uploaded", "Procurement", uploaded.name, status="Success")
                st.rerun()

        if st.button("Sample Dataset", use_container_width=True, key="use_sample_btn"):
            st.session_state.raw_df = load_csv(SAMPLE_PATH)
            st.session_state._data_source_name = "sample_vendors.csv"
            audit.log_action("Tender Uploaded", "Procurement", "sample_vendors.csv", status="Success")
            st.rerun()

        st.divider()

        # --- Scoring Configuration -------------------------------------------
        st.markdown('<div class="sb-subhead">Scoring Configuration</div>', unsafe_allow_html=True)
        can_edit = rbac.can_edit_weights()
        if not can_edit:
            st.caption(f"Read-only for role: {rbac.current_role()}")

        # A Reset click seeds each slider's widget state to the default
        # BEFORE the sliders below are instantiated (Streamlit widgets read
        # their initial value from session_state if already present), then
        # commits the defaults as the applied weights immediately.
        if st.session_state.pop("_reset_weights_requested", False):
            for feature in FEATURE_COLUMNS:
                st.session_state[f"weight_{feature}"] = int(round(DEFAULT_WEIGHTS[feature] * 100))
            st.session_state.applied_weights = dict(DEFAULT_WEIGHTS)

        # Sliders are 0-100 (%) purely for display — each value is divided
        # back to the original 0.0-1.0 fraction before it ever reaches
        # compute_overall_score(), so the actual scoring math, weight keys,
        # and normalize_weights() behavior are byte-for-byte unchanged.
        # The native label is collapsed and replaced with a custom row
        # (label left, percentage right, same line) — the native per-thumb
        # value badge is hidden via CSS since its position tracks the thumb
        # and can't be pinned to the row's right edge, so this custom row
        # reads the widget's own session_state value to stay in sync.
        weight_pcts = {}
        for feature in FEATURE_COLUMNS:
            state_key = f"weight_{feature}"
            current_pct = st.session_state.get(state_key, int(round(DEFAULT_WEIGHTS[feature] * 100)))
            st.markdown(
                f'<div class="sb-slider-row"><span class="sb-slider-label">{FEATURE_LABELS[feature]}</span>'
                f'<span class="sb-slider-value">{current_pct}%</span></div>',
                unsafe_allow_html=True,
            )
            weight_pcts[feature] = st.slider(
                FEATURE_LABELS[feature], 0, 100, int(round(DEFAULT_WEIGHTS[feature] * 100)), 5,
                key=state_key, disabled=not can_edit, format="%d%%", label_visibility="collapsed",
            )
        total_pct = sum(weight_pcts.values())
        ui_components.sidebar_weight_total(total_pct, valid=(total_pct == 100))

        apply_clicked = st.button(
            "Apply Weights", type="primary", use_container_width=True,
            key="apply_weights_btn", disabled=not can_edit,
        )
        reset_clicked = st.button(
            "Reset to defaults", use_container_width=True,
            key="reset_weights_btn", disabled=not can_edit,
        )

        if reset_clicked:
            audit.log_action(
                "Weight Configuration Reset", "Procurement", "Scoring weights",
                previous=st.session_state.get("applied_weights", dict(DEFAULT_WEIGHTS)), new=dict(DEFAULT_WEIGHTS),
            )
            st.session_state._reset_weights_requested = True
            st.rerun()

        if apply_clicked:
            new_weights = {feature: pct / 100.0 for feature, pct in weight_pcts.items()}
            prev_applied = st.session_state.get("applied_weights", dict(DEFAULT_WEIGHTS))
            if new_weights != prev_applied:
                audit.log_action(
                    "Weight Configuration Changed", "Procurement", "Scoring weights",
                    previous=prev_applied, new=new_weights,
                )
            st.session_state.applied_weights = new_weights
            st.rerun()

        # The ranking engine only ever sees weights committed via Apply/Reset
        # above — dragging a slider previews its percentage and the Total
        # Weight readout live, but doesn't recompute vendor ranking until
        # the user explicitly applies it (matches the Apply Weights action).
        weights = st.session_state.setdefault("applied_weights", dict(DEFAULT_WEIGHTS))

        st.divider()
        st.markdown('<div class="sb-subhead" style="margin-bottom:4px;">Anomaly Sensitivity</div>', unsafe_allow_html=True)
        contamination = st.slider("Expected anomaly rate", 0.02, 0.3, 0.1, 0.01, key="contamination")

    api_key_present = bool(get_api_key())
    st.session_state.api_key_present = api_key_present
    ui_components.sidebar_status_row("AI Service", connected=api_key_present, connected_label="Online")

    rbac.render_sidebar_profile()

if st.session_state.raw_df is None:
    st.info("Upload a CSV in the sidebar, or click **Use sample dataset** to get started.")
    st.stop()

# --------------------------------------------------------------------------
# Deterministic pipeline — unchanged logic, computed once per rerun, shared
# via session_state with every page (src/vendor_scoring.py,
# src/anomaly_detection.py, src/analytics_tools.py are untouched by this
# refactor).
# --------------------------------------------------------------------------
raw_df = coerce_numeric_columns(st.session_state.raw_df)
raw_df["had_missing_data"] = rows_with_missing_mask(raw_df)

report = validate_vendor_data(raw_df)
if report.missing_columns:
    st.error(f"Missing required columns: {', '.join(report.missing_columns)}")
    st.stop()

featured_df = engineer_features(raw_df)
scored_df = compute_overall_score(featured_df, weights)
scored_df = detect_anomalies(scored_df, contamination=contamination)
ranked_df = rank_vendors(scored_df)
ranked_df = add_recommendation_categories(ranked_df)
vendor_options = ranked_df["vendor_id"] + " — " + ranked_df["vendor_name"]

top_vendor_row = ranked_df.sort_values("overall_score", ascending=False).iloc[0]
kpis = dashboard_metrics.compute_kpis(ranked_df)
top_bundle = build_recommendation_bundle(
    ranked_df, top_vendor_row, "Highest overall weighted score across all evaluation criteria."
)

st.session_state.raw_df_clean = raw_df
st.session_state.validation_report = report
st.session_state.featured_df = featured_df
st.session_state.ranked_df = ranked_df
st.session_state.vendor_options = vendor_options
st.session_state.current_weights = weights
st.session_state.top_vendor_row = top_vendor_row
st.session_state.kpis = kpis
st.session_state.top_bundle = top_bundle

# --------------------------------------------------------------------------
# Tender-aware recommendation — the centralized recommendation object every
# page reads from (src/recommendation_engine.py). Deliberately NOT cached:
# recomputed fresh every rerun so switching, creating, or editing a tender
# (src/tender_repository.py) can never show a stale recommendation.
# --------------------------------------------------------------------------
selected_tender = tender_repository.get_tender_or_default(st.session_state.selected_tender_id)
st.session_state.selected_tender = selected_tender
st.session_state.tender_name = selected_tender["title"]
recommendation = recommendation_engine.build_recommendation(ranked_df, st.session_state.selected_tender_id)
st.session_state.recommendation = recommendation

workflow.mark_data_uploaded(len(ranked_df))
workflow.mark_ai_analysis_complete(recommendation["vendor_name"])

if st.session_state.notification_settings.get("High Risk Vendor", True) or st.session_state.notification_settings.get("Score Updated", True):
    notifications.sync_from_ranked_df(ranked_df)
if st.session_state.notification_settings.get("Contract Expiry", True):
    notifications.sync_contract_expiry(st.session_state.awarded_vendors)

# --------------------------------------------------------------------------
# Top header — slim, light, search / notifications / help / identity.
# --------------------------------------------------------------------------
top_search, top_spacer, top_notif, top_help, top_identity = st.columns([3, 3, 0.6, 0.6, 2], vertical_alignment="center")
with top_search:
    query = st.text_input(
        "Search", key="global_search_query",
        placeholder="Search vendors, tenders, documents...",
        label_visibility="collapsed", icon=":material/search:",
    )

with top_notif:
    unread = notifications.unread_count()
    with st.popover(str(unread) if unread else "", icon=":material/notifications:", use_container_width=True):
        st.markdown("##### Notifications")
        if st.button("Mark all read", key="mark_all_notifs_read"):
            notifications.mark_all_read()
            st.rerun()
        notifs = notifications.get_notifications()
        if not notifs:
            st.caption("No notifications yet.")
        for n in notifs[:15]:
            ui_components.notification_card(n["title"], n["message"], f"{n['category']} · {n['created_at']}", unread=not n["read"])

with top_help:
    with st.popover("", icon=":material/help:", use_container_width=True):
        st.markdown("##### About")
        st.caption(
            "Intelligent Procurement Advisor scores and ranks vendors from transparent, deterministic "
            "criteria, flags statistical anomalies for review, and never auto-approves a vendor — every "
            "recommendation requires explicit human sign-off (Procurement → Approvals)."
        )
        if rbac.can_access("audit_logs"):
            st.page_link("views/audit_logs.py", label="Responsible AI notes", icon=":material/policy:")

with top_identity:
    rbac.render_identity_control()

st.markdown(
    '<div style="border-bottom:1px solid #E2E8F0; margin: 0 0 1.1rem 0;"></div>',
    unsafe_allow_html=True,
)

if query.strip():
    with st.container(border=True):
        st.markdown(f"**Search results for _{query}_**")
        results = search.global_search(query, ranked_df, st.session_state.knowledge_base, st.session_state.chat_history)
        if not results:
            st.caption("No matches found.")
        for group, items in results.items():
            st.markdown(f"**{group}**")
            for item in items:
                st.markdown(f"- **{item['label']}** — {item['subtitle']}")

pg.run()
