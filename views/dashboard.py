"""Dashboard — light enterprise landing page: welcome header, KPI row with
sparklines, recommended-vendor / procurement-overview / risk-distribution
cards, a score-breakdown section, and a recent-activity + alerts row.

Every recommendation-related value on this page reads from
st.session_state.recommendation (src/recommendation_engine.py) — the single
centralized, tender-aware recommendation object — never computed locally.
Everything else is read from st.session_state as before, computed once in
app.py by the unchanged scoring/anomaly pipeline."""
import streamlit as st

from src import audit, dashboard as db, notifications, reports, rbac, ui_components

ranked_df = st.session_state.ranked_df
kpis = st.session_state.kpis
top_bundle = st.session_state.top_bundle
recommendation = st.session_state.recommendation
pool_df = recommendation["scored_pool_df"]
bv = kpis["business_value"]

# --------------------------------------------------------------------------
# Welcome header
# --------------------------------------------------------------------------
header_left, header_right = st.columns([3, 2], vertical_alignment="center")
with header_left:
    st.markdown(
        f'<div class="welcome-title">Welcome back, {rbac.current_user_name()}</div>'
        f'<div class="welcome-sub">Here\'s what\'s happening with your procurement operations today '
        f'&middot; {st.session_state.tender_name}</div>',
        unsafe_allow_html=True,
    )
with header_right:
    btn_export, btn_new = st.columns(2)
    with btn_export:
        if ui_components.secondary_button("Export Report", icon=":material/download:", key="export_report_btn", use_container_width=True):
            st.session_state["_dash_export_pdf"] = reports.generate_executive_report(kpis, top_bundle)
        if st.session_state.get("_dash_export_pdf"):
            st.download_button(
                "Save Executive_Report.pdf", st.session_state["_dash_export_pdf"],
                file_name="Executive_Report.pdf", mime="application/pdf", key="export_report_dl",
            )
    with btn_new:
        if st.button(
            "New Tender", icon=":material/add:", type="primary", key="new_tender_btn",
            use_container_width=True, disabled=not rbac.can_access("tenders"),
        ):
            st.switch_page("views/tenders.py")

st.write("")

# --------------------------------------------------------------------------
# Row 1 — four KPI cards with sparklines, all tender-scoped
# --------------------------------------------------------------------------
sparks = db.build_kpi_sparklines(ranked_df, kpis)
confidence_pct = recommendation["confidence"] * 100
conf_tone = "success" if confidence_pct >= 70 else ("warning" if confidence_pct >= 40 else "danger")
conf_word = {"success": "High", "warning": "Medium", "danger": "Low"}[conf_tone]
risk_level, risk_tone = db.compute_risk_level(pool_df)

row1 = st.columns(4)
with row1[0]:
    with st.container(border=True, height=148):
        ui_components.kpi_card_v2(
            "Overall Procurement Confidence", f"{confidence_pct:.0f}%", f"{conf_word} Confidence",
            icon="trending-up", spark_values=sparks["confidence"], tone=conf_tone, key="spark_confidence",
        )
with row1[1]:
    with st.container(border=True, height=148):
        ui_components.kpi_card_v2(
            "Vendors Evaluated", str(recommendation["evaluated_vendors"]), f"{recommendation['qualified_vendors']} Qualified",
            icon="users", spark_values=sparks["vendors"], tone="info", key="spark_vendors",
        )
with row1[2]:
    with st.container(border=True, height=148):
        ui_components.kpi_card_v2(
            "Procurement Risk Level", risk_level, f"{recommendation['anomalous_count']} Anomalous",
            icon="shield-alert", spark_values=sparks["risk"], tone=risk_tone, key="spark_risk",
        )
with row1[3]:
    with st.container(border=True, height=148):
        ui_components.kpi_card_v2(
            "Est. Decision Time Reduction", f"{bv['reduction_pct']:.0f}%", "vs Manual Process",
            icon="clock", spark_values=sparks["decision_time"], tone="success", key="spark_decision",
        )

