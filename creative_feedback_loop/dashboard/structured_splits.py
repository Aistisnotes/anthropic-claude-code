"""Structured percentage split dashboard for creative feedback loop.

Aggregates extracted ad components into dimension tables showing:
| Dimension | Value | % of All Ads | % of Winners | % of Losers | Delta (W-L) | Avg ROAS | Total Spend |

Displayed for both Section A (recent classified) and Section B (top 50 by spend).
Delta column is the key insight — color-coded green (>+15%), red (<-15%), neutral.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import streamlit as st

logger = logging.getLogger(__name__)

# Dimensions to extract and aggregate
DIMENSIONS = [
    ("pain_point", "Pain Points"),
    ("symptoms", "Symptoms"),
    ("root_cause_depth", "Root Cause Depth"),
    ("root_cause_chain", "Root Cause Chain"),
    ("mechanism_ump", "Mechanisms — UMP"),
    ("mechanism_ums", "Mechanisms — UMS"),
    ("ad_format", "Ad Formats"),
    ("avatar", "Avatars"),
    ("awareness_level", "Awareness Levels"),
    ("lead_type", "Lead Types"),
    ("hook_type", "Hook Patterns"),
    ("emotional_triggers", "Emotional Triggers"),
    ("language_patterns", "Language Patterns"),
]


def _get_dimension_values(extraction: dict, dim_key: str) -> list[str]:
    """Get values for a dimension from an extraction dict. Returns list of values."""
    if dim_key == "pain_point":
        val = extraction.get("pain_point", "")
        return [val] if val else []
    elif dim_key == "symptoms":
        return extraction.get("symptoms") or []
    elif dim_key == "root_cause_depth":
        depth = (extraction.get("root_cause") or {}).get("depth", "")
        return [depth] if depth else []
    elif dim_key == "root_cause_chain":
        chain = (extraction.get("root_cause") or {}).get("chain", "")
        return [chain] if chain else []
    elif dim_key == "mechanism_ump":
        ump = (extraction.get("mechanism") or {}).get("ump", "")
        return [ump] if ump else []
    elif dim_key == "mechanism_ums":
        ums = (extraction.get("mechanism") or {}).get("ums", "")
        return [ums] if ums else []
    elif dim_key == "ad_format":
        val = extraction.get("ad_format", "")
        return [val] if val else []
    elif dim_key == "avatar":
        avatar = extraction.get("avatar") or {}
        behavior = avatar.get("behavior", "")
        if behavior:
            impact = avatar.get("impact", "")
            if impact:
                return [f"{behavior} → {impact}"]
            return [behavior]
        return []
    elif dim_key == "awareness_level":
        val = extraction.get("awareness_level", "")
        return [val] if val else []
    elif dim_key == "lead_type":
        val = extraction.get("lead_type", "")
        return [val] if val else []
    elif dim_key == "hook_type":
        val = extraction.get("hook_type", "")
        return [val] if val else []
    elif dim_key == "emotional_triggers":
        return extraction.get("emotional_triggers") or []
    elif dim_key == "language_patterns":
        return extraction.get("language_patterns") or []
    return []


def build_dimension_table(
    ads_with_extractions: list[dict[str, Any]],
    dim_key: str,
) -> list[dict[str, Any]]:
    """Build a single dimension table from a list of ads with extractions.

    Each ad dict should have:
      - extraction: dict (from script_component_extractor)
      - status: str ("winner" | "loser" | "untested")
      - spend: float
      - roas: float

    Returns list of row dicts sorted by absolute delta descending.
    """
    total_ads = len(ads_with_extractions)
    if total_ads == 0:
        return []

    winners = [a for a in ads_with_extractions if a.get("status") == "winner"]
    losers = [a for a in ads_with_extractions if a.get("status") == "loser"]
    total_winners = len(winners)
    total_losers = len(losers)

    # Count occurrences per value
    value_stats: dict[str, dict] = defaultdict(lambda: {
        "all_count": 0,
        "winner_count": 0,
        "loser_count": 0,
        "total_spend": 0.0,
        "roas_sum": 0.0,
        "roas_count": 0,
    })

    for ad in ads_with_extractions:
        extraction = ad.get("extraction") or {}
        values = _get_dimension_values(extraction, dim_key)
        status = ad.get("status", "untested")
        spend = ad.get("spend", 0.0) or 0.0
        roas = ad.get("roas", 0.0) or 0.0

        for val in values:
            if not val:
                continue
            # Truncate long values for display
            display_val = val[:80] + "..." if len(val) > 80 else val
            stats = value_stats[display_val]
            stats["all_count"] += 1
            stats["total_spend"] += spend
            if roas > 0:
                stats["roas_sum"] += roas
                stats["roas_count"] += 1
            if status == "winner":
                stats["winner_count"] += 1
            elif status == "loser":
                stats["loser_count"] += 1

    # Build rows
    rows = []
    for value, stats in value_stats.items():
        pct_all = (stats["all_count"] / total_ads * 100) if total_ads > 0 else 0
        pct_winners = (stats["winner_count"] / total_winners * 100) if total_winners > 0 else 0
        pct_losers = (stats["loser_count"] / total_losers * 100) if total_losers > 0 else 0
        delta = pct_winners - pct_losers
        avg_roas = (stats["roas_sum"] / stats["roas_count"]) if stats["roas_count"] > 0 else 0

        rows.append({
            "value": value,
            "pct_all": round(pct_all, 1),
            "pct_winners": round(pct_winners, 1),
            "pct_losers": round(pct_losers, 1),
            "delta": round(delta, 1),
            "avg_roas": round(avg_roas, 2),
            "total_spend": round(stats["total_spend"], 2),
        })

    # Sort by absolute delta descending
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows


def build_all_dimensions(
    ads_with_extractions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build tables for all dimensions.

    Returns dict mapping dimension key to list of rows.
    """
    result = {}
    for dim_key, _label in DIMENSIONS:
        rows = build_dimension_table(ads_with_extractions, dim_key)
        if rows:
            result[dim_key] = rows
    return result


