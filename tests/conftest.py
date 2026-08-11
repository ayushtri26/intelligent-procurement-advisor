import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.analytics_tools import add_recommendation_categories
from src.anomaly_detection import detect_anomalies
from src.data_processing import coerce_numeric_columns, load_csv, rows_with_missing_mask
from src.feature_engineering import engineer_features
from src.vendor_scoring import DEFAULT_WEIGHTS, compute_overall_score, rank_vendors


@pytest.fixture(autouse=True)
def no_api_key_by_default(monkeypatch):
    """Tests run without a Claude key unless they explicitly set one, so the
    deterministic rule-based path is what's actually exercised by default."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def ranked_df():
    """The real sample-vendor pipeline output, exactly as app.py would build it."""
    raw = load_csv(os.path.join(_REPO_ROOT, "data", "sample_vendors.csv"))
    raw = coerce_numeric_columns(raw)
    raw["had_missing_data"] = rows_with_missing_mask(raw)
    featured = engineer_features(raw)
    scored = compute_overall_score(featured, DEFAULT_WEIGHTS)
    scored = detect_anomalies(scored, contamination=0.1, random_state=42)
    ranked = rank_vendors(scored)
    ranked = add_recommendation_categories(ranked)
    return ranked
