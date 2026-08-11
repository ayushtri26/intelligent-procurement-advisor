"""Configurable weighted vendor scoring."""
from __future__ import annotations

import pandas as pd

from src.feature_engineering import FEATURE_COLUMNS

DEFAULT_WEIGHTS = {
    "price_competitiveness": 0.20,
    "delivery_reliability": 0.20,
    "quality_score": 0.20,
    "compliance_score": 0.15,
    "experience_score": 0.15,
    "financial_stability_score": 0.10,
}


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Scale weights so they sum to 1.0. Falls back to defaults if all zero."""
    total = sum(weights.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in weights.items()}


def compute_overall_score(df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Add an `overall_score` column (0-100) as the weighted sum of feature scores."""
    weights = normalize_weights(weights or DEFAULT_WEIGHTS)
    df = df.copy()
    df["overall_score"] = sum(df[feature] * weights[feature] for feature in FEATURE_COLUMNS)
    df["overall_score"] = df["overall_score"].round(1)
    return df


def rank_vendors(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by overall_score descending and add a 1-based rank column."""
    df = df.sort_values("overall_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df
