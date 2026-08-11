"""Recommendations — full recommendation bundle for any vendor (not just the
top pick) plus the dynamic Procurement Insights feed. All facts come from
src.analytics_tools / src.dashboard; nothing here is computed by an LLM."""
import streamlit as st

from src import dashboard as db, reports, ui_components
from src.analytics_tools import build_recommendation_bundle

ranked_df = st.session_state.ranked_df
vendor_options = st.session_state.vendor_options

st.title("Recommendations")

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
