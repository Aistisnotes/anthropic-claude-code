"""CSV Matcher — matches Meta Ads Manager CSV rows to ClickUp creative tasks.

Matching uses version numbers (V876, V877) found in both ad names and task names.
A single ClickUp task can map to multiple CSV rows (e.g., V876-V878 = 3 ads).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Optional

import pandas as pd

from .clickup_client import CreativeTask

# Pattern to find version numbers like V876, v877, V1234
VERSION_PATTERN = re.compile(r'[Vv](\d{2,5})')
# Pattern for version ranges like V876-V878, V876-878
VERSION_RANGE_PATTERN = re.compile(r'[Vv](\d{2,5})\s*[-–—]\s*[Vv]?(\d{2,5})')
# Also match B-prefixed identifiers like B310
B_PATTERN = re.compile(r'[Bb](\d{2,5})')


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
    raw_data: dict = field(default_factory=dict)


@dataclass
class MatchResult:
    """Result of matching a ClickUp task to CSV ad data."""
    task: CreativeTask
    matched_ads: list[AdMetrics] = field(default_factory=list)
    total_spend: float = 0.0
    avg_roas: float = 0.0
    avg_cpa: float = 0.0
    avg_ctr: float = 0.0
    total_impressions: int = 0
    total_conversions: int = 0
    weighted_roas: float = 0.0  # Spend-weighted ROAS
    match_identifiers: list[str] = field(default_factory=list)  # Which identifiers matched


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
    match_log: list[str] = field(default_factory=list)  # Detailed match log


@dataclass
class CSVDiagnostics:
    """Debug info about the parsed CSV."""
    column_names: list[str]
    column_mapping: dict[str, Optional[str]]  # our_field → actual_column_name
    total_rows: int
    total_ads: int  # rows with valid ad name
    total_spend: float
    spend_stats: dict[str, float]  # min, max, median, avg
    roas_stats: dict[str, float]  # min, max, median, avg
    roas_below_threshold: dict[str, int]  # threshold → count
    spend_above_threshold: dict[str, int]  # threshold → count
    combined_checks: dict[str, int]  # "roas<X_and_spend>Y" → count


def extract_version_numbers(text: str) -> set[str]:
    """Extract all version numbers from text.

    Handles: V876, V876-V878 (range), V876-878 (short range), V876/V877.
    Returns set of version strings like {'V876', 'V877', 'V878', 'B310'}.
    Prefixed with V or B to avoid cross-matching.
    """
    versions: set[str] = set()

    # First find ranges
    for match in VERSION_RANGE_PATTERN.finditer(text):
        start = int(match.group(1))
        end_str = match.group(2)
        end = int(end_str)
        if end < start and len(end_str) < len(match.group(1)):
            prefix = match.group(1)[:len(match.group(1)) - len(end_str)]
            end = int(prefix + end_str)
        if end >= start and (end - start) <= 20:
            for v in range(start, end + 1):
                versions.add(f"V{v}")

    # Individual V-numbers
    for match in VERSION_PATTERN.finditer(text):
        versions.add(f"V{match.group(1)}")

    # B-numbers
    for match in B_PATTERN.finditer(text):
        versions.add(f"B{match.group(1)}")

    return versions


# ── Column name mapping ───────────────────────────────────────────────────────

COLUMN_ALIASES = {
    "ad_name": [
        "ad name", "ad_name", "name", "ad creative name", "creative name",
        "ad set name",  # some exports use this
    ],
    "spend": [
        "amount spent (usd)", "amount spent", "spend", "cost", "total spend",
        "amount spent (USD)", "amount_spent", "total_spend",
    ],
    "roas": [
        "purchase roas (total)", "purchase roas", "roas",
        "website purchase roas", "purchase roas (return on ad spend)",
        "website purchase roas (total)", "total purchase roas",
        "purchase_roas", "website_purchase_roas",
    ],
    "cpa": [
        "cost per result", "cost per purchase", "cpa", "cost per action",
        "cost per website purchase", "cost_per_result", "cost_per_purchase",
    ],
    "ctr": [
        "ctr (link click-through rate)", "ctr (all)", "ctr", "link ctr",
        "ctr (link)", "click-through rate", "ctr_all",
    ],
    "impressions": [
        "impressions", "imps", "total impressions",
    ],
    "conversions": [
        "results", "purchases", "conversions", "website purchases",
        "total purchases", "actions", "total_purchases",
    ],
    "cost_per_purchase": [
        "cost per purchase", "cost per website purchase",
        "cost per result", "cost_per_purchase",
    ],
    "thruplays": [
        "thruplays", "thruplay", "thruplay actions",
        "video plays at 100%", "video_thruplays",
    ],
    "hook_rate": [
        "hook rate", "video plays at 25%", "video average play time",
        "video_plays_at_25",
    ],
}


def _find_column(df: pd.DataFrame, aliases: list[str]) -> Optional[str]:
    """Find a column in the DataFrame by checking aliases (case-insensitive).

    Also tries substring matching as a fallback.
    """
    df_cols_lower = {c.lower().strip(): c for c in df.columns}
    # Exact match first
    for alias in aliases:
        if alias.lower() in df_cols_lower:
            return df_cols_lower[alias.lower()]
    # Substring match fallback (e.g., "purchase roas" matches "Website Purchase ROAS (Total)")
    for alias in aliases:
        alias_l = alias.lower()
        for col_l, col_orig in df_cols_lower.items():
            if alias_l in col_l:
                return col_orig
    return None


def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if pd.isna(val):
        return default
    try:
        if isinstance(val, str):
            val = val.replace(",", "").replace("$", "").replace("%", "").strip()
            if not val:
                return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default: int = 0) -> int:
    return int(_safe_float(val, float(default)))


# ── Core parsing ──────────────────────────────────────────────────────────────

def parse_meta_csv(csv_content: str | bytes) -> tuple[list[AdMetrics], float, CSVDiagnostics]:
    """Parse Meta Ads Manager CSV export.

    Returns: (list of AdMetrics, total_account_spend, diagnostics)
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

    # Build column mapping for diagnostics
    column_mapping = {
        "ad_name": col_ad_name,
        "spend": col_spend,
        "roas": col_roas,
        "cpa": col_cpa,
        "ctr": col_ctr,
        "impressions": col_impressions,
        "conversions": col_conversions,
        "cost_per_purchase": col_cost_per_purchase,
        "thruplays": col_thruplays,
        "hook_rate": col_hook_rate,
    }

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

    # Build diagnostics
    spends = [a.spend for a in ads]
    roases = [a.roas for a in ads]
    roases_nonzero = [r for r in roases if r > 0]

    spend_stats = {}
    roas_stats = {}
    if spends:
        spend_stats = {
            "min": min(spends), "max": max(spends),
            "median": statistics.median(spends),
            "avg": statistics.mean(spends),
        }
    if roases_nonzero:
        roas_stats = {
            "min": min(roases_nonzero), "max": max(roases_nonzero),
            "median": statistics.median(roases_nonzero),
            "avg": statistics.mean(roases_nonzero),
        }

    diag = CSVDiagnostics(
        column_names=list(df.columns),
        column_mapping=column_mapping,
        total_rows=len(df),
        total_ads=len(ads),
        total_spend=total_spend,
        spend_stats=spend_stats,
        roas_stats=roas_stats,
        roas_below_threshold={
            "< 0.5": sum(1 for a in ads if 0 < a.roas < 0.5),
            "< 0.8": sum(1 for a in ads if 0 < a.roas < 0.8),
            "< 0.9": sum(1 for a in ads if 0 < a.roas < 0.9),
            "< 1.0": sum(1 for a in ads if 0 < a.roas < 1.0),
        },
        spend_above_threshold={
            "> $100": sum(1 for a in ads if a.spend > 100),
            "> $500": sum(1 for a in ads if a.spend > 500),
            "> $1000": sum(1 for a in ads if a.spend > 1000),
            "> $5000": sum(1 for a in ads if a.spend > 5000),
        },
        combined_checks={
            "roas<0.8 AND spend>$500": sum(1 for a in ads if 0 < a.roas < 0.8 and a.spend > 500),
            "roas<0.9 AND spend>$500": sum(1 for a in ads if 0 < a.roas < 0.9 and a.spend > 500),
            "roas<0.9 AND spend>$1000": sum(1 for a in ads if 0 < a.roas < 0.9 and a.spend > 1000),
            "roas>1.5 AND spend>$500": sum(1 for a in ads if a.roas > 1.5 and a.spend > 500),
            "roas>2.0 AND spend>$1000": sum(1 for a in ads if a.roas > 2.0 and a.spend > 1000),
        },
    )

    return ads, total_spend, diag


