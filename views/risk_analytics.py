"""Risk Analytics — the risk matrix (likelihood vs. impact, derived from
existing compliance/financial scores) and the compliance-risk vendor list.
Reuses src/dashboard.py and src/analytics_tools.py — no new risk model."""
import plotly.express as px
import streamlit as st

from src import dashboard as db, reports, ui_components
from src.analytics_tools import get_compliance_risks

ranked_df = st.session_state.ranked_df

st.title("Risk Analytics")

risk_matrix = db.build_risk_matrix(ranked_df)
fig_risk = px.scatter(
    risk_matrix, x="likelihood", y="impact", color="is_anomalous",
    color_discrete_map={True: ui_components.RED, False: ui_components.BLUE}, hover_name="vendor_name", size="overall_score",
    labels={"likelihood": "Likelihood (100 − compliance score)", "impact": "Impact (100 − financial stability score)"},
    title="Risk Matrix: Likelihood vs. Impact",
)
fig_risk.add_hline(y=50, line_dash="dot", opacity=0.4)
fig_risk.add_vline(x=50, line_dash="dot", opacity=0.4)
st.plotly_chart(ui_components.style_chart(fig_risk), use_container_width=True, config=ui_components.PLOTLY_CONFIG)
st.caption("Likelihood and impact are simple proxies derived from existing compliance/financial scores — not a separate model.")

st.header("Compliance Risk Vendors")
compliance_risks = get_compliance_risks(ranked_df)
if compliance_risks.empty:
    ui_components.empty_state("No compliance risks", "All vendors meet or exceed the compliance threshold.")
else:
    ui_components.data_table(compliance_risks)

if st.button("Download Risk Report PDF", icon=":material/download:"):
    pdf_bytes = reports.generate_risk_report(risk_matrix, compliance_risks)
    st.download_button("Save Risk_Report.pdf", pdf_bytes, file_name="Risk_Report.pdf", mime="application/pdf")
