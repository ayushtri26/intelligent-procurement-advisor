"""Centralized, tender-aware vendor recommendation service.

This is the single source of truth for "which vendor is recommended" —
every page (Dashboard, Recommendations, Vendor Analytics, AI Assistant,
Tenders) must read `build_recommendation()`'s output rather than computing
its own answer. It deliberately does NOT touch src.vendor_scoring,
src.anomaly_detection, or src.feature_engineering — those still produce the
generic, tender-agnostic `overall_score`/`is_anomalous` columns exactly as
before. This module adds a tender-specific layer on top:

    ranked_df (generic scores, unchanged)
        -> filter to the tender's eligible vendor category
        -> eligibility check (Qualified / Conditionally Qualified / Disqualified)
        -> tender-specific dimension scoring (technical compliance, tender-
           relative price, delivery, past performance, warranty, risk)
        -> weighted final_score using the tender's own evaluation_criteria
        -> rank, pick #1, generate explanations from the real deltas

Nothing here is cached (no st.cache_data) — it is cheap to recompute and
must never go stale when selected_tender_id changes, which is the whole
point: call build_recommendation(ranked_df, tender_id) fresh on every rerun.
"""
from __future__ import annotations

import pandas as pd

from src.tender_repository import get_tender_or_default as get_tender

DIMENSION_LABELS = {
    "technical_compliance": "Technical Compliance",
    "price": "Price",
    "delivery": "Delivery",
    "past_performance": "Past Performance",
    "warranty": "Warranty / Service",
    "risk": "Risk",
}


# --------------------------------------------------------------------------
# Eligibility layer
# --------------------------------------------------------------------------

def compute_eligibility(pool_df: pd.DataFrame, tender: dict) -> pd.DataFrame:
    """Tag every vendor in the category-matched pool Qualified / Conditionally
    Qualified / Disqualified against the tender's mandatory requirements."""
    df = pool_df.copy()
    statuses, notes = [], []

    for _, row in df.iterrows():
        row_notes: list[str] = []
        disqualified = False
        conditional = False

        certs = row.get("certifications_count", 0) or 0
        if certs < tender["min_certifications"]:
            disqualified = True
            row_notes.append(f"Below minimum certifications ({int(certs)} < {tender['min_certifications']})")

        quality = row.get("quality_rating", 0) or 0
        if quality < tender["min_quality_rating"] - 1.5:
            disqualified = True
            row_notes.append(f"Quality rating well below tender minimum ({quality:.1f} < {tender['min_quality_rating']})")
        elif quality < tender["min_quality_rating"]:
            conditional = True
            row_notes.append(f"Quality rating slightly below tender minimum ({quality:.1f} < {tender['min_quality_rating']})")

        violations = row.get("compliance_violations", 0) or 0
        if violations >= 2:
            disqualified = True
            row_notes.append(f"{int(violations)} compliance violations on record")
        elif violations == 1:
            conditional = True
            row_notes.append("One compliance violation on record")

        if bool(row.get("is_anomalous", False)):
            conditional = True
            row_notes.append("Flagged as a statistical anomaly — requires review")

        if disqualified:
            statuses.append("Disqualified")
        elif conditional:
            statuses.append("Conditionally Qualified")
        else:
            statuses.append("Qualified")
        notes.append(row_notes)

    df["eligibility_status"] = statuses
    df["eligibility_notes"] = notes
    return df


# --------------------------------------------------------------------------
# Tender-specific dimension scoring
# --------------------------------------------------------------------------

def _technical_compliance_score(row: pd.Series, tender: dict) -> float:
    cert_ratio = min(row.get("certifications_count", 0) / max(tender["min_certifications"], 1), 1.5) / 1.5 * 100
    quality_ratio = min(row.get("quality_rating", 0) / max(tender["min_quality_rating"], 1), 1.3) / 1.3 * 100
    return round(min(cert_ratio, 100) * 0.5 + min(quality_ratio, 100) * 0.5, 1)


