"""Vendor Analytics — chart-heavy visuals over the already-computed ranking."""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import dashboard as db, ui_components

ranked_df = st.session_state.ranked_df
kpis = st.session_state.kpis

st.title("Vendor Analytics")

fig_rank = px.bar(
    ranked_df, x="vendor_name", y="overall_score", color="is_anomalous",
    color_discrete_map={True: ui_components.RED, False: ui_components.BLUE},
    labels={"overall_score": "Overall Score", "vendor_name": "Vendor", "is_anomalous": "Anomalous"},
    title="Vendor Ranking",
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
    fig_gauge = go.Figure(
        go.Indicator(
            mode="gauge+number", value=kpis["confidence"], number={"suffix": "%"},
            title={"text": "Overall Procurement Confidence"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": ui_components.confidence_color(kpis["confidence"])},
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
top10 = ranked_df.sort_values("overall_score", ascending=False).head(10)[
    ["rank", "vendor_name", "vendor_id", "overall_score", "category", "is_anomalous"]
].copy()
top10["rank"] = top10["rank"].astype(int)
ui_components.data_table(top10)
