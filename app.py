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
st.logo("assets/logo.svg", icon_image="assets/logo_icon.svg", size="large")
ui_components.inject_global_css()


# --------------------------------------------------------------------------
# Login gate — Google/OIDC sign-in via Streamlit's native st.login(). Nothing
# below this block renders until the user is authenticated. When no identity
# provider is configured yet (local dev without .streamlit/secrets.toml), a
# clearly-labeled demo-mode fallback keeps the rest of the app testable —
# see .streamlit/secrets.toml.example for the real Google OAuth setup.
# --------------------------------------------------------------------------
def _auth_configured() -> bool:
    try:
        return bool(st.secrets.get("auth", {}).get("client_id"))
    except Exception:
        return False


def _render_login_screen(auth_ready: bool) -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { display: none; }
        [data-testid="stMainBlockContainer"] { padding-top: 8vh; }
        .login-title { font-size: 26px; font-weight: 700; color: #0F172A; margin-top: 16px; text-align: center; }
        .login-sub { font-size: 14px; color: #64748B; margin-top: 6px; margin-bottom: 28px; text-align: center; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        with st.container(border=True):
            icon_l, icon_r = st.columns([1, 4])
            with icon_l:
                st.image("assets/logo_icon.svg", width=48)
            st.markdown(
                '<div class="login-title">Intelligent Procurement Advisor</div>'
                '<div class="login-sub">Sign in with Google to continue</div>',
                unsafe_allow_html=True,
            )
            if auth_ready:
                if st.button("Continue with Google", icon=":material/login:", type="primary", use_container_width=True):
                    st.login()
            else:
                st.button("Continue with Google", icon=":material/login:", type="primary", use_container_width=True, disabled=True)
                st.caption("Google sign-in isn't configured yet — add an `[auth]` block to `.streamlit/secrets.toml` (see `secrets.toml.example`).")
                with st.expander("Continue in demo mode"):
                    demo_name = st.text_input("Your name", key="_demo_login_name", placeholder="e.g. Ayush Tripathi")
                    if st.button("Continue as demo user", use_container_width=True, disabled=not demo_name.strip()):
                        rbac.set_user(demo_name.strip(), "", is_real_login=False)
                        st.rerun()


_google_ready = _auth_configured()
if _google_ready and bool(getattr(st.user, "is_logged_in", False)) and "user" not in st.session_state:
    rbac.set_user(st.user.get("name", "Unknown"), st.user.get("email", ""), is_real_login=True)

if "user" not in st.session_state:
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
# flex-order CSS rule in ui_components.GLOBAL_CSS), then data source +
# scoring configuration, collapsed by default once a tender is loaded.
# --------------------------------------------------------------------------
with st.sidebar:
    tender_context.render_tender_workspace()

    with st.expander("Data & Scoring", icon=":material/tune:", expanded=(st.session_state.raw_df is None)):
        st.caption("VENDOR DATA SOURCE")
        uploaded = st.file_uploader("Upload vendor CSV", type="csv", label_visibility="collapsed")
        use_sample = st.button("Use sample dataset", use_container_width=True)

        if uploaded is not None:
            st.session_state.raw_df = load_csv(uploaded)
            audit.log_action("Tender Uploaded", "Procurement", uploaded.name, status="Success")
        elif use_sample:
            st.session_state.raw_df = load_csv(SAMPLE_PATH)
            audit.log_action("Tender Uploaded", "Procurement", "sample_vendors.csv", status="Success")

        st.divider()
        st.caption("SCORING CONFIGURATION")
        can_edit = rbac.can_edit_weights()
        if not can_edit:
            st.caption(f"Read-only for role: {rbac.current_role()}")
        weights = {
            feature: st.slider(
                FEATURE_LABELS[feature], 0.0, 1.0, DEFAULT_WEIGHTS[feature], 0.05,
                key=f"weight_{feature}", disabled=not can_edit,
            )
            for feature in FEATURE_COLUMNS
        }

        prev_weights = st.session_state.get("_prev_weights")
        if prev_weights is not None and prev_weights != weights:
            audit.log_action(
                "Weight Configuration Changed", "Procurement", "Scoring weights",
                previous=prev_weights, new=weights,
            )
        st.session_state._prev_weights = dict(weights)

        st.divider()
        st.caption("ANOMALY SENSITIVITY")
        contamination = st.slider("Expected anomaly rate", 0.02, 0.3, 0.1, 0.01, key="contamination")

    api_key_present = bool(get_api_key())
    st.session_state.api_key_present = api_key_present
    st.caption(f"Claude API · {'Enabled' if api_key_present else 'Fallback mode'}")

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