def render_dimension_table(
    rows: list[dict[str, Any]],
    title: str,
) -> None:
    """Render a single dimension table in Streamlit with color-coded deltas."""
    if not rows:
        return

    st.markdown(f"#### {title}")

    # Build HTML table
    html = """<table style="width:100%; border-collapse:collapse; margin-bottom:20px; font-size:13px;">
    <thead>
        <tr style="border-bottom:2px solid #444;">
            <th style="text-align:left; padding:8px; color:#fafafa;">Value</th>
            <th style="text-align:right; padding:8px; color:#fafafa;">% All</th>
            <th style="text-align:right; padding:8px; color:#fafafa;">% Winners</th>
            <th style="text-align:right; padding:8px; color:#fafafa;">% Losers</th>
            <th style="text-align:right; padding:8px; color:#fafafa;">Delta (W-L)</th>
            <th style="text-align:right; padding:8px; color:#fafafa;">Avg ROAS</th>
            <th style="text-align:right; padding:8px; color:#fafafa;">Total Spend</th>
        </tr>
    </thead>
    <tbody>"""

    for row in rows:
        delta = row["delta"]
        if delta > 15:
            delta_color = "#4caf50"  # green
        elif delta < -15:
            delta_color = "#ef5350"  # red
        else:
            delta_color = "#999"  # neutral

        delta_prefix = "+" if delta > 0 else ""

        html += f"""
        <tr style="border-bottom:1px solid #333;">
            <td style="padding:6px 8px; color:#fafafa; max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{row['value']}</td>
            <td style="text-align:right; padding:6px 8px; color:#ccc;">{row['pct_all']}%</td>
            <td style="text-align:right; padding:6px 8px; color:#4caf50;">{row['pct_winners']}%</td>
            <td style="text-align:right; padding:6px 8px; color:#ef5350;">{row['pct_losers']}%</td>
            <td style="text-align:right; padding:6px 8px; color:{delta_color}; font-weight:bold;">{delta_prefix}{delta}%</td>
            <td style="text-align:right; padding:6px 8px; color:#fafafa;">{row['avg_roas']:.2f}x</td>
            <td style="text-align:right; padding:6px 8px; color:#fafafa;">${row['total_spend']:,.0f}</td>
        </tr>"""

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


def render_dashboard(
    ads_with_extractions: list[dict[str, Any]],
    section_label: str = "Section A",
) -> dict[str, list[dict[str, Any]]]:
    """Render the full structured dashboard for a set of ads.

    Args:
        ads_with_extractions: List of ad dicts with extraction data.
        section_label: Label for the dashboard section.

    Returns:
        The dimension tables dict for storage/comparison.
    """
    st.markdown(f"### {section_label} — Structured Dashboard")

    total = len(ads_with_extractions)
    winners = sum(1 for a in ads_with_extractions if a.get("status") == "winner")
    losers = sum(1 for a in ads_with_extractions if a.get("status") == "loser")
    untested = total - winners - losers

    st.markdown(
        f'<div style="color:#fafafa; margin-bottom:16px;">'
        f'Total Ads: <b>{total}</b> &nbsp;|&nbsp; '
        f'<span style="color:#4caf50;">Winners: {winners}</span> &nbsp;|&nbsp; '
        f'<span style="color:#ef5350;">Losers: {losers}</span> &nbsp;|&nbsp; '
        f'Untested: {untested}</div>',
        unsafe_allow_html=True,
    )

    all_tables = build_all_dimensions(ads_with_extractions)

    for dim_key, dim_label in DIMENSIONS:
        if dim_key in all_tables:
            render_dimension_table(all_tables[dim_key], dim_label)

    return all_tables
