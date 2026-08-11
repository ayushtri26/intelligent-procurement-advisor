"""Anomalies — the anomaly-flagged vendor list with per-vendor drivers,
pulled from the already-computed ranked_df (Isolation Forest output is
unchanged, see src/anomaly_detection.py)."""
import streamlit as st

from src import ui_components
from src.analytics_tools import FEATURE_LABELS
from src.anomaly_detection import get_anomaly_drivers

ranked_df = st.session_state.ranked_df

st.title("Anomalies")
st.caption("Vendors whose feature profile is statistically unusual relative to the rest of the evaluated pool.")

flagged = ranked_df[ranked_df["is_anomalous"] == True]  # noqa: E712

if flagged.empty:
    ui_components.empty_state("No anomalies detected", "No vendors are currently flagged as statistical outliers.")
else:
    st.warning(f"{len(flagged)} vendor(s) flagged as anomalous.")
    for _, row in flagged.sort_values("overall_score", ascending=False).iterrows():
        with st.container(border=True):
            c1, c2 = st.columns([2, 1])
            with c1:
                st.subheader(f"{row['vendor_name']} ({row['vendor_id']})")
                st.caption(f"Category: {row.get('category', 'N/A')} · Rank #{int(row['rank'])}")
            with c2:
                st.metric("Overall Score", f"{row['overall_score']:.1f} / 100")
                st.metric("Anomaly Score", f"{row['anomaly_score']:.3f}")

            drivers = get_anomaly_drivers(ranked_df, row["vendor_id"])
            st.markdown("**Driving factors:**")
            for d in drivers:
                st.markdown(
                    f"- **{FEATURE_LABELS.get(d['feature'], d['feature'])}**: {d['value']} vs peer avg "
                    f"{d['peer_average']} ({d['direction']} average, z={d['z_score']})"
                )
            st.caption("An anomaly flag is a prompt to investigate, not a verdict — verify the underlying data before excluding or shortlisting this vendor.")
