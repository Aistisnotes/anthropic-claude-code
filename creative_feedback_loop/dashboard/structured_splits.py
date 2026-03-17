"""Structured dimension splits dashboard.

Computes breakdowns by dimension (pain point, avatar, mechanism, etc.)
with spend, ROAS, win/lose rates for each value.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


DIMENSIONS = [
    "pain_point",
    "symptoms",
    "avatar",
    "root_cause",
    "mechanism",
    "awareness_level",
    "ad_format",
]

DIMENSION_LABELS = {
    "pain_point": "Pain Points",
    "symptoms": "Symptoms",
    "avatar": "Avatar",
    "root_cause": "Root Cause",
    "mechanism": "Mechanism (UMP)",
    "awareness_level": "Awareness Level",
    "ad_format": "Ad Format",
}


def compute_dimension_breakdown(
    df: pd.DataFrame,
    dimension: str,
    winner_col: str = "classification",
    spend_col: str = "Amount Spent (USD)",
    roas_col: str = "ROAS (Purchase)",
) -> list[dict[str, Any]]:
    """Compute breakdown for a single dimension.

    Returns list of dicts with:
      value, pct_all, pct_win, pct_lose, avg_roas, total_spend
    sorted by total_spend descending.
    """
    if dimension not in df.columns or df[dimension].isna().all():
        return []

    total = len(df)
    winners = df[df[winner_col] == "Winner"] if winner_col in df.columns else pd.DataFrame()
    losers = df[df[winner_col] == "Loser"] if winner_col in df.columns else pd.DataFrame()
    total_winners = len(winners)
    total_losers = len(losers)

    rows = []
    for value, group in df.groupby(dimension, dropna=True):
        if pd.isna(value) or str(value).strip() == "" or str(value).lower() == "none":
            continue

        n = len(group)
        pct_all = round(n / total * 100) if total > 0 else 0

        win_count = len(group[group[winner_col] == "Winner"]) if winner_col in group.columns else 0
        lose_count = len(group[group[winner_col] == "Loser"]) if winner_col in group.columns else 0

        pct_win = round(win_count / total_winners * 100) if total_winners > 0 else 0
        pct_lose = round(lose_count / total_losers * 100) if total_losers > 0 else 0

        avg_roas = group[roas_col].mean() if roas_col in group.columns else 0
        total_spend = group[spend_col].sum() if spend_col in group.columns else 0

        rows.append({
            "value": str(value),
            "count": n,
            "pct_all": pct_all,
            "pct_win": pct_win,
            "pct_lose": pct_lose,
            "avg_roas": round(avg_roas, 2) if pd.notna(avg_roas) else 0,
            "total_spend": round(total_spend, 2) if pd.notna(total_spend) else 0,
        })

    # Sort by total_spend descending
    rows.sort(key=lambda x: x["total_spend"], reverse=True)
    return rows


def compute_all_dimensions(
    df: pd.DataFrame,
    winner_col: str = "classification",
    spend_col: str = "Amount Spent (USD)",
    roas_col: str = "ROAS (Purchase)",
) -> dict[str, list[dict[str, Any]]]:
    """Compute breakdowns for all dimensions.

    Returns dict keyed by dimension name.
    """
    result = {}
    for dim in DIMENSIONS:
        result[dim] = compute_dimension_breakdown(df, dim, winner_col, spend_col, roas_col)
    return result


def build_dimension_html_table(
    breakdown: list[dict[str, Any]],
    dimension_label: str,
    section_label: str = "Section A",
) -> str:
    """Build a dark-themed HTML table for a dimension breakdown.

    Args:
        breakdown: List of dicts from compute_dimension_breakdown
        dimension_label: Display name for the dimension
        section_label: Section A or Section B label

    Returns:
        HTML string for the table
    """
    if not breakdown:
        return f'<div style="color:#888; padding:8px;">No data for {dimension_label}</div>'

    header = f"""<table style="width:100%; border-collapse:collapse; background:#1e1e2e; border-radius:8px; overflow:hidden; margin-bottom:16px;">
  <thead>
    <tr style="background:#2d2d3d;">
      <th style="padding:10px 12px; text-align:left; color:#fafafa; font-weight:700; font-size:13px;">Value</th>
      <th style="padding:10px 12px; text-align:center; color:#fafafa; font-weight:700; font-size:13px;">% All</th>
      <th style="padding:10px 12px; text-align:center; color:#fafafa; font-weight:700; font-size:13px;">% Win</th>
      <th style="padding:10px 12px; text-align:center; color:#fafafa; font-weight:700; font-size:13px;">% Lose</th>
      <th style="padding:10px 12px; text-align:right; color:#fafafa; font-weight:700; font-size:13px;">Avg ROAS</th>
      <th style="padding:10px 12px; text-align:right; color:#fafafa; font-weight:700; font-size:13px;">Spend</th>
    </tr>
  </thead>
  <tbody>"""

    rows_html = ""
    for i, row in enumerate(breakdown):
        bg = "#1e1e2e" if i % 2 == 0 else "#262730"
        roas_color = "#4ade80" if row["avg_roas"] >= 1.0 else "#f87171"
        win_color = "#4ade80" if row["pct_win"] > row["pct_lose"] else "#f87171" if row["pct_win"] < row["pct_lose"] else "#fafafa"

        spend_display = _format_spend(row["total_spend"])

        rows_html += f"""
    <tr style="background:{bg};">
      <td style="padding:8px 12px; color:#fafafa; font-size:13px;">{_escape_html(row['value'])}</td>
      <td style="padding:8px 12px; text-align:center; color:#fafafa; font-size:13px;">{row['pct_all']}%</td>
      <td style="padding:8px 12px; text-align:center; color:{win_color}; font-size:13px;">{row['pct_win']}%</td>
      <td style="padding:8px 12px; text-align:center; color:#fafafa; font-size:13px;">{row['pct_lose']}%</td>
      <td style="padding:8px 12px; text-align:right; color:{roas_color}; font-size:13px; font-weight:600;">{row['avg_roas']:.2f}x</td>
      <td style="padding:8px 12px; text-align:right; color:#fafafa; font-size:13px;">&#36;{spend_display}</td>
    </tr>"""

    return header + rows_html + """
  </tbody>
</table>"""


def _format_spend(amount: float) -> str:
    """Format spend as human-readable (e.g., 183k, 1.2M)."""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M"
    elif amount >= 1_000:
        return f"{amount / 1_000:.0f}k"
    else:
        return f"{amount:.0f}"


def _escape_html(text: str) -> str:
    """Escape HTML special chars and dollar signs."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("$", "&#36;")
    )
