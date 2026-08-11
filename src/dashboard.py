"""Presentation-layer derived metrics for the executive dashboard.

Everything here is computed FROM the already-scored/ranked/anomaly-flagged
dataframe that src.vendor_scoring / src.anomaly_detection / src.analytics_tools
produce — this module adds no new scoring or anomaly-detection logic of its
own, it only summarizes, formats, and packages those existing results for
display (KPI cards, confidence %, risk level, dynamic insights, explainable
score bars, illustrative business-value estimates).

Every formula here is a simple, transparent, deterministic rule — documented
in each function's docstring — consistent with the project's "explainable,
deterministic, no hidden ML" principle for anything Claude might narrate.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.analytics_tools import (
    COMPLIANCE_RISK_THRESHOLD,
    FEATURE_LABELS,
    build_due_diligence_checklist,
    build_trade_offs,
    classify_confidence,
    get_compliance_risks,
    get_strengths_and_risks,
)
from src.feature_engineering import FEATURE_COLUMNS

# --------------------------------------------------------------------------
# Illustrative business-value assumptions — clearly surfaced as estimates,
# never presented as measured fact.
# --------------------------------------------------------------------------
MANUAL_MINUTES_PER_VENDOR = 8.0  # assumed manual review time per vendor, per tender
AI_ASSISTED_MINUTES = 20.0  # assumed total time to review the AI-assisted shortlist
ASSUMED_HOURLY_RATE_USD = 75.0
ILLUSTRATIVE_ACCURACY_IMPROVEMENT_PCT = 18  # illustrative: fewer risk indicators missed vs. manual spot-checks

# --------------------------------------------------------------------------
# Confidence & risk
# --------------------------------------------------------------------------

def compute_confidence(ranked_df: pd.DataFrame) -> float:
    """Overall procurement confidence (0-100) in the top-ranked vendor.

    Deterministic weighted formula, transparent by design:
      - up to 40 pts for how far the #1 vendor's score leads the #2 vendor
        (a 15+ point gap earns the full 40)
      - up to 30 pts scaled from the #1 vendor's compliance score
      - 30 pts if the #1 vendor is not anomaly-flagged, 0 if it is
    """
    if ranked_df.empty:
        return 0.0
    sorted_df = ranked_df.sort_values("overall_score", ascending=False).reset_index(drop=True)
    top = sorted_df.iloc[0]
    runner_up_score = sorted_df.iloc[1]["overall_score"] if len(sorted_df) > 1 else top["overall_score"]
    gap = max(0.0, float(top["overall_score"]) - float(runner_up_score))

    gap_component = min(gap / 15.0, 1.0) * 40.0
    compliance_component = (float(top.get("compliance_score", 0)) / 100.0) * 30.0
    anomaly_component = 0.0 if bool(top.get("is_anomalous", False)) else 30.0

    return round(gap_component + compliance_component + anomaly_component, 1)


def compute_risk_level(ranked_df: pd.DataFrame) -> tuple[str, str]:
    """Overall procurement risk level (Low/Medium/High) + a badge tone
    (success/warning/danger — see src/ui_components.status_badge).

    Deterministic point system: anomaly count, average compliance, and
    average quality across all evaluated vendors each contribute 0-2 points;
    4+ => High, 2-3 => Medium, 0-1 => Low.
    """
    if ranked_df.empty:
        return "Low", "success"
    anomaly_count = int(ranked_df.get("is_anomalous", pd.Series(dtype=bool)).sum())
    avg_compliance = float(ranked_df["compliance_score"].mean())
    avg_quality = float(ranked_df["quality_score"].mean())

    points = 0
    points += 2 if anomaly_count >= 3 else (1 if anomaly_count >= 1 else 0)
    points += 2 if avg_compliance < 60 else (1 if avg_compliance < 75 else 0)
    points += 2 if avg_quality < 60 else (1 if avg_quality < 75 else 0)

    if points >= 4:
        return "High", "danger"
    if points >= 2:
        return "Medium", "warning"
    return "Low", "success"


def compute_business_value(ranked_df: pd.DataFrame) -> dict:
    """Illustrative time/cost-saving estimates — NOT measured, clearly labeled."""
    n = max(1, len(ranked_df))
    manual_minutes = MANUAL_MINUTES_PER_VENDOR * n
    manual_hours = manual_minutes / 60.0
    ai_minutes = AI_ASSISTED_MINUTES
    reduction_pct = round((manual_minutes - ai_minutes) / manual_minutes * 100, 1) if manual_minutes else 0.0
    hours_saved = round((manual_minutes - ai_minutes) / 60.0, 1)
    cost_saving = round(hours_saved * ASSUMED_HOURLY_RATE_USD, 0)
    return {
        "manual_hours": round(manual_hours, 1),
        "manual_minutes": round(manual_minutes, 0),
        "ai_minutes": ai_minutes,
        "reduction_pct": reduction_pct,
        "hours_saved": hours_saved,
        "cost_saving_usd": cost_saving,
        "accuracy_improvement_pct": ILLUSTRATIVE_ACCURACY_IMPROVEMENT_PCT,
    }


def compute_kpis(ranked_df: pd.DataFrame) -> dict:
    """All figures for the top-of-page executive KPI cards."""
    top = ranked_df.sort_values("overall_score", ascending=False).iloc[0]
    anomalous_mask = ranked_df.get("is_anomalous", pd.Series(False, index=ranked_df.index)).astype(bool)
    qualified = ranked_df[(ranked_df["overall_score"] >= 60) & (~anomalous_mask)]
    confidence = compute_confidence(ranked_df)
    risk_level, risk_tone = compute_risk_level(ranked_df)
    business_value = compute_business_value(ranked_df)

    return {
        "recommended_vendor_name": top["vendor_name"],
        "recommended_vendor_id": top["vendor_id"],
        "confidence": confidence,
        "vendors_evaluated": len(ranked_df),
        "qualified_vendors": len(qualified),
        "anomalous_count": int(anomalous_mask.sum()),
        "risk_level": risk_level,
        "risk_tone": risk_tone,
        "business_value": business_value,
    }


# --------------------------------------------------------------------------
# Explainability helpers
# --------------------------------------------------------------------------

def build_score_contribution(vendor_row: pd.Series, weights: dict[str, float]) -> list[dict]:
    """Per-feature {label, score, weight, contribution, bar_fraction} for bar-chart rendering."""
    total_weight = sum(weights.values()) or 1.0
    rows = []
    for feature in FEATURE_COLUMNS:
        score = float(vendor_row.get(feature, 0.0) or 0.0)
        weight = weights.get(feature, 0.0) / total_weight
        rows.append(
            {
                "feature": feature,
                "label": FEATURE_LABELS[feature],
                "score": round(score, 1),
                "weight_pct": round(weight * 100, 1),
                "contribution": round(score * weight, 1),
            }
        )
    return rows


def build_advantages(candidate_row: pd.Series, comparison_row: pd.Series) -> list[str]:
    """The mirror of analytics_tools.build_trade_offs: where the candidate is meaningfully AHEAD."""
    if candidate_row.get("vendor_id") == comparison_row.get("vendor_id"):
        return []
    advantages = []
    for feature in FEATURE_COLUMNS:
        cand_val = candidate_row.get(feature)
        comp_val = comparison_row.get(feature)
        if cand_val is None or comp_val is None or pd.isna(cand_val) or pd.isna(comp_val):
            continue
        if cand_val > comp_val + 5:
            advantages.append(f"Higher {FEATURE_LABELS[feature]} than {comparison_row.get('vendor_name')} ({cand_val:.0f} vs {comp_val:.0f}).")
    return advantages


def why_outranks_next(ranked_df: pd.DataFrame, vendor_id: str) -> list[str]:
    """Why the given vendor outranks the next-best alternative, in plain terms."""
    sorted_df = ranked_df.sort_values("overall_score", ascending=False).reset_index(drop=True)
    match = sorted_df[sorted_df["vendor_id"] == vendor_id]
    if match.empty:
        return []
    idx = match.index[0]
    if idx + 1 >= len(sorted_df):
        return ["This vendor is the only one remaining after filtering — no direct runner-up to compare against."]
    candidate = sorted_df.iloc[idx]
    runner_up = sorted_df.iloc[idx + 1]
    advantages = build_advantages(candidate, runner_up)
    gap = round(float(candidate["overall_score"]) - float(runner_up["overall_score"]), 1)
    lines = [f"Leads {runner_up['vendor_name']} (rank #{int(runner_up['rank'])}) by {gap} overall points."]
    lines.extend(advantages)
    return lines


# --------------------------------------------------------------------------
# Dynamic procurement insights (template-based, fully deterministic — no LLM)
# --------------------------------------------------------------------------

def generate_insights(ranked_df: pd.DataFrame, max_insights: int = 8) -> list[str]:
    insights: list[str] = []
    if ranked_df.empty:
        return insights

    n = len(ranked_df)
    compliant = ranked_df[ranked_df["compliance_score"] >= COMPLIANCE_RISK_THRESHOLD]
    insights.append(f"{len(compliant)} of {n} vendors meet or exceed the compliance threshold ({COMPLIANCE_RISK_THRESHOLD}/100).")

    avg_quality = ranked_df["quality_score"].mean()
    insights.append(f"Average vendor quality score is {avg_quality:.0f}/100 across all evaluated vendors.")

    if "category" in ranked_df.columns and ranked_df["category"].nunique() > 1:
        by_category = ranked_df.groupby("category")["overall_score"].mean().sort_values(ascending=False)
        if len(by_category) >= 2:
            best_cat, worst_cat = by_category.index[0], by_category.index[-1]
            if best_cat != worst_cat:
                insights.append(
                    f"{best_cat} vendors outperform {worst_cat} vendors on average "
                    f"({by_category.iloc[0]:.0f} vs {by_category.iloc[-1]:.0f} overall score)."
                )

    anomalous = ranked_df[ranked_df.get("is_anomalous", False) == True]  # noqa: E712
    if not anomalous.empty:
        worst_compliance = anomalous.sort_values("compliance_score").iloc[0]
        insights.append(
            f"Vendor {worst_compliance['vendor_name']} ({worst_compliance['vendor_id']}) has unusually low "
            f"compliance ({worst_compliance['compliance_score']:.0f}/100) among flagged vendors."
        )
    else:
        insights.append("No vendors are currently flagged as statistical anomalies.")

    std_by_feature = ranked_df[FEATURE_COLUMNS].std().sort_values(ascending=False)
    if not std_by_feature.empty:
        strongest_differentiator = FEATURE_LABELS[std_by_feature.index[0]]
        insights.append(f"{strongest_differentiator} shows the widest spread between vendors — it is currently the strongest differentiator.")

    mean_by_feature = ranked_df[FEATURE_COLUMNS].mean().sort_values(ascending=False)
    if not mean_by_feature.empty:
        insights.append(f"{FEATURE_LABELS[mean_by_feature.index[0]]} is, on average, the highest-scoring criterion across all vendors.")

    top = ranked_df.sort_values("overall_score", ascending=False).iloc[0]
    strengths, _risks = get_strengths_and_risks(top)
    if strengths:
        insights.append(f"The top-ranked vendor's strongest attribute is {strengths[0].split(' (')[0]}.")

    compliance_risks = get_compliance_risks(ranked_df)
    if not compliance_risks.empty:
        insights.append(f"{len(compliance_risks)} vendor(s) fall below the compliance risk threshold and warrant closer review.")

    return insights[:max_insights]


# --------------------------------------------------------------------------
# Knowledge base summary (for the RAG status page — reads KnowledgeBase, no writes)
# --------------------------------------------------------------------------

def summarize_knowledge_base(kb) -> pd.DataFrame:
    """One row per indexed document: filename, chunk count, pages covered."""
    if not kb.chunks:
        return pd.DataFrame(columns=["Document", "Chunks", "Pages"])
    rows = {}
    for chunk in kb.chunks:
        entry = rows.setdefault(chunk.filename, {"Document": chunk.filename, "Chunks": 0, "pages": set()})
        entry["Chunks"] += 1
        if chunk.page is not None:
            entry["pages"].add(chunk.page)
    records = []
    for entry in rows.values():
        pages = sorted(entry["pages"])
        records.append(
            {
                "Document": entry["Document"],
                "Chunks": entry["Chunks"],
                "Pages": f"{len(pages)} page(s)" if pages else "N/A",
            }
        )
    return pd.DataFrame(records)


# --------------------------------------------------------------------------
# Risk matrix (Likelihood vs. Impact) — a simple, documented proxy built
# entirely from existing feature scores, not a new model.
# --------------------------------------------------------------------------

def build_risk_matrix(ranked_df: pd.DataFrame) -> pd.DataFrame:
    """Likelihood = 100 - compliance_score (weaker compliance -> more likely an issue surfaces).
    Impact = 100 - financial_stability_score (weaker financial footing -> costlier if it does)."""
    matrix = ranked_df[["vendor_id", "vendor_name", "compliance_score", "financial_stability_score", "is_anomalous", "overall_score"]].copy()
    matrix["likelihood"] = (100 - matrix["compliance_score"]).round(1)
    matrix["impact"] = (100 - matrix["financial_stability_score"]).round(1)
    return matrix


# --------------------------------------------------------------------------
# Dashboard donut cards — simple re-groupings of columns already computed by
# src.analytics_tools (recommendation_category, is_anomalous). No new model.
# --------------------------------------------------------------------------

_EVALUATION_ORDER = [
    "Recommended for Shortlist",
    "Acceptable with Conditions",
    "Not Recommended",
    "Review Required — Anomaly Detected",
]


def build_evaluation_overview(ranked_df: pd.DataFrame) -> dict[str, int]:
    """Vendor count per recommendation category, for the dashboard's
    'Procurement Overview' donut."""
    counts = ranked_df["recommendation_category"].value_counts()
    return {label: int(counts.get(label, 0)) for label in _EVALUATION_ORDER if counts.get(label, 0) > 0}


def build_risk_distribution(ranked_df: pd.DataFrame) -> dict[str, int]:
    """Low/Medium/High risk vendor counts, derived from the same
    recommendation category + anomaly flag already computed per vendor."""

    def _bucket(row) -> str:
        if row.get("is_anomalous"):
            return "High"
        if row.get("recommendation_category") == "Recommended for Shortlist":
            return "Low"
        if row.get("recommendation_category") == "Acceptable with Conditions":
            return "Medium"
        return "High"

    counts = ranked_df.apply(_bucket, axis=1).value_counts()
    return {level: int(counts.get(level, 0)) for level in ["Low", "Medium", "High"]}


def build_kpi_sparklines(ranked_df: pd.DataFrame, kpis: dict) -> dict[str, list[float]]:
    """Small illustrative trend series for the dashboard KPI cards — each is
    derived from real already-computed values (score distribution, business
    value estimate), never randomly fabricated."""
    scores_desc = ranked_df.sort_values("overall_score", ascending=False)["overall_score"].tolist()
    anomaly_asc = ranked_df.sort_values("anomaly_score")["anomaly_score"].tolist()
    bv = kpis["business_value"]
    return {
        "confidence": scores_desc[:10] or [0],
        "vendors": list(range(1, min(len(ranked_df), 10) + 1)) or [0],
        "risk": [round(-v * 100, 2) for v in anomaly_asc[:10]] or [0],
        "decision_time": [bv["manual_minutes"], (bv["manual_minutes"] + bv["ai_minutes"]) / 2, bv["ai_minutes"]],
    }


def relative_time(timestamp_str: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' -> a short 'x min ago' label for the activity feed."""
    try:
        ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(timestamp_str)
    seconds = int((datetime.now() - ts).total_seconds())
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hr{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"
