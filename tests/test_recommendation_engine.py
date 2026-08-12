"""Tests for the centralized, tender-aware recommendation service
(src/recommendation_engine.py) — the core of the "make vendor
recommendation tender-specific" feature.

Uses the real sample_vendors.csv run through the unchanged deterministic
pipeline (src.feature_engineering / src.vendor_scoring / src.anomaly_detection)
so these tests exercise the same code path app.py uses, not a synthetic
fixture that could hide integration bugs.
"""
import pandas as pd
import pytest

from src.analytics_tools import add_recommendation_categories
from src.anomaly_detection import detect_anomalies
from src.data_processing import coerce_numeric_columns, load_csv, rows_with_missing_mask
from src.feature_engineering import engineer_features
from src.recommendation_engine import build_recommendation, compute_eligibility, compute_tender_scores
from src.tender_repository import get_tender
from src.tenders_data import SEED_TENDERS as TENDERS
from src.vendor_scoring import DEFAULT_WEIGHTS, compute_overall_score, rank_vendors


@pytest.fixture(scope="module")
def ranked_df() -> pd.DataFrame:
    raw_df = coerce_numeric_columns(load_csv("data/sample_vendors.csv"))
    raw_df["had_missing_data"] = rows_with_missing_mask(raw_df)
    featured_df = engineer_features(raw_df)
    scored_df = compute_overall_score(featured_df, DEFAULT_WEIGHTS)
    scored_df = detect_anomalies(scored_df, contamination=0.1)
    df = rank_vendors(scored_df)
    return add_recommendation_categories(df)


def test_all_three_mock_tenders_exist():
    assert len(TENDERS) >= 3
    categories = {t["category"] for t in TENDERS.values()}
    assert len(categories) == len(TENDERS)  # each tender is a genuinely distinct category


def test_recommendation_changes_across_all_three_tenders(ranked_df):
    """The core requirement: different tenders must produce different
    recommended vendors because eligibility/requirements/weights genuinely
    differ — not because of randomization."""
    recommendations = {tid: build_recommendation(ranked_df, tid) for tid in TENDERS}
    vendor_names = {tid: rec["vendor_name"] for tid, rec in recommendations.items()}

    for tid, rec in recommendations.items():
        assert rec["vendor_id"] is not None, f"{tid} produced no recommendation"

    assert len(set(vendor_names.values())) == len(vendor_names), (
        f"Expected a distinct recommended vendor per tender, got {vendor_names}"
    )


def test_recommendation_is_deterministic_for_the_same_tender(ranked_df):
    first = build_recommendation(ranked_df, "TND-001")
    second = build_recommendation(ranked_df, "TND-001")
    assert first["vendor_id"] == second["vendor_id"]
    assert first["final_score"] == second["final_score"]


def test_eligible_vendors_are_restricted_to_the_tender_category(ranked_df):
    tender = get_tender("TND-001")  # laptops -> Electronics
    rec = build_recommendation(ranked_df, "TND-001")
    pool = rec["scored_pool_df"]
    assert set(pool["category"].unique()) == set(tender["vendor_category_match"])


def test_recommended_vendor_is_never_disqualified(ranked_df):
    for tid in TENDERS:
        rec = build_recommendation(ranked_df, tid)
        assert rec["eligibility_status"] != "Disqualified"


def test_disqualified_vendor_is_excluded_from_ranking(ranked_df):
    # Union Circuit Depot (V021) has 0 certifications and 4 compliance
    # violations — must never be recommendable for the laptop tender.
    rec = build_recommendation(ranked_df, "TND-001")
    ranked_ids = {row["vendor_id"] for row in rec["ranking"]}
    assert "V021" not in ranked_ids


def test_score_breakdown_totals_match_final_score(ranked_df):
    for tid in TENDERS:
        rec = build_recommendation(ranked_df, tid)
        breakdown = rec["score_breakdown"]
        assert breakdown, f"{tid} produced no score breakdown"
        total = breakdown["Total"]
        assert total["points"] == pytest.approx(rec["final_score"], abs=0.2)
        assert total["max"] == pytest.approx(100.0, abs=0.5)


def test_qualified_vendors_count_matches_ranking_length(ranked_df):
    for tid in TENDERS:
        rec = build_recommendation(ranked_df, tid)
        assert rec["qualified_vendors"] == len(rec["ranking"])


def test_confidence_is_between_zero_and_one(ranked_df):
    for tid in TENDERS:
        rec = build_recommendation(ranked_df, tid)
        assert 0.0 <= rec["confidence"] <= 1.0


def test_strengths_and_risks_are_generated_not_fixed_text(ranked_df):
    rec_laptop = build_recommendation(ranked_df, "TND-001")
    rec_furniture = build_recommendation(ranked_df, "TND-002")
    # Different tenders/vendors must produce different generated explanation
    # text (proves it's computed from real deltas, not a hardcoded string).
    assert rec_laptop["strengths"] != rec_furniture["strengths"]
    assert rec_laptop["reasoning"] != rec_furniture["reasoning"]


def test_compute_eligibility_flags_low_certification_vendor_as_disqualified(ranked_df):
    tender = get_tender("TND-001")
    pool = ranked_df[ranked_df["category"].isin(tender["vendor_category_match"])]
    tagged = compute_eligibility(pool, tender)
    v021 = tagged[tagged["vendor_id"] == "V021"].iloc[0]
    assert v021["eligibility_status"] == "Disqualified"


def test_compute_tender_scores_final_score_within_bounds(ranked_df):
    tender = get_tender("TND-003")
    pool = ranked_df[ranked_df["category"].isin(tender["vendor_category_match"])]
    pool = compute_eligibility(pool, tender)
    scored = compute_tender_scores(pool, tender)
    assert (scored["final_score"] >= 0).all()
    assert (scored["final_score"] <= 100).all()


def test_build_recommendation_handles_unknown_tender_id_gracefully(ranked_df):
    rec = build_recommendation(ranked_df, "TND-DOES-NOT-EXIST")
    # get_tender() falls back to the default tender rather than raising.
    assert rec["tender_id"] in TENDERS or rec["vendor_id"] is not None
