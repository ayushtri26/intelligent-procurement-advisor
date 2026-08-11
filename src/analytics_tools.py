"""Deterministic vendor analytics.

Every function here computes facts directly from the vendor dataframe using
plain pandas — no LLM involved. This is intentional: the assistant's LLM
layer (src/llm_service.py) is only ever allowed to *narrate* results that
were already computed here, never to calculate them itself.
"""
from __future__ import annotations

import pandas as pd

from src.anomaly_detection import get_anomaly_drivers
from src.feature_engineering import FEATURE_COLUMNS
from src.vendor_scoring import compute_overall_score, rank_vendors

FEATURE_LABELS = {
    "price_competitiveness": "Price Competitiveness",
    "delivery_reliability": "Delivery Reliability",
    "quality_score": "Quality",
    "compliance_score": "Compliance",
    "experience_score": "Experience",
    "financial_stability_score": "Financial Stability",
}

STRENGTH_THRESHOLD = 75
RISK_THRESHOLD = 55
COMPLIANCE_RISK_THRESHOLD = 60
LOW_COMPLIANCE_FOR_CONFIDENCE = 55
LOW_FINANCIAL_THRESHOLD = 60
LOW_EXPERIENCE_THRESHOLD = 50
CLOSE_GAP_THRESHOLD = 3.0
MODERATE_GAP_THRESHOLD = 8.0

QUALITY_COMPOSITE_COLUMNS = [
    "delivery_reliability",
    "quality_score",
    "compliance_score",
    "experience_score",
    "financial_stability_score",
]
SAFETY_COLUMNS = ["compliance_score", "financial_stability_score", "quality_score"]


# --------------------------------------------------------------------------
# Row-level building blocks
# --------------------------------------------------------------------------

def get_strengths_and_risks(vendor_row: pd.Series) -> tuple[list[str], list[str]]:
    strengths, risks = [], []
    for feature in FEATURE_COLUMNS:
        if feature not in vendor_row.index:
            continue
        value = vendor_row[feature]
        if pd.isna(value):
            continue
        label = FEATURE_LABELS[feature]
        if value >= STRENGTH_THRESHOLD:
            strengths.append(f"{label} ({value:.0f}/100)")
        elif value < RISK_THRESHOLD:
            risks.append(f"{label} ({value:.0f}/100)")
    if bool(vendor_row.get("is_anomalous", False)):
        risks.insert(0, "Flagged as a statistical outlier vs. peer vendors")
    return strengths, risks


def get_recommendation_label(overall_score: float, is_anomalous: bool) -> tuple[str, str]:
    """Return (label, css-ish tone) for the recommendation banner."""
    if is_anomalous:
        return "Review Required — Anomaly Detected", "warning"
    if overall_score >= 80:
        return "Recommended for Shortlist", "success"
    if overall_score >= 60:
        return "Acceptable with Conditions", "info"
    return "Not Recommended", "error"