st.write("")

# --------------------------------------------------------------------------
# Row 2 — recommended vendor (tender-specific) / procurement overview / risk distribution
# --------------------------------------------------------------------------
row2 = st.columns(3)
CARD_HEIGHT = 400

with row2[0]:
    with st.container(border=True, height=CARD_HEIGHT):
        head_l, head_r = st.columns([5, 1], vertical_alignment="center")
        with head_l:
            st.caption("Recommended Vendor")
            st.markdown(f"**{recommendation['vendor_name']}**")
        with head_r:
            st.markdown(
                f'<div style="text-align:right">{ui_components.icon_svg("award", size=20, color="#F59E0B")}</div>',
                unsafe_allow_html=True,
            )
        if recommendation["vendor_id"]:
            score_col, rank_col = st.columns(2)
            score_col.metric("Score", f"{recommendation['final_score']:.1f} / 100")
            rank_col.metric("Rank", f"#{recommendation['rank']} of {recommendation['qualified_vendors']}")
            ui_components.status_badge(
                recommendation["eligibility_status"],
                tone="success" if recommendation["eligibility_status"] == "Qualified" else "warning",
            )
            st.caption(recommendation["reasoning"])
            st.write("")
            st.markdown("**Why this vendor?**")
            ui_components.reason_list(recommendation["strengths"][:4], icon="check-circle", color=ui_components.GREEN)
            if recommendation["risks"]:
                ui_components.reason_list(recommendation["risks"][:3], icon="alert-triangle", color=ui_components.AMBER)
        else:
            st.warning(recommendation["risks"][0] if recommendation["risks"] else "No eligible vendor found.", icon=":material/warning:")
            closest = recommendation.get("closest_matches") or []
            if closest:
                st.markdown("**Closest Matches**")
                for c in closest:
                    st.markdown(f"- {c['vendor_name']} — {c['match_pct']:.0f}% requirement match")
                st.caption("Consider expanding the supplier pool or modifying non-mandatory requirements.")
        st.write("")
        if rbac.can_access("recommendations"):
            st.page_link("views/recommendations.py", label="View full analysis", icon=":material/arrow_forward:")

with row2[1]:
    with st.container(border=True, height=CARD_HEIGHT):
        st.markdown("**Procurement Overview**")
        st.caption(f"Vendors by evaluation outcome · {recommendation['tender_title']}")
        overview = db.build_evaluation_overview(pool_df)
        overview_colors = {
            "Recommended for Shortlist": ui_components.GREEN,
            "Acceptable with Conditions": ui_components.BLUE,
            "Not Recommended": ui_components.SLATE,
            "Review Required — Anomaly Detected": ui_components.RED,
        }
        if overview:
            colors = [overview_colors[k] for k in overview]
            ui_components.donut_chart(
                list(overview.keys()), list(overview.values()), colors,
                str(recommendation["evaluated_vendors"]), "Total Vendors", key="donut_overview",
            )
            ui_components.chart_legend([{"label": k, "value": v, "color": overview_colors[k]} for k, v in overview.items()])
        else:
            st.caption("No vendors evaluated for this tender yet.")
        if rbac.can_access("vendor_analytics"):
            st.page_link("views/vendor_analytics.py", label="View vendor analytics", icon=":material/arrow_forward:")

with row2[2]:
    with st.container(border=True, height=CARD_HEIGHT):
        st.markdown("**Risk Distribution**")
        st.caption(f"Vendors by risk level · {recommendation['tender_title']}")
        dist = db.build_risk_distribution(pool_df)
        dist_colors = {"Low": ui_components.GREEN, "Medium": ui_components.AMBER, "High": ui_components.RED}
        if any(dist.values()):
            colors = [dist_colors[k] for k in dist]
            ui_components.donut_chart(
                list(dist.keys()), list(dist.values()), colors,
                str(recommendation["evaluated_vendors"]), "Total Vendors", key="donut_risk",
            )
            ui_components.chart_legend([{"label": f"{k} Risk", "value": v, "color": dist_colors[k]} for k, v in dist.items()])
        else:
            st.caption("No vendors evaluated for this tender yet.")
        if rbac.can_access("risk_analytics"):
            st.page_link("views/risk_analytics.py", label="View risk analytics", icon=":material/arrow_forward:")

