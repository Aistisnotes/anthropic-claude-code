"""CSV Matcher — matches Meta Ads Manager CSV rows to ClickUp creative tasks.

Matching uses version numbers (V876, V877) found in both ad names and task names.
A single ClickUp task can map to multiple CSV rows (e.g., V876-V878 = 3 ads).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import StringIO
from typing import Optional

import pandas as pd

from .clickup_client import CreativeTask

# Pattern to find version/batch numbers like V876, v877, B310, b50
VERSION_PATTERN = re.compile(r'[VvBb](\d+)')
# Pattern for version ranges like V876-V878, V876-878
VERSION_RANGE_PATTERN = re.compile(r'[VvBb](\d+)\s*[-–—]\s*[VvBb]?(\d+)')


@dataclass
class AdMetrics:
    """Performance metrics for a single ad from Meta CSV."""
    ad_name: str
    version_number: Optional[str] = None
    spend: float = 0.0
    roas: float = 0.0
    cpa: float = 0.0
    ctr: float = 0.0
    impressions: int = 0
    conversions: int = 0
    cost_per_purchase: float = 0.0
    thruplays: int = 0
    hook_rate: float = 0.0
    # Raw row data for reference
    raw_data: dict = field(default_factory=dict)


@dataclass
class MatchResult:
    """Result of matching a ClickUp task to CSV ad data."""
    task: CreativeTask
    matched_ads: list[AdMetrics] = field(default_factory=list)
    # Aggregated metrics across all matched ads
    total_spend: float = 0.0
    avg_roas: float = 0.0
    avg_cpa: float = 0.0
    avg_ctr: float = 0.0
    total_impressions: int = 0
    total_conversions: int = 0
    weighted_roas: float = 0.0  # Spend-weighted ROAS


@dataclass
class MatchSummary:
    """Summary of the matching process."""
    matched: list[MatchResult]
    unmatched_tasks: list[CreativeTask]
    unmatched_csv_rows: list[AdMetrics]
    total_account_spend: float
    total_matched: int
    total_unmatched_tasks: int
    total_unmatched_csv: int


def extract_version_numbers(text: str) -> set[str]:
    """Extract all V/B identifiers from text, expanding ranges, with prefix attached.

    Examples:
      "V876-V878"        -> {'V876', 'V877', 'V878'}
      "B310_V1"          -> {'B310', 'V1'}
      "[SKN] V876-V878"  -> {'V876', 'V877', 'V878'}
      "B310 / V1-V3"     -> {'B310', 'V1', 'V2', 'V3'}
    """
    versions: set[str] = set()

    # Expand ranges first (e.g. V876-V878 -> V876, V877, V878)
    for match in VERSION_RANGE_PATTERN.finditer(text):
        prefix = match.group(0)[0].upper()  # V or B
        start, end = int(match.group(1)), int(match.group(2))
        if end >= start and (end - start) <= 50:
            for v in range(start, end + 1):
                versions.add(f"{prefix}{v}")

    # Then add all individual V/B identifiers
    for match in VERSION_PATTERN.finditer(text):
        prefix = match.group(0)[0].upper()
        versions.add(f"{prefix}{match.group(1)}")

    return versions


# ── Column name mapping ───────────────────────────────────────────────────────

COLUMN_ALIASES = {
    "ad_name": ["ad name", "ad_name", "name", "ad creative name"],
    "spend": ["amount spent (usd)", "amount spent", "spend", "cost", "total spend"],
    "roas": ["purchase roas", "roas", "website purchase roas", "purchase roas (return on ad spend)"],
    "cpa": ["cost per purchase", "cost per result", "cpa", "cost per action"],
    "ctr": ["ctr (link click-through rate)", "ctr", "link ctr", "ctr (all)"],
    "impressions": ["impressions"],
    "conversions": ["purchases", "conversions", "results", "website purchases"],
    "cost_per_purchase": ["cost per purchase", "cost per website purchase"],
    "thruplays": ["thruplays", "thruplay", "video plays at 100%"],
    "hook_rate": ["hook rate", "video plays at 25%", "video average play time"],
}


def _find_column(df: pd.DataFrame, aliases: list[str]) -> Optional[str]:
    """Find a column in the DataFrame by checking aliases (case-insensitive)."""
    df_cols_lower = {c.lower().strip(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in df_cols_lower:
            return df_cols_lower[alias.lower()]
    return None


def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if pd.isna(val):
        return default
    try:
        # Handle strings with commas and currency symbols
        if isinstance(val, str):
            val = val.replace(",", "").replace("$", "").replace("%", "").strip()
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default: int = 0) -> int:
    """Safely convert a value to int."""
    return int(_safe_float(val, float(default)))


# ── Core parsing ──────────────────────────────────────────────────────────────

def parse_meta_csv(csv_content: str | bytes) -> tuple[list[AdMetrics], float]:
    """Parse Meta Ads Manager CSV export.

    Returns: (list of AdMetrics, total_account_spend)
    """
    if isinstance(csv_content, bytes):
        csv_content = csv_content.decode("utf-8", errors="replace")

    df = pd.read_csv(StringIO(csv_content))

    # Find relevant columns
    col_ad_name = _find_column(df, COLUMN_ALIASES["ad_name"])
    col_spend = _find_column(df, COLUMN_ALIASES["spend"])
    col_roas = _find_column(df, COLUMN_ALIASES["roas"])
    col_cpa = _find_column(df, COLUMN_ALIASES["cpa"])
    col_ctr = _find_column(df, COLUMN_ALIASES["ctr"])
    col_impressions = _find_column(df, COLUMN_ALIASES["impressions"])
    col_conversions = _find_column(df, COLUMN_ALIASES["conversions"])
    col_cost_per_purchase = _find_column(df, COLUMN_ALIASES["cost_per_purchase"])
    col_thruplays = _find_column(df, COLUMN_ALIASES["thruplays"])
    col_hook_rate = _find_column(df, COLUMN_ALIASES["hook_rate"])

    if not col_ad_name:
        raise ValueError(
            f"Could not find ad name column. Available columns: {list(df.columns)}"
        )

    ads: list[AdMetrics] = []
    total_spend = 0.0

    for _, row in df.iterrows():
        ad_name = str(row.get(col_ad_name, "")).strip()
        if not ad_name or ad_name == "nan":
            continue

        spend = _safe_float(row.get(col_spend)) if col_spend else 0.0
        total_spend += spend

        versions = extract_version_numbers(ad_name)

        ad = AdMetrics(
            ad_name=ad_name,
            version_number=next(iter(versions)) if len(versions) == 1 else None,
            spend=spend,
            roas=_safe_float(row.get(col_roas)) if col_roas else 0.0,
            cpa=_safe_float(row.get(col_cpa)) if col_cpa else 0.0,
            ctr=_safe_float(row.get(col_ctr)) if col_ctr else 0.0,
            impressions=_safe_int(row.get(col_impressions)) if col_impressions else 0,
            conversions=_safe_int(row.get(col_conversions)) if col_conversions else 0,
            cost_per_purchase=_safe_float(row.get(col_cost_per_purchase)) if col_cost_per_purchase else 0.0,
            thruplays=_safe_int(row.get(col_thruplays)) if col_thruplays else 0,
            hook_rate=_safe_float(row.get(col_hook_rate)) if col_hook_rate else 0.0,
            raw_data=row.to_dict(),
        )
        ads.append(ad)

    return ads, total_spend


# ── Matching ──────────────────────────────────────────────────────────────────

def match_tasks_to_csv(
    tasks: list[CreativeTask],
    ads: list[AdMetrics],
    total_account_spend: float,
) -> MatchSummary:
    """Match ClickUp tasks to Meta CSV ads by version numbers.

    A task can match multiple ads (V876-V878 = 3 ads).
    An ad can only match one task (first match wins).
    """
    matched_results: list[MatchResult] = []
    unmatched_tasks: list[CreativeTask] = []
    matched_ad_indices: set[int] = set()

    for task in tasks:
        task_versions = extract_version_numbers(task.name)
        if not task_versions:
            # Try matching by exact name substring as fallback
            pass

        matched_ads: list[AdMetrics] = []
        for idx, ad in enumerate(ads):
            if idx in matched_ad_indices:
                continue
            ad_versions = extract_version_numbers(ad.ad_name)

            # Match if any version number overlaps
            if task_versions & ad_versions:
                matched_ads.append(ad)
                matched_ad_indices.add(idx)

        if matched_ads:
            result = MatchResult(task=task, matched_ads=matched_ads)
            # Calculate aggregated metrics
            result.total_spend = sum(a.spend for a in matched_ads)
            result.total_impressions = sum(a.impressions for a in matched_ads)
            result.total_conversions = sum(a.conversions for a in matched_ads)

            # Spend-weighted ROAS
            if result.total_spend > 0:
                result.weighted_roas = sum(
                    a.spend * a.roas for a in matched_ads
                ) / result.total_spend
            result.avg_roas = result.weighted_roas

            # Average CPA/CTR (spend-weighted)
            if result.total_spend > 0:
                result.avg_cpa = sum(
                    a.spend * a.cpa for a in matched_ads if a.cpa > 0
                ) / result.total_spend
                result.avg_ctr = sum(
                    a.spend * a.ctr for a in matched_ads if a.ctr > 0
                ) / result.total_spend

            matched_results.append(result)
        else:
            unmatched_tasks.append(task)

    # Unmatched CSV rows
    unmatched_csv = [
        ads[i] for i in range(len(ads)) if i not in matched_ad_indices
    ]

    return MatchSummary(
        matched=matched_results,
        unmatched_tasks=unmatched_tasks,
        unmatched_csv_rows=unmatched_csv,
        total_account_spend=total_account_spend,
        total_matched=len(matched_results),
        total_unmatched_tasks=len(unmatched_tasks),
        total_unmatched_csv=len(unmatched_csv),
    )


def get_top_account_ads(ads: list[AdMetrics], n: int = 5) -> list[AdMetrics]:
    """Return top N ads by spend from the full CSV (regardless of ClickUp match)."""
    return sorted(ads, key=lambda a: a.spend, reverse=True)[:n]
