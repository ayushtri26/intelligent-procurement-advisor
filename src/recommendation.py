"""Per-vendor recommendation narrative for the Step 4 "Vendor Detail" panel.

Thin wrapper around src.analytics_tools (facts) and src.llm_service (optional
narration). The chat assistant lives in src.procurement_assistant — this
module only covers the single-vendor detail view.
"""
from __future__ import annotations

import pandas as pd

from src import llm_service
from src.analytics_tools import (  # noqa: F401 (re-exported for app.py)
    FEATURE_LABELS,
    get_recommendation_label,
    get_strengths_and_risks,
)
from src.llm_service import get_api_key  # noqa: F401 (re-exported for app.py)


def generate_recommendation_text(vendor_row: pd.Series) -> str:
    overall_score = vendor_row["overall_score"]
    is_anomalous = bool(vendor_row.get("is_anomalous", False))
    strengths, risks = get_strengths_and_risks(vendor_row)
    label, _ = get_recommendation_label(overall_score, is_anomalous)

    parts = [f"**{vendor_row['vendor_name']}** scores **{overall_score:.1f}/100** overall. Recommendation: **{label}**."]
    if strengths:
        parts.append("Strong on: " + ", ".join(strengths) + ".")
    if risks:
        parts.append("Watch out for: " + ", ".join(risks) + ".")
    if is_anomalous:
        parts.append(
            "This vendor's feature profile differs significantly from its peers — "
            "verify the underlying data and conduct additional due diligence before proceeding."
        )
    return " ".join(parts)


def generate_llm_narrative(vendor_row: pd.Series, drivers: list[dict], api_key: str | None = None) -> str | None:
    """Best-effort natural-language elaboration of the rule-based recommendation. Returns None on any failure."""
    strengths, risks = get_strengths_and_risks(vendor_row)
    driver_text = "; ".join(
        f"{FEATURE_LABELS.get(d['feature'], d['feature'])} is {d['direction']} peer average "
        f"({d['value']} vs {d['peer_average']} avg, z={d['z_score']})"
        for d in drivers
    )
    prompt = (
        "You are a procurement analyst assistant. Write a concise (3-4 sentence) evaluation "
        "narrative for the vendor below, grounded ONLY in the data provided. Do not invent facts.\n\n"
        f"Vendor: {vendor_row['vendor_name']} ({vendor_row.get('category', 'N/A')})\n"
        f"Overall score: {vendor_row['overall_score']}/100\n"
        f"Anomaly flagged: {bool(vendor_row.get('is_anomalous', False))}\n"
        f"Anomaly drivers: {driver_text or 'none'}\n"
        f"Strengths: {', '.join(strengths) or 'none'}\n"
        f"Risks: {', '.join(risks) or 'none'}\n"
    )
    return llm_service.narrate(prompt, api_key=api_key, max_tokens=300)