def _tender_price_score(row: pd.Series, tender: dict) -> float:
    """Mirrors src.feature_engineering.price_competitiveness's formula shape,
    but relative to the TENDER's budget rather than the vendor's own
    market-average price — this is what makes price tender-specific."""
    budget = tender.get("budget") or row.get("quoted_price", 0) or 1
    ratio_diff = (budget - row.get("quoted_price", 0)) / budget
    return round(min(max(ratio_diff * 100 + 50, 0), 100), 1)


def _warranty_score(row: pd.Series) -> float:
    cert_component = min(row.get("certifications_count", 0) / 5, 1) * 100
    defect_component = (1 - min(row.get("defect_rate", 0) or 0, 1)) * 100
    return round(cert_component * 0.5 + defect_component * 0.5, 1)


def _risk_score(row: pd.Series) -> float:
    """Higher = lower risk (so it combines the same way as every other
    dimension: higher score * weight = more points)."""
    penalty = 0.0
    if bool(row.get("is_anomalous", False)):
        penalty += 40
    penalty += min(row.get("compliance_violations", 0) or 0, 3) * 15
    return round(max(0.0, 100 - penalty), 1)


def compute_tender_scores(df: pd.DataFrame, tender: dict) -> pd.DataFrame:
    """Add the six tender-specific dimension scores plus the weighted
    `final_score`, using the tender's own evaluation_criteria weights."""
    df = df.copy()
    df["technical_compliance_score"] = df.apply(lambda r: _technical_compliance_score(r, tender), axis=1)
    df["tender_price_score"] = df.apply(lambda r: _tender_price_score(r, tender), axis=1)
    df["delivery_score"] = df["delivery_reliability"]
    df["past_performance_score"] = df["experience_score"]
    df["warranty_score"] = df.apply(_warranty_score, axis=1)
    df["risk_score"] = df.apply(_risk_score, axis=1)

    weights = tender["evaluation_criteria"]
    total_weight = sum(weights.values()) or 1.0
    dim_columns = {
        "technical_compliance": "technical_compliance_score",
        "price": "tender_price_score",
        "delivery": "delivery_score",
        "past_performance": "past_performance_score",
        "warranty": "warranty_score",
        "risk": "risk_score",
    }
    df["final_score"] = 0.0
    for dim, col in dim_columns.items():
        df["final_score"] += df[col] * (weights.get(dim, 0) / total_weight)
    df["final_score"] = df["final_score"].round(1)
    return df


# --------------------------------------------------------------------------
# Explanations
# --------------------------------------------------------------------------

def _generate_explanations(top: pd.Series, viable_df: pd.DataFrame, tender: dict) -> tuple[list[str], list[str]]:
    strengths: list[str] = []
    risks: list[str] = []

    if top["eligibility_status"] == "Qualified":
        strengths.append("Meets all mandatory tender specifications")
    else:
        risks.append("Conditionally qualified — " + "; ".join(top["eligibility_notes"] or ["review required"]))

    budget = tender.get("budget")
    if budget:
        delta_pct = (budget - top["quoted_price"]) / budget * 100
        if delta_pct > 0.05:
            strengths.append(f"Bid is {delta_pct:.1f}% below tender budget")
        elif delta_pct < -0.05:
            risks.append(f"Bid is {abs(delta_pct):.1f}% above tender budget")

    otd = top.get("on_time_delivery_rate")
    if pd.notna(otd):
        strengths.append(f"{otd * 100:.0f}% historical on-time delivery")

    if top["past_performance_score"] >= 70:
        strengths.append("Strong past performance track record")

    if top.get("certifications_count", 0) >= tender["min_certifications"]:
        strengths.append("Mandatory certification requirements verified")
    else:
        risks.append("Does not fully meet mandatory certification requirements")

    cheapest = viable_df.sort_values("quoted_price", ascending=True).iloc[0]
    if cheapest["vendor_id"] != top["vendor_id"]:
        higher_pct = (top["quoted_price"] - cheapest["quoted_price"]) / cheapest["quoted_price"] * 100
        risks.append(f"Bid is {higher_pct:.1f}% higher than the lowest compliant bidder ({cheapest['vendor_name']})")

    if bool(top.get("is_anomalous", False)):
        risks.append("Flagged as a statistical anomaly — verify independently before proceeding")

    return strengths, risks


