"""Derive 0-100 vendor feature scores from raw procurement/vendor data."""
from __future__ import annotations

import pandas as pd

from src.data_processing import NUMERIC_COLUMNS

FEATURE_COLUMNS = [
    "price_competitiveness",
    "delivery_reliability",
    "quality_score",
    "compliance_score",
    "experience_score",
    "financial_stability_score",
]


def impute_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing numeric values with the column median so scoring never breaks on NaN."""
    df = df.copy()
    for col in NUMERIC_COLUMNS:
        if col in df.columns and df[col].isna().any():
            median = df[col].median()
            df[col] = df[col].fillna(median)
    return df


def _minmax(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi - lo == 0:
        return pd.Series(50.0, index=series.index)
    return (series - lo) / (hi - lo) * 100


def price_competitiveness(df: pd.DataFrame) -> pd.Series:
    """Cheaper than market average scores higher; at market average scores 50."""
    ratio_diff = (df["market_avg_price"] - df["quoted_price"]) / df["market_avg_price"]
    return (ratio_diff * 100 + 50).clip(0, 100)


def delivery_reliability(df: pd.DataFrame) -> pd.Series:
    on_time = df["on_time_delivery_rate"].clip(0, 1) * 100
    delay_penalty = (100 - df["avg_delay_days"] * 10).clip(0, 100)
    return (on_time * 0.7 + delay_penalty * 0.3).clip(0, 100)


def quality_score(df: pd.DataFrame) -> pd.Series:
    defect_component = (1 - df["defect_rate"].clip(0, 1)) * 100
    rating_component = df["quality_rating"].clip(0, 10) * 10
    return (defect_component * 0.5 + rating_component * 0.5).clip(0, 100)


def compliance_score(df: pd.DataFrame) -> pd.Series:
    cert_component = (df["certifications_count"].clip(lower=0, upper=5) / 5) * 100
    violation_component = (100 - df["compliance_violations"].clip(lower=0) * 25).clip(0, 100)
    return (cert_component * 0.6 + violation_component * 0.4).clip(0, 100)


def experience_score(df: pd.DataFrame) -> pd.Series:
    years_component = (df["years_in_business"].clip(lower=0, upper=20) / 20) * 100
    contracts_component = (df["completed_contracts"].clip(lower=0, upper=100) / 100) * 100
    return (years_component * 0.5 + contracts_component * 0.5).clip(0, 100)


def financial_stability_score(df: pd.DataFrame) -> pd.Series:
    revenue_component = _minmax(df["annual_revenue"])
    debt_component = (100 - df["debt_to_equity_ratio"].clip(lower=0) * 50).clip(0, 100)
    return (revenue_component * 0.5 + debt_component * 0.5).clip(0, 100)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with imputation applied and all feature score columns added."""
    df = impute_missing_values(df)
    df["price_competitiveness"] = price_competitiveness(df)
    df["delivery_reliability"] = delivery_reliability(df)
    df["quality_score"] = quality_score(df)
    df["compliance_score"] = compliance_score(df)
    df["experience_score"] = experience_score(df)
    df["financial_stability_score"] = financial_stability_score(df)
    for col in FEATURE_COLUMNS:
        df[col] = df[col].round(1)
    return df