# ── Matching ──────────────────────────────────────────────────────────────────

def match_tasks_to_csv(
    tasks: list[CreativeTask],
    ads: list[AdMetrics],
    total_account_spend: float,
) -> MatchSummary:
    """Match ClickUp tasks to Meta CSV ads by version numbers.

    Deterministic: sorts tasks by name before matching to ensure
    same input always produces same output.
    """
    # Sort tasks by name for deterministic ordering
    sorted_tasks = sorted(tasks, key=lambda t: t.name)

    matched_results: list[MatchResult] = []
    unmatched_tasks: list[CreativeTask] = []
    matched_ad_indices: set[int] = set()
    match_log: list[str] = []

    for task in sorted_tasks:
        task_versions = extract_version_numbers(task.name)
        if not task_versions:
            unmatched_tasks.append(task)
            match_log.append(f"SKIP: '{task.name[:50]}' — no version identifiers found")
            continue

        matched_ads: list[AdMetrics] = []
        matched_ids: list[str] = []
        for idx, ad in enumerate(ads):
            if idx in matched_ad_indices:
                continue
            ad_versions = extract_version_numbers(ad.ad_name)

            overlap = task_versions & ad_versions
            if overlap:
                matched_ads.append(ad)
                matched_ad_indices.add(idx)
                matched_ids.extend(sorted(overlap))
                match_log.append(
                    f"MATCH: CSV '{ad.ad_name[:50]}' <-> ClickUp '{task.name[:50]}' "
                    f"on [{', '.join(sorted(overlap))}] "
                    f"(ROAS={ad.roas:.2f}, Spend=${ad.spend:,.0f})"
                )

        if matched_ads:
            result = MatchResult(task=task, matched_ads=matched_ads, match_identifiers=matched_ids)
            result.total_spend = sum(a.spend for a in matched_ads)
            result.total_impressions = sum(a.impressions for a in matched_ads)
            result.total_conversions = sum(a.conversions for a in matched_ads)

            if result.total_spend > 0:
                result.weighted_roas = sum(
                    a.spend * a.roas for a in matched_ads
                ) / result.total_spend
            result.avg_roas = result.weighted_roas

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
            match_log.append(f"NO MATCH: '{task.name[:50]}' — identifiers {sorted(task_versions)} not found in CSV")

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
        match_log=match_log,
    )


def get_top_ads_by_spend(ads: list[AdMetrics], top_n: int = 50) -> list[AdMetrics]:
    """Return the top N ads by spend from the full CSV."""
    sorted_ads = sorted(ads, key=lambda a: a.spend, reverse=True)
    return sorted_ads[:top_n]