def _score_breakdown(top: pd.Series, tender: dict) -> dict:
    weights = tender["evaluation_criteria"]
    total_weight = sum(weights.values()) or 1.0
    raw_by_dim = {
        "technical_compliance": top["technical_compliance_score"],
        "price": top["tender_price_score"],
        "delivery": top["delivery_score"],
        "past_performance": top["past_performance_score"],
        "warranty": top["warranty_score"],
        "risk": top["risk_score"],
    }
    breakdown: dict[str, dict] = {}
    total_points, total_max = 0.0, 0.0
    for dim, raw_score in raw_by_dim.items():
        w = weights.get(dim, 0) / total_weight
        max_points = round(w * 100, 1)
        points = round(raw_score * w, 1)
        breakdown[DIMENSION_LABELS[dim]] = {"points": points, "max": max_points}
        total_points += points
        total_max += max_points
    breakdown["Total"] = {"points": round(total_points, 1), "max": round(total_max, 1)}
    return breakdown


def _requirement_match_pct(row: pd.Series, tender: dict) -> float:
    """Continuous 0-100 'how close is this vendor to meeting the mandatory
    requirements' score — used only for the closest-matches fallback when
    no vendor is fully eligible, never for ranking a real recommendation."""
    cert_component = min(row.get("certifications_count", 0) / max(tender["min_certifications"], 1), 1.0)
    quality_component = min(row.get("quality_rating", 0) / max(tender["min_quality_rating"], 1), 1.0)
    violation_component = max(0.0, 1 - (row.get("compliance_violations", 0) or 0) / 2)
    return round((cert_component + quality_component + violation_component) / 3 * 100, 1)


def _closest_matches(pool: pd.DataFrame, tender: dict, top_n: int = 3) -> list[dict]:
    scored = pool.copy()
    scored["match_pct"] = scored.apply(lambda r: _requirement_match_pct(r, tender), axis=1)
    top = scored.sort_values("match_pct", ascending=False).head(top_n)
    return [
        {"vendor_id": r["vendor_id"], "vendor_name": r["vendor_name"], "match_pct": r["match_pct"]}
        for _, r in top.iterrows()
    ]


def _confidence(top: pd.Series, runner_up: pd.Series | None) -> float:
    gap = float(top["final_score"] - runner_up["final_score"]) if runner_up is not None else 40.0
    base = min(max(gap / 25, 0), 1) * 0.6 + 0.3
    if top["eligibility_status"] != "Qualified":
        base *= 0.7
    if bool(top.get("is_anomalous", False)):
        base *= 0.6
    return round(min(base, 0.98), 2)


# --------------------------------------------------------------------------
# Orchestrator — the one function every page should call
# --------------------------------------------------------------------------

