"""Vendor Analytics — chart-heavy visuals over the already-computed ranking,
plus a banner referencing the same centralized tender recommendation shown
on Dashboard/Recommendations/Tenders (src/recommendation_engine.py)."""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import dashboard as db, ui_components

ranked_df = st.session_state.ranked_df
recommendation = st.session_state.recommendation

st.title("Vendor Analytics")

with st.container(border=True):
    rec_l, rec_r = st.columns([3, 1])
    with rec_l:
        st.caption(f"Tender: {recommendation['tender_title']}")
        if recommendation["vendor_id"]:
            st.markdown(f"**Recommended: {recommendation['vendor_name']}** ({recommendation['vendor_id']})")
        else:
            st.markdown("**No eligible vendor found for this tender.**")
    with rec_r:
        if recommendation["vendor_id"]:
            st.metric("Score", f"{recommendation['final_score']:.1f} / 100")

fig_rank = px.bar(
    ranked_df, x="vendor_name", y="overall_score", color="is_anomalous",
    color_discrete_map={True: ui_components.RED, False: ui_components.BLUE},
    labels={"overall_score": "Overall Score", "vendor_name": "Vendor", "is_anomalous": "Anomalous"},
    title="Vendor Ranking (all evaluated vendors)",
)
fig_rank.update_layout(xaxis_tickangle=-45)
st.plotly_chart(ui_components.style_chart(fig_rank), use_container_width=True, config=ui_components.PLOTLY_CONFIG)

col1, col2 = st.columns(2)
with col1:
    fig_scatter = px.scatter(
        ranked_df, x="price_competitiveness", y="quality_score", color="is_anomalous",
        color_discrete_map={True: ui_components.RED, False: ui_components.BLUE}, size="overall_score", hover_name="vendor_name",
        labels={"price_competitiveness": "Price Competitiveness", "quality_score": "Quality", "is_anomalous": "Anomalous"},
        title="Price vs. Quality (anomalies highlighted)",
    )
    st.plotly_chart(ui_components.style_chart(fig_scatter), use_container_width=True, config=ui_components.PLOTLY_CONFIG)

with col2:
    confidence_pct = recommendation["confidence"] * 100
    fig_gauge = go.Figure(
        go.Indicator(
            mode="gauge+number", value=confidence_pct, number={"suffix": "%"},
            title={"text": "Tender Recommendation Confidence"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": ui_components.confidence_color(confidence_pct)},
                "bgcolor": ui_components.SURFACE,
                "bordercolor": ui_components.BORDER,
                "steps": [
                    {"range": [0, 50], "color": "rgba(239,68,68,0.12)"},
                    {"range": [50, 75], "color": "rgba(245,158,11,0.12)"},
                    {"range": [75, 100], "color": "rgba(22,163,74,0.12)"},
                ],
            },
        )
    )
    st.plotly_chart(
        ui_components.style_chart(fig_gauge, height=280), use_container_width=True, config=ui_components.PLOTLY_CONFIG,
    )

st.markdown("### Top 10 Vendor Leaderboard")
st.caption("All evaluated vendors, ranked by generic overall score — not limited to the current tender's eligible category.")
top10 = ranked_df.sort_values("overall_score", ascending=False).head(10)[
    ["rank", "vendor_name", "vendor_id", "overall_score", "category", "is_anomalous"]
].copy()
top10["rank"] = top10["rank"].astype(int)
eligibility_by_id = {r["vendor_id"]: r["eligibility_status"] for r in recommendation["ranking"]}
top10["tender_eligibility"] = top10["vendor_id"].map(eligibility_by_id).fillna("Not eligible for this tender")
ui_components.data_table(top10)