def add_recommendation_categories(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["recommendation_category"] = df.apply(
        lambda r: get_recommendation_label(r.get("overall_score", 0.0), bool(r.get("is_anomalous", False)))[0],
        axis=1,
    )
    return df


def vendor_record(row: pd.Series) -> dict:
    """Compact, JSON-safe record with every field the assistant is expected to report."""
    return {
        "vendor_id": row.get("vendor_id"),
        "vendor_name": row.get("vendor_name"),
        "category": row.get("category"),
        "rank": int(row["rank"]) if "rank" in row.index and pd.notna(row.get("rank")) else None,
        "overall_score": _safe_round(row.get("overall_score")),
        "price_score": _safe_round(row.get("price_competitiveness")),
        "delivery_score": _safe_round(row.get("delivery_reliability")),
        "quality_score": _safe_round(row.get("quality_score")),
        "compliance_score": _safe_round(row.get("compliance_score")),
        "experience_score": _safe_round(row.get("experience_score")),
        "financial_stability_score": _safe_round(row.get("financial_stability_score")),
        "is_anomalous": bool(row.get("is_anomalous", False)),
        "anomaly_score": _safe_round(row.get("anomaly_score"), 3),
        "recommendation_category": row.get("recommendation_category"),
        "had_missing_data": bool(row.get("had_missing_data", False)),
    }


def _safe_round(value, ndigits: int = 1):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return None


def classify_confidence(candidate_row: pd.Series, runner_up_score: float | None) -> str:
    """High / Medium / Low per the product's confidence rubric."""
    anomaly = bool(candidate_row.get("is_anomalous", False))
    compliance_issue = candidate_row.get("compliance_score", 100) < LOW_COMPLIANCE_FOR_CONFIDENCE
    missing_data = bool(candidate_row.get("had_missing_data", False))
    candidate_score = candidate_row.get("overall_score", 0.0)
    gap = candidate_score - runner_up_score if runner_up_score is not None else 100.0

    if anomaly or compliance_issue or missing_data:
        return "Low"
    if gap < CLOSE_GAP_THRESHOLD:
        return "Low"
    if gap < MODERATE_GAP_THRESHOLD:
        return "Medium"
    return "High"


def build_due_diligence_checklist(row: pd.Series) -> list[str]:
    checks = []
    if bool(row.get("is_anomalous", False)):
        checks.append("Independently verify pricing and delivery history; request recent client references.")
    if row.get("compliance_score", 100) < COMPLIANCE_RISK_THRESHOLD:
        checks.append("Request updated compliance certifications and review the compliance-violation history.")
    if row.get("financial_stability_score", 100) < LOW_FINANCIAL_THRESHOLD:
        checks.append("Request recent financial statements or a credit report to confirm solvency.")
    if row.get("experience_score", 100) < LOW_EXPERIENCE_THRESHOLD:
        checks.append("Check references for comparable past contracts given the vendor's limited track record.")
    if bool(row.get("had_missing_data", False)):
        checks.append("Source data for this vendor had missing fields (imputed) — confirm the real values before relying on this score.")
    checks.append("Confirm final pricing and contract terms directly with the vendor before commitment.")
    return checks


def build_trade_offs(candidate_row: pd.Series, comparison_row: pd.Series) -> list[str]:
    if candidate_row.get("vendor_id") == comparison_row.get("vendor_id"):
        return []
    trade_offs = []
    for feature in FEATURE_COLUMNS:
        cand_val = candidate_row.get(feature)
        comp_val = comparison_row.get(feature)
        if cand_val is None or comp_val is None or pd.isna(cand_val) or pd.isna(comp_val):
            continue
        if cand_val < comp_val - 5:
            trade_offs.append(
                f"Lower {FEATURE_LABELS[feature]} than {comparison_row.get('vendor_name')} "
                f"({cand_val:.0f} vs {comp_val:.0f})."
            )
    return trade_offs


def build_recommendation_bundle(df: pd.DataFrame, candidate_row: pd.Series, rationale: str) -> dict:
    """The single point that assembles a *full* recommendation — never just a top score.

    Always includes: recommended vendor, reasons, trade-offs, anomaly status, confidence,
    due-diligence checks, and a human-approval reminder.
    """
    strengths, risks = get_strengths_and_risks(candidate_row)
    sorted_df = df.sort_values("overall_score", ascending=False).reset_index(drop=True)
    others = sorted_df[sorted_df["vendor_id"] != candidate_row.get("vendor_id")]
    runner_up = others.iloc[0] if not others.empty else candidate_row
    runner_up_score = runner_up.get("overall_score") if not others.empty else None
    confidence = classify_confidence(candidate_row, runner_up_score)
    label, _tone = get_recommendation_label(candidate_row.get("overall_score", 0.0), bool(candidate_row.get("is_anomalous", False)))

    return {
        "recommended_vendor": vendor_record(candidate_row),
        "rationale": rationale,
        "key_reasons": strengths or ["No feature scored above the strength threshold — this is the strongest available option."],
        "risks": risks,
        "trade_offs": build_trade_offs(candidate_row, runner_up),
        "is_anomalous": bool(candidate_row.get("is_anomalous", False)),
        "confidence": confidence,
        "due_diligence": build_due_diligence_checklist(candidate_row),
        "recommendation_category": label,
        "requires_human_approval": True,
        "had_missing_data": bool(candidate_row.get("had_missing_data", False)),
    }


def build_executive_summary(df: pd.DataFrame) -> dict:
    top = df.sort_values("overall_score", ascending=False).iloc[0]
    rec_bundle = build_recommendation_bundle(df, top, "Highest overall weighted score across all evaluation criteria.")
    anomalous = df[df.get("is_anomalous", False) == True]  # noqa: E712
    compliance_risks = get_compliance_risks(df)
    return {
        "vendor_count": len(df),
        "recommended_vendor": rec_bundle["recommended_vendor"],
        "confidence": rec_bundle["confidence"],
        "rationale": rec_bundle["rationale"],
        "key_reasons": rec_bundle["key_reasons"],
        "risks": rec_bundle["risks"],
        "trade_offs": rec_bundle["trade_offs"],
        "due_diligence": rec_bundle["due_diligence"],
        "anomalous_count": int(len(anomalous)),
        "anomalous_vendors": [vendor_record(r) for _, r in anomalous.iterrows()],
        "compliance_risk_count": int(len(compliance_risks)),
        "requires_human_approval": True,
    }


# --------------------------------------------------------------------------
# Named analytics functions
# --------------------------------------------------------------------------

def get_top_vendors(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    n = max(1, min(int(n), len(df)))
    return df.sort_values("overall_score", ascending=False).head(n).reset_index(drop=True)


def get_cheapest_qualified_vendor(df: pd.DataFrame, min_overall_score: float = 60.0) -> tuple[pd.Series, bool]:
    """Cheapest vendor that also clears a minimum quality bar and isn't anomalous.

    Returns (row, fallback_used). fallback_used is True when no vendor met the bar and
    the result had to widen to a less-qualified pool — callers should surface this.
    """
    anomalous_mask = df.get("is_anomalous", pd.Series(False, index=df.index)).astype(bool)
    qualified = df[(df["overall_score"] >= min_overall_score) & (~anomalous_mask)]
    fallback_used = False
    if qualified.empty:
        qualified = df[~anomalous_mask]
        fallback_used = True
    if qualified.empty:
        qualified = df
        fallback_used = True

    if "quoted_price" in qualified.columns and qualified["quoted_price"].notna().any():
        best = qualified.sort_values("quoted_price", ascending=True).iloc[0]
    else:
        best = qualified.sort_values("price_competitiveness", ascending=False).iloc[0]
    return best, fallback_used


def get_safest_vendor(df: pd.DataFrame) -> tuple[pd.Series, bool]:
    """Vendor with the strongest compliance/financial/quality profile, preferring non-anomalous."""
    candidates = df.copy()
    candidates["_safety_index"] = candidates[SAFETY_COLUMNS].mean(axis=1)
    anomalous_mask = candidates.get("is_anomalous", pd.Series(False, index=candidates.index)).astype(bool)
    non_anomalous = candidates[~anomalous_mask]
    pool = non_anomalous if not non_anomalous.empty else candidates
    fallback_used = non_anomalous.empty
    best = pool.sort_values("_safety_index", ascending=False).iloc[0]
    return best, fallback_used


def get_best_value_vendor(df: pd.DataFrame) -> tuple[pd.Series, bool]:
    """Best quality-delivered-per-dollar vendor, preferring non-anomalous."""
    candidates = df.copy()
    candidates["_quality_composite"] = candidates[QUALITY_COMPOSITE_COLUMNS].mean(axis=1)
    if "quoted_price" in candidates.columns and (candidates["quoted_price"] > 0).all():
        candidates["_value_index"] = candidates["_quality_composite"] / candidates["quoted_price"] * 1000
    else:
        candidates["_value_index"] = candidates["_quality_composite"] * (candidates["price_competitiveness"] / 100)
    anomalous_mask = candidates.get("is_anomalous", pd.Series(False, index=candidates.index)).astype(bool)
    non_anomalous = candidates[~anomalous_mask]
    pool = non_anomalous if not non_anomalous.empty else candidates
    fallback_used = non_anomalous.empty
    best = pool.sort_values("_value_index", ascending=False).iloc[0]
    return best, fallback_used


def compare_vendors(df: pd.DataFrame, vendor_ids: list[str]) -> pd.DataFrame:
    cols = ["vendor_id", "vendor_name", "category", "rank", "overall_score"] + FEATURE_COLUMNS + [
        "is_anomalous",
        "anomaly_score",
        "recommendation_category",
    ]
    cols = [c for c in cols if c in df.columns]
    rows = []
    for vid in vendor_ids:
        match = df[df["vendor_id"] == vid]
        if not match.empty:
            rows.append({c: match.iloc[0].get(c) for c in cols})
    return pd.DataFrame(rows)


def explain_vendor(df: pd.DataFrame, vendor_id: str) -> dict:
    match = df[df["vendor_id"] == vendor_id]
    if match.empty:
        return {"found": False, "vendor_id": vendor_id}
    row = match.iloc[0]
    strengths, risks = get_strengths_and_risks(row)
    sorted_df = df.sort_values("overall_score", ascending=False).reset_index(drop=True)
    others = sorted_df[sorted_df["vendor_id"] != vendor_id]
    runner_up = others.iloc[0] if not others.empty else row
    runner_up_score = runner_up.get("overall_score") if not others.empty else None
    label, _tone = get_recommendation_label(row.get("overall_score", 0.0), bool(row.get("is_anomalous", False)))
    return {
        "found": True,
        "record": vendor_record(row),
        "strengths": strengths,
        "risks": risks,
        "recommendation_category": label,
        "confidence": classify_confidence(row, runner_up_score),
        "due_diligence": build_due_diligence_checklist(row),
        "trade_offs": build_trade_offs(row, runner_up),
        "had_missing_data": bool(row.get("had_missing_data", False)),
    }


def explain_anomaly(df: pd.DataFrame, vendor_id: str) -> dict:
    match = df[df["vendor_id"] == vendor_id]
    if match.empty:
        return {"found": False, "vendor_id": vendor_id}
    row = match.iloc[0]
    is_anomalous = bool(row.get("is_anomalous", False))
    result = {
        "found": True,
        "vendor_id": vendor_id,
        "vendor_name": row.get("vendor_name"),
        "is_anomalous": is_anomalous,
    }
    if is_anomalous:
        result["drivers"] = get_anomaly_drivers(df, vendor_id)
        result["anomaly_score"] = _safe_round(row.get("anomaly_score"), 3)
    return result


def get_compliance_risks(df: pd.DataFrame, threshold: float = COMPLIANCE_RISK_THRESHOLD) -> pd.DataFrame:
    at_risk = df[df["compliance_score"] < threshold]
    cols = ["vendor_id", "vendor_name", "compliance_score", "compliance_violations", "is_anomalous"]
    cols = [c for c in cols if c in df.columns]
    return at_risk[cols].sort_values("compliance_score", ascending=True).reset_index(drop=True)


def run_weight_sensitivity(df: pd.DataFrame, adjusted_weights: dict[str, float]) -> dict:
    """Recompute scores/ranking under `adjusted_weights` and diff against the current ranking."""
    new_df = compute_overall_score(df, adjusted_weights)
    if "rank" in new_df.columns:
        new_df = new_df.drop(columns=["rank"])
    new_df = rank_vendors(new_df)

    old_ranks = df.set_index("vendor_id")["rank"] if "rank" in df.columns else None
    comparison = new_df[["vendor_id", "vendor_name", "rank", "overall_score"]].rename(
        columns={"rank": "new_rank", "overall_score": "new_score"}
    )
    if old_ranks is not None:
        comparison["old_rank"] = comparison["vendor_id"].map(old_ranks)
        comparison["rank_change"] = comparison["old_rank"] - comparison["new_rank"]
    comparison = comparison.sort_values("new_rank").reset_index(drop=True)

    top_before = df.sort_values("overall_score", ascending=False).iloc[0]["vendor_id"] if "overall_score" in df.columns else None
    top_after = new_df.iloc[0]["vendor_id"]

    return {
        "new_ranked_df": new_df,
        "comparison": comparison,
        "top_before": top_before,
        "top_after": top_after,
        "top_changed": top_before != top_after,
    }
