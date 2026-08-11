"""Spend Analytics — charts derived purely from existing CSV price columns
(quoted_price, market_avg_price, category). No new business logic; this is
a new lens on data the pipeline already loaded."""
import pandas as pd
import plotly.express as px
import streamlit as st

from src import reports, ui_components

ranked_df = st.session_state.ranked_df

st.title("Spend Analytics")

total_quoted = ranked_df["quoted_price"].sum()
total_market = ranked_df["market_avg_price"].sum()
delta = total_market - total_quoted

k1, k2, k3 = st.columns(3)
with k1:
    with st.container(border=True):
        ui_components.kpi_card("Total Quoted Spend", f"${total_quoted:,.0f}")
with k2:
    with st.container(border=True):
        ui_components.kpi_card("Total Market-Average Spend", f"${total_market:,.0f}")
with k3:
    with st.container(border=True):
        ui_components.kpi_card("Illustrative Savings vs. Market Avg", f"${delta:,.0f}", "quoted below market average" if delta > 0 else "quoted above market average")

if "category" in ranked_df.columns:
    by_category = ranked_df.groupby("category")["quoted_price"].sum().sort_values(ascending=False).reset_index()
    fig_cat = px.bar(by_category, x="category", y="quoted_price", title="Spend by Category", labels={"quoted_price": "Total Quoted Price", "category": "Category"})
    st.plotly_chart(ui_components.style_chart(fig_cat), use_container_width=True, config=ui_components.PLOTLY_CONFIG)

savings_df = ranked_df[["vendor_name", "quoted_price", "market_avg_price"]].copy()
savings_df["delta"] = savings_df["market_avg_price"] - savings_df["quoted_price"]
savings_df = savings_df.sort_values("delta", ascending=False)

fig_delta = px.bar(
    savings_df, x="vendor_name", y="delta", title="Price Delta vs. Market Average (positive = below market)",
    labels={"delta": "Market Avg − Quoted", "vendor_name": "Vendor"},
)
fig_delta.update_layout(xaxis_tickangle=-45)
st.plotly_chart(ui_components.style_chart(fig_delta), use_container_width=True, config=ui_components.PLOTLY_CONFIG)

st.header("Savings Opportunities (Illustrative)")
st.caption("Comparison of quoted price to market average price — an illustrative estimate, not an audited savings figure.")
ui_components.data_table(savings_df.rename(columns={"vendor_name": "Vendor", "quoted_price": "Quoted Price", "market_avg_price": "Market Avg", "delta": "Delta"}))

if st.button("Download Savings Opportunities PDF", icon=":material/download:"):
    pdf_bytes = reports.generate_savings_report(savings_df)
    st.download_button("Save Savings_Opportunities.pdf", pdf_bytes, file_name="Savings_Opportunities.pdf", mime="application/pdf")
