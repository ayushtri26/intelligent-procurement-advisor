"""CSV loading and validation for vendor data."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

REQUIRED_COLUMNS = [
    "vendor_id",
    "vendor_name",
    "category",
    "quoted_price",
    "market_avg_price",
    "on_time_delivery_rate",
    "avg_delay_days",
    "defect_rate",
    "quality_rating",
    "certifications_count",
    "compliance_violations",
    "years_in_business",
    "completed_contracts",
    "annual_revenue",
    "debt_to_equity_ratio",
]

NUMERIC_COLUMNS = [c for c in REQUIRED_COLUMNS if c not in ("vendor_id", "vendor_name", "category")]


@dataclass
class ValidationReport:
    total_rows: int
    missing_columns: list[str]
    missing_counts: pd.Series
    missing_pct: pd.Series
    duplicate_vendor_ids: list[str]
    rows_with_missing: int
    is_valid: bool
    errors: list[str] = field(default_factory=list)

    @property
    def has_missing_values(self) -> bool:
        return bool(self.missing_counts.sum() > 0)


def load_csv(file) -> pd.DataFrame:
    """Load a vendor CSV from a path or an uploaded file-like object."""
    df = pd.read_csv(file)
    df.columns = [c.strip() for c in df.columns]
    return df


def validate_vendor_data(df: pd.DataFrame) -> ValidationReport:
    """Check required columns, missing values, and duplicate vendor ids."""
    errors: list[str] = []

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        errors.append(f"Missing required columns: {', '.join(missing_columns)}")

    present_columns = [c for c in REQUIRED_COLUMNS if c in df.columns]
    missing_counts = df[present_columns].isna().sum() if present_columns else pd.Series(dtype=int)
    missing_pct = (missing_counts / len(df) * 100).round(1) if len(df) else missing_counts

    duplicate_vendor_ids: list[str] = []
    if "vendor_id" in df.columns:
        dupes = df["vendor_id"][df["vendor_id"].duplicated(keep=False)]
        duplicate_vendor_ids = sorted(dupes.dropna().unique().tolist())
        if duplicate_vendor_ids:
            errors.append(f"Duplicate vendor_id values: {', '.join(duplicate_vendor_ids)}")

    rows_with_missing = int(df[present_columns].isna().any(axis=1).sum()) if present_columns else 0

    is_valid = not missing_columns and not duplicate_vendor_ids and len(df) > 0

    return ValidationReport(
        total_rows=len(df),
        missing_columns=missing_columns,
        missing_counts=missing_counts,
        missing_pct=missing_pct,
        duplicate_vendor_ids=duplicate_vendor_ids,
        rows_with_missing=rows_with_missing,
        is_valid=is_valid,
        errors=errors,
    )


def rows_with_missing_mask(df: pd.DataFrame) -> pd.Series:
    """Per-row boolean: True if any required field is missing. Used to flag low-confidence records downstream."""
    present = [c for c in REQUIRED_COLUMNS if c in df.columns]
    if not present:
        return pd.Series(False, index=df.index)
    return df[present].isna().any(axis=1)


def coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Force expected numeric columns to numeric dtype, turning bad values into NaN."""
    df = df.copy()
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
