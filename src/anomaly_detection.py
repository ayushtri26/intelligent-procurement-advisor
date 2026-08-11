"""Isolation Forest based anomalous vendor detection."""
from __future__ import annotations

import pandas as pd
from sklearn.ensemble import IsolationForest

from src.feature_engineering import FEATURE_COLUMNS


def detect_anomalies(
    df: pd.DataFrame,
    feature_cols: list[str] | None = None,
    contamination: float = 0.1,
    random_state: int = 42,
) -> pd.DataFrame:
    """Add `anomaly_score` (higher = more normal) and `is_anomalous` columns."""
    feature_cols = feature_cols or FEATURE_COLUMNS
    df = df.copy()

    model = IsolationForest(contamination=contamination, random_state=random_state)
    X = df[feature_cols]
    predictions = model.fit_predict(X)
    df["anomaly_score"] = model.decision_function(X).round(3)
    df["is_anomalous"] = predictions == -1
    return df


def get_anomaly_drivers(
    df: pd.DataFrame,
    vendor_id: str,
    feature_cols: list[str] | None = None,
    top_n: int = 3,
) -> list[dict]:
    """Rule-based explanation: which features deviate most from the peer-group mean."""
    feature_cols = feature_cols or FEATURE_COLUMNS
    vendor_row = df.loc[df["vendor_id"] == vendor_id]
    if vendor_row.empty:
        return []
    vendor_row = vendor_row.iloc[0]

    means = df[feature_cols].mean()
    stds = df[feature_cols].std(ddof=0).replace(0, 1)

    drivers = []
    for feature in feature_cols:
        z_score = (vendor_row[feature] - means[feature]) / stds[feature]
        drivers.append(
            {
                "feature": feature,
                "value": round(float(vendor_row[feature]), 1),
                "peer_average": round(float(means[feature]), 1),
                "z_score": round(float(z_score), 2),
                "direction": "above" if z_score > 0 else "below",
            }
        )

    drivers.sort(key=lambda d: abs(d["z_score"]), reverse=True)
    return drivers[:top_n]
