"""Vendors — data validation, feature engineering preview, ranking table,
and full vendor detail / explainability. All computation is read from
st.session_state; nothing here recalculates scores or anomalies."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import audit, dashboard as db, reports, ui_components
from src.analytics_tools import explain_vendor
from src.anomaly_detection import get_anomaly_drivers
from src.feature_engineering import FEATURE_COLUMNS
from src.analytics_tools import FEATURE_LABELS
from src.recommendation import generate_llm_narrative, generate_recommendation_text

ranked_df = st.session_state.ranked_df
featured_df = st.session_state.featured_df
report = st.session_state.validation_report
raw_df = st.session_state.raw_df_clean
vendor_options = st.session_state.vendor_options
api_key_present = st.session_state.api_key_present

st.title("Vendors")

with st.expander("Data validation", expanded=False):
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Vendors", report.total_rows)
    c2.metric("Rows with Missing Values", report.rows_with_missing)
    c3.metric("Duplicate Vendor IDs", len(report.duplicate_vendor_ids))
    if report.has_missing_values:
        missing_df = pd.DataFrame({"missing_count": report.missing_counts, "missing_pct (%)": report.missing_pct})
        missing_df = missing_df[missing_df["missing_count"] > 0]
        ui_components.data_table(missing_df)
        st.caption("Missing numeric values are imputed with the column median before scoring; affected vendors are flagged internally.")
    else:
        st.success("No missing values detected.")
    with st.expander("Preview raw data"):
        ui_components.data_table(raw_df)

with st.expander("Engineered feature scores", expanded=False):
    ui_components.data_table(featured_df[["vendor_id", "vendor_name", "category"] + FEATURE_COLUMNS])

st.header("Vendor Ranking")
display_cols = ["rank", "vendor_id", "vendor_name", "category", "overall_score", "is_anomalous"] + FEATURE_COLUMNS
ui_components.data_table(ranked_df[display_cols])

n_anomalous = int(ranked_df["is_anomalous"].sum())
if n_anomalous:
    st.warning(f"{n_anomalous} vendor(s) flagged as anomalous — see Anomalies for details before approval.", icon=":material/warning:")

st.header("Vendor Inspection")
selected = st.selectbox("Select a vendor to inspect", vendor_options)
selected_id = selected.split(" — ")[0]

if st.session_state.get("_last_viewed_vendor") != selected_id:
    st.session_state._last_viewed_vendor = selected_id
    audit.log_action("Vendor Viewed", "Procurement", selected, status="Success")

vendor_row = ranked_df.loc[ranked_df["vendor_id"] == selected_id].iloc[0]
info = explain_vendor(ranked_df, selected_id)
rec = info["record"]

fav_col, _ = st.columns([1, 6])
with fav_col:
    is_fav = selected_id in st.session_state.favorite_vendor_ids
    if st.button("Unsave" if is_fav else "Save", icon=":material/star:" if is_fav else ":material/star_border:", key="fav_toggle"):
        if is_fav:
            st.session_state.favorite_vendor_ids.remove(selected_id)
        else:
            st.session_state.favorite_vendor_ids.append(selected_id)
        st.rerun()

profile_cols = st.columns(4)
profile_cols[0].metric("Overall Score", f"{rec['overall_score']:.1f} / 100")
profile_cols[1].metric("Rank", f"#{rec['rank']} of {len(ranked_df)}")
profile_cols[2].metric("Category", rec.get("category", "N/A"))
profile_cols[3].metric("Confidence", info["confidence"])

chart_col, detail_col = st.columns([1, 1])
with chart_col:
    fig_radar = go.Figure()
    r_values = [vendor_row[f] for f in FEATURE_COLUMNS]
    theta_values = [FEATURE_LABELS[f] for f in FEATURE_COLUMNS]
    fig_radar.add_trace(go.Scatterpolar(
        r=r_values + [r_values[0]], theta=theta_values + [theta_values[0]], fill="toself",
        name=rec["vendor_name"], line=dict(color=ui_components.BLUE), fillcolor="rgba(59,130,246,0.15)",
    ))
    fig_radar.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(visible=True, range=[0, 100], gridcolor=ui_components.BORDER),
            angularaxis=dict(gridcolor=ui_components.BORDER),
        ),
        showlegend=False, title="Feature Score Breakdown",
    )
    st.plotly_chart(ui_components.style_chart(fig_radar), use_container_width=True, config=ui_components.PLOTLY_CONFIG)

    st.markdown("**Score Contribution**")
    contrib = db.build_score_contribution(vendor_row, st.session_state.current_weights)
    ui_components.score_panel(FEATURE_LABELS, contrib)

with detail_col:
    drivers = []
    if rec["is_anomalous"]:
        st.error(f"Anomaly Detected — Risk Rating: {info['recommendation_category']}", icon=":material/report_problem:")
        drivers = get_anomaly_drivers(ranked_df, selected_id)
        st.markdown("**Reason for anomaly:**")
        for d in drivers:
            st.markdown(f"- **{FEATURE_LABELS.get(d['feature'], d['feature'])}**: {d['value']} vs peer avg {d['peer_average']} ({d['direction']} average, z={d['z_score']})")
    else:
        st.success(f"No anomaly detected — Risk Rating: {info['recommendation_category']}", icon=":material/check_circle:")

    st.write("**Strengths:**", ", ".join(info["strengths"]) or "None identified")
    st.write("**Weaknesses:**", ", ".join(info["risks"]) or "None identified")
    st.write(f"**Compliance summary:** score {rec['compliance_score']:.0f}/100")
    st.write(f"**Financial summary:** stability score {rec['financial_stability_score']:.0f}/100")

    outranks = db.why_outranks_next(ranked_df, selected_id)
    if outranks:
        st.markdown("**Why this vendor outranks the next vendor:**")
        for line in outranks:
            st.markdown(f"- {line}")

    st.markdown("**Recommended actions:**")
    for action in info["due_diligence"]:
        st.markdown(f"- {action}")

    llm_text = generate_llm_narrative(vendor_row, drivers) if api_key_present else None
    st.markdown("##### Narrative")
    if llm_text:
        st.write(llm_text)
        st.caption("Generated by Claude.")
    else:
        st.write(generate_recommendation_text(vendor_row))
        if not api_key_present:
            st.caption("Rule-based explanation (no Claude API key configured).")

    if st.button("Download Vendor Summary PDF", icon=":material/download:"):
        pdf_bytes = reports.generate_vendor_summary_report(info)
        st.download_button("Save Vendor_Summary.pdf", pdf_bytes, file_name=f"{rec['vendor_id']}_summary.pdf", mime="application/pdf")
