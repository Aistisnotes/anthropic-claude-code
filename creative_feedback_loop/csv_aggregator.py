"""CSV aggregation logic — the ROOT of all analysis.

Meta CSV exports have ONE ROW PER AD PER AD SET. The same ad name appears
multiple times. This module groups rows by ad name and produces aggregated
metrics before any matching or classification happens.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Common column name variants in Meta exports
AD_NAME_COLUMNS = [
    "Ad name", "ad_name", "Ad Name", "ad name",
    "Ad creative name", "Creative name",
]
SPEND_COLUMNS = [
    "Amount spent (USD)", "Amount spent", "Spend", "spend",
    "Cost", "cost", "Amount Spent (USD)",
]
ROAS_COLUMNS = [
    "Purchase ROAS", "purchase_roas", "ROAS", "roas",
    "Website Purchase ROAS", "Purchase ROAS (Total)",
    "Purchase ROAS (return on ad spend)",
]
REVENUE_COLUMNS = [
    "Purchase Conversion Value", "Revenue", "revenue",
    "Conversion value", "Purchase conversion value",
    "Website Purchase Conversion Value",
    "Website Purchases Conversion Value",
]
IMPRESSIONS_COLUMNS = [
    "Impressions", "impressions", "Impr.",
]
CONVERSIONS_COLUMNS = [
    "Purchases", "purchases", "Results", "results",
    "Website Purchases", "Conversions", "conversions",
]
DATE_COLUMNS = [
    "Day", "Reporting starts", "Date", "date", "day",
    "Reporting Starts", "Start date",
]


@dataclass
class AggregatedAd:
    """An ad with metrics aggregated across all ad sets / rows."""
    ad_name: str
    total_spend: float = 0.0
    total_revenue: float = 0.0
    blended_roas: float = 0.0
    total_impressions: int = 0
    total_conversions: int = 0
    row_count: int = 0


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find the first matching column name from a list of candidates."""
    for c in candidates:
        if c in df.columns:
            return c
    # Try case-insensitive
    lower_map = {col.lower().strip(): col for col in df.columns}
    for c in candidates:
        if c.lower().strip() in lower_map:
            return lower_map[c.lower().strip()]
    return None


def _safe_float(val: Any) -> float:
    """Convert a value to float, treating blanks / errors as 0."""
    if pd.isna(val):
        return 0.0
    try:
        # Strip currency symbols and commas
        if isinstance(val, str):
            val = re.sub(r"[,$€£]", "", val.strip())
            if val == "" or val == "-":
                return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val: Any) -> int:
    return int(_safe_float(val))


def load_and_aggregate_csv(
    csv_path: str,
    date_start: str | None = None,
    date_end: str | None = None,
) -> tuple[list[AggregatedAd], dict[str, Any]]:
    """Load a Meta Ads CSV and aggregate rows by ad name.

    Args:
        csv_path: Path to the CSV file.
        date_start: Optional start date filter (YYYY-MM-DD).
        date_end: Optional end date filter (YYYY-MM-DD).

    Returns:
        (list of AggregatedAd, stats dict with raw_rows, unique_ads, etc.)
    """
    df = pd.read_csv(csv_path)
    raw_row_count = len(df)
    logger.info(f"Loaded CSV with {raw_row_count} rows, {len(df.columns)} columns")

    # Resolve column names
    ad_name_col = _find_column(df, AD_NAME_COLUMNS)
    spend_col = _find_column(df, SPEND_COLUMNS)
    roas_col = _find_column(df, ROAS_COLUMNS)
    revenue_col = _find_column(df, REVENUE_COLUMNS)
    impressions_col = _find_column(df, IMPRESSIONS_COLUMNS)
    conversions_col = _find_column(df, CONVERSIONS_COLUMNS)
    date_col = _find_column(df, DATE_COLUMNS)

    if not ad_name_col:
        raise ValueError(
            f"Cannot find ad name column. Available columns: {list(df.columns)}"
        )
    if not spend_col:
        raise ValueError(
            f"Cannot find spend column. Available columns: {list(df.columns)}"
        )

    logger.info(
        f"Resolved columns — ad_name: '{ad_name_col}', spend: '{spend_col}', "
        f"roas: '{roas_col}', revenue: '{revenue_col}', "
        f"impressions: '{impressions_col}', conversions: '{conversions_col}', "
        f"date: '{date_col}'"
    )

    # ── Optional date filtering (FIX 4) ──
    if date_col and (date_start or date_end):
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        before_filter = len(df)
        if date_start:
            df = df[df[date_col] >= pd.Timestamp(date_start)]
        if date_end:
            df = df[df[date_col] <= pd.Timestamp(date_end)]
        after_filter = len(df)
        logger.info(
            f"Date filter applied: {before_filter} → {after_filter} rows "
            f"({date_start} to {date_end})"
        )
    elif (date_start or date_end) and not date_col:
        logger.warning(
            "Date filter requested but no date column found in CSV — using all data"
        )

    # ── Group by ad name and aggregate (FIX 1 — THE CRITICAL FIX) ──
    aggregated: dict[str, AggregatedAd] = {}

    for _, row in df.iterrows():
        name = str(row[ad_name_col]).strip()
        if not name or name.lower() == "nan":
            continue

        if name not in aggregated:
            aggregated[name] = AggregatedAd(ad_name=name)

        ad = aggregated[name]
        row_spend = _safe_float(row.get(spend_col, 0))
        ad.total_spend += row_spend

        # Revenue: prefer direct revenue column, fall back to spend * ROAS
        if revenue_col and revenue_col in row.index:
            ad.total_revenue += _safe_float(row.get(revenue_col, 0))
        elif roas_col and roas_col in row.index:
            row_roas = _safe_float(row.get(roas_col, 0))
            ad.total_revenue += row_spend * row_roas

        if impressions_col:
            ad.total_impressions += _safe_int(row.get(impressions_col, 0))
        if conversions_col:
            ad.total_conversions += _safe_int(row.get(conversions_col, 0))

        ad.row_count += 1

    # Calculate blended ROAS per ad
    for ad in aggregated.values():
        if ad.total_spend > 0:
            ad.blended_roas = round(ad.total_revenue / ad.total_spend, 4)
        else:
            ad.blended_roas = 0.0

    ads_list = sorted(aggregated.values(), key=lambda a: a.total_spend, reverse=True)

    stats = {
        "raw_rows": raw_row_count,
        "rows_after_date_filter": len(df),
        "unique_ads": len(ads_list),
        "total_spend": sum(a.total_spend for a in ads_list),
        "has_date_column": date_col is not None,
        "date_column_name": date_col,
    }

    logger.info(
        f"Aggregated {raw_row_count} CSV rows into {len(ads_list)} unique ads"
    )

    return ads_list, stats