def _empty_recommendation(tender: dict, evaluated_pool: pd.DataFrame | None = None, no_category_match: bool = False) -> dict:
    pool = evaluated_pool if evaluated_pool is not None else pd.DataFrame()
    closest = [] if pool.empty else _closest_matches(pool, tender)
    if no_category_match:
        risk_msg = "No vendor in the current dataset is in this tender's eligible category."
        reasoning = "No vendors exist in the vendor pool for this tender's category — expand the supplier pool to evaluate this tender."
    else:
        risk_msg = "No fully compliant vendors found."
        reasoning = "No vendor met this tender's mandatory requirements. Consider expanding the supplier pool or modifying non-mandatory requirements."
    return {
        "tender_id": tender["tender_id"],
        "tender_title": tender["title"],
        "vendor_id": None,
        "vendor_name": "No eligible vendor found",
        "final_score": 0.0,
        "rank": 0,
        "qualified_vendors": 0,
        "evaluated_vendors": int(len(pool)),
        "anomalous_count": int(pool["is_anomalous"].sum()) if "is_anomalous" in pool.columns and not pool.empty else 0,
        "confidence": 0.0,
        "eligibility_status": "None",
        "strengths": [],
        "risks": [risk_msg],
        "reasoning": reasoning,
        "score_breakdown": {},
        "ranking": [],
        "closest_matches": closest,
        "scored_pool_df": pool,
    }


def build_recommendation(ranked_df: pd.DataFrame, tender_id: str) -> dict:
    """The centralized recommendation object. Recomputed fresh every call —
    never cached — so switching tenders always reruns the full pipeline
    below and can never show a stale recommendation."""
    tender = get_tender(tender_id)
    print(f"[recommendation_engine] Tender selected: {tender['title']} ({tender_id})")
    print(f"[recommendation_engine] Tender category: {tender['category']} (vendor category match: {tender['vendor_category_match']})")

    pool = ranked_df[ranked_df["category"].isin(tender["vendor_category_match"])].copy()
    print(f"[recommendation_engine] Eligible vendors (category match): {len(pool)}")
    if pool.empty:
        print("[recommendation_engine] No vendors match this tender's category — returning empty recommendation.")
        return _empty_recommendation(tender, no_category_match=True)

    pool = compute_eligibility(pool, tender)
    pool = compute_tender_scores(pool, tender)

    viable = pool[pool["eligibility_status"] != "Disqualified"].sort_values("final_score", ascending=False).reset_index(drop=True)
    if "rank" in viable.columns:
        viable = viable.drop(columns=["rank"])
    viable.insert(0, "tender_rank", range(1, len(viable) + 1))

    print(
        "[recommendation_engine] Vendor scores: "
        + str(viable[["vendor_id", "vendor_name", "final_score", "eligibility_status"]].to_dict("records"))
    )

    if viable.empty:
        print("[recommendation_engine] Every eligible vendor was disqualified — returning empty recommendation.")
        return _empty_recommendation(tender, evaluated_pool=pool)

    top = viable.iloc[0]
    runner_up = viable.iloc[1] if len(viable) > 1 else None
    print(f"[recommendation_engine] Recommended vendor: {top['vendor_name']} ({top['vendor_id']}) — final_score {top['final_score']}")

    strengths, risks = _generate_explanations(top, viable, tender)
    confidence = _confidence(top, runner_up)
    breakdown = _score_breakdown(top, tender)
    reasoning = (
        f"{top['vendor_name']} scored {top['final_score']:.1f}/100 against {tender['title']}'s evaluation "
        f"criteria, leading a pool of {len(viable)} qualified vendor(s) evaluated in the {tender['category']} category."
    )

    return {
        "tender_id": tender_id,
        "tender_title": tender["title"],
        "vendor_id": top["vendor_id"],
        "vendor_name": top["vendor_name"],
        "final_score": float(top["final_score"]),
        "rank": int(top["tender_rank"]),
        "qualified_vendors": int(len(viable)),
        "evaluated_vendors": int(len(pool)),
        "anomalous_count": int(pool["is_anomalous"].sum()),
        "confidence": confidence,
        "eligibility_status": top["eligibility_status"],
        "strengths": strengths,
        "risks": risks,
        "reasoning": reasoning,
        "score_breakdown": breakdown,
        "ranking": viable[["tender_rank", "vendor_id", "vendor_name", "final_score", "eligibility_status"]].to_dict("records"),
        "closest_matches": [],
        "scored_pool_df": pool,
    }