st.write("")

# --------------------------------------------------------------------------
# Score Breakdown — tender-specific evaluation criteria applied to the
# recommended vendor, from the same recommendation object as everything else.
# --------------------------------------------------------------------------
breakdown = recommendation.get("score_breakdown") or {}
if breakdown:
    with st.container(border=True):
        st.markdown(f"**Score Breakdown** — {recommendation['vendor_name']}")
        dim_items = [(label, vals) for label, vals in breakdown.items() if label != "Total"]
        cols = st.columns(3)
        for i, (label, vals) in enumerate(dim_items):
            with cols[i % 3]:
                fraction = min(vals["points"] / vals["max"], 1.0) if vals["max"] else 0.0
                st.progress(fraction, text=f"{label}  ·  {vals['points']:.1f} / {vals['max']:.1f}")
        total = breakdown.get("Total", {"points": 0, "max": 0})
        st.markdown(f"**Total: {total['points']:.1f} / {total['max']:.1f}**")
    st.write("")

# --------------------------------------------------------------------------
# Row 3 — recent activity / alerts & notifications
# --------------------------------------------------------------------------
_ACTION_TONE = {
    "Tender Uploaded": "info",
    "Tender Selected": "info",
    "Tender Stage Advanced": "info",
    "Vendor Viewed": "neutral",
    "Document Uploaded": "info",
    "Knowledge Base Built": "info",
    "Manager Approval Granted": "success",
    "Director Approval Granted": "success",
    "Contract Awarded": "success",
    "Weight Configuration Changed": "neutral",
    "User Login": "neutral",
}

row3 = st.columns(2)
with row3[0]:
    with st.container(border=True, height=320):
        act_head_l, act_head_r = st.columns([3, 1.4], vertical_alignment="center")
        act_head_l.markdown("**Recent Activity**")
        with act_head_r:
            if rbac.can_access("activity_timeline"):
                st.page_link("views/activity_timeline.py", label="View all", icon=":material/arrow_forward:")
        audit_df = audit.get_audit_df().head(6)
        rows = [
            {
                "title": r["Action"],
                "sub": r["Affected Object"],
                "user": r["Username"],
                "time": db.relative_time(r["Timestamp"]),
                "tone": _ACTION_TONE.get(r["Action"], "neutral"),
            }
            for _, r in audit_df.iterrows()
        ]
        ui_components.activity_table(rows)

with row3[1]:
    with st.container(border=True, height=320):
        st.markdown("**Alerts & Notifications**")
        notifs = notifications.get_notifications()
        high_risk = [n for n in notifs if n["category"] == "High Risk Vendor"]
        other = [n for n in notifs if n["category"] != "High Risk Vendor"]

        alert_items = []
        if high_risk:
            alert_items.append({
                "icon": "shield-alert", "tone": "danger",
                "title": f"{len(high_risk)} vendor(s) flagged as high risk",
                "sub": "Require immediate attention",
                "time": db.relative_time(high_risk[0]["created_at"]),
            })
        _ALERT_ICON = {
            "Score Updated": ("trending-up", "info"),
            "Tender Deadline": ("clock", "warning"),
            "Contract Expiry": ("clock", "warning"),
            "AI Recommendation Ready": ("lightbulb", "success"),
        }
        for n in other[:4]:
            icon, tone = _ALERT_ICON.get(n["category"], ("bell", "info"))
            alert_items.append({
                "icon": icon, "tone": tone, "title": n["title"], "sub": n["message"],
                "time": db.relative_time(n["created_at"]),
            })
        ui_components.alert_list(alert_items[:5])
