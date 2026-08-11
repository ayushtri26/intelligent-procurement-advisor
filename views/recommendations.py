"""Recommendations — the tender-specific centralized recommendation (from
src/recommendation_engine.py) as the primary content, plus the existing
"build a full recommendation for any vendor" inspection tool and the
dynamic Procurement Insights feed below it. All facts come from
src.recommendation_engine / src.analytics_tools / src.dashboard; nothing
here is computed by an LLM."""
import streamlit as st

from src import dashboard as db, reports, ui_components
from src.analytics_tools import build_recommendation_bundle

ranked_df = st.session_state.ranked_df
vendor_options = st.session_state.vendor_options
recommendation = st.session_state.recommendation

# --------------------------------------------------------------------------
# Tender Recommendation — the single source of truth for this tender,
# consistent with Dashboard, Tenders, Vendor Analytics, and the AI Assistant.
# --------------------------------------------------------------------------
st.title("Recommendations")
st.caption(f"Tender: {recommendation['tender_title']}")

if recommendation["vendor_id"]:
    with st.container(border=True):
        top_c1, top_c2 = st.columns([2, 1])
        with top_c1:
            st.subheader(recommendation["vendor_name"])
            st.caption(f"{recommendation['vendor_id']} · Rank #{recommendation['rank']} of {recommendation['qualified_vendors']} qualified")
        with top_c2:
            st.metric("Final Score", f"{recommendation['final_score']:.1f} / 100")
            ui_components.status_badge(f"Confidence: {recommendation['confidence'] * 100:.0f}%", tone="info")

        st.caption(recommendation["reasoning"])

        st.markdown("**Why this vendor?**")
        ui_components.reason_list(recommendation["strengths"], icon="check-circle", color=ui_components.GREEN)
        if recommendation["risks"]:
            st.markdown("**Risks / considerations:**")
            ui_components.reason_list(recommendation["risks"], icon="alert-triangle", color=ui_components.AMBER)

        breakdown = recommendation.get("score_breakdown") or {}
        if breakdown:
            st.markdown("**Score Breakdown**")
            dim_items = [(label, vals) for label, vals in breakdown.items() if label != "Total"]
            cols = st.columns(3)
            for i, (label, vals) in enumerate(dim_items):
                with cols[i % 3]:
                    fraction = min(vals["points"] / vals["max"], 1.0) if vals["max"] else 0.0
                    st.progress(fraction, text=f"{label} · {vals['points']:.1f} / {vals['max']:.1f}")
            total = breakdown.get("Total", {"points": 0, "max": 0})
            st.markdown(f"**Total: {total['points']:.1f} / {total['max']:.1f}**")

        st.caption("This is a recommendation only — final selection requires explicit human approval.")

    if len(recommendation["ranking"]) > 1:
        with st.expander(f"Full tender ranking ({len(recommendation['ranking'])} vendor(s))"):
            ui_components.data_table(recommendation["ranking"])
else:
    st.warning("No eligible vendor found for this tender's category or mandatory requirements.", icon=":material/warning:")

st.divider()

# --------------------------------------------------------------------------
# Inspect any vendor — supplementary tool, independent of tender eligibility.
# --------------------------------------------------------------------------
st.header("Inspect Any Vendor")
st.caption("Build a full recommendation bundle for any evaluated vendor, regardless of tender eligibility.")

selected = st.selectbox("Build a full recommendation for", vendor_options, index=0)
selected_id = selected.split(" — ")[0]
row = ranked_df.loc[ranked_df["vendor_id"] == selected_id].iloc[0]
bundle = build_recommendation_bundle(ranked_df, row, "Selected for recommendation review.")

with st.container(border=True):
    top_c1, top_c2 = st.columns([2, 1])
    with top_c1:
        st.subheader(bundle["recommended_vendor"]["vendor_name"])
        st.caption(f"{bundle['recommended_vendor']['vendor_id']} · Rank #{bundle['recommended_vendor']['rank']}")
    with top_c2:
        st.metric("Overall Score", f"{bundle['recommended_vendor']['overall_score']:.1f} / 100")
        ui_components.status_badge(f"Confidence: {bundle['confidence']}", tone=ui_components.confidence_label_tone(bundle["confidence"]))

    st.markdown("**Why recommended:**")
    for reason in bundle["key_reasons"]:
        st.markdown(f"- {reason}")

    tco1, tco2 = st.columns(2)
    with tco1:
        st.markdown("**Trade-offs:**")
        for t in (bundle["trade_offs"] or ["None significant versus the next-best alternative."]):
            st.markdown(f"- {t}")
    with tco2:
        st.markdown("**Due diligence:**")
        for d in bundle["due_diligence"]:
            st.markdown(f"- {d}")

    st.markdown("**Status:**")
    if bundle["is_anomalous"]:
        ui_components.status_badge("Anomaly Flagged", tone="warning")
    else:
        ui_components.status_badge("No anomaly", tone="success")
    st.caption("This is a recommendation only — final selection requires explicit human approval.")

st.header("Procurement Insights")
st.caption("Automatically generated from the current evaluation — no manual analysis required.")
insights = db.generate_insights(ranked_df)
with st.container(border=True):
    for insight in insights:
        st.markdown(f"- {insight}")

if st.button("Download Insights PDF", icon=":material/download:"):
    pdf_bytes = reports.generate_insights_report(insights)
    st.download_button("Save Procurement_Insights.pdf", pdf_bytes, file_name="Procurement_Insights.pdf", mime="application/pdf")
