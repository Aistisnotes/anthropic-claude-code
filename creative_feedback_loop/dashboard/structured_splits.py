"""Visual card dashboard for creative performance analysis.

Replaces scrollable dataframe tables with compact visual cards:
- Compact Summary Cards (one screen, 10-second read)
- Expandable Detailed Breakdowns (collapsed by default)
- Dark theme styling throughout

NEVER uses st.dataframe(). All display via st.markdown(unsafe_allow_html=True).
"""

from __future__ import annotations

from typing import Any

import streamlit as st


# ── Color Constants ──────────────────────────────────────────────────────────
CARD_BG = "#1e1e2e"
TABLE_BG = "#262730"
TABLE_ALT = "#2d2d3d"
TABLE_HEADER = "#1e1e2e"
TEXT_COLOR = "#fafafa"
TEXT_MUTED = "#ccc"
GREEN = "#22c55e"
YELLOW = "#f59e0b"
RED = "#ef4444"
GRAY = "#6b7280"
BLUE = "#3b82f6"
PURPLE = "#8b5cf6"


def _signal_color(delta: float) -> tuple[str, str, str]:
    """Return (color, emoji, label) based on delta value."""
    if delta > 20:
        return GREEN, "🟢", "HIGH SIGNAL"
    elif delta > 10:
        return YELLOW, "🟡", "MEDIUM"
    elif delta >= 0:
        return GRAY, "⚪", "BASELINE"
    else:
        return RED, "🔴", "AVOID"


def _format_spend(amount: float) -> str:
    """Format spend amount."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    elif amount >= 1_000:
        return f"${amount / 1_000:.0f}k"
    else:
        return f"${amount:.0f}"


def _format_roas(roas: float) -> str:
    """Format ROAS value."""
    return f"{roas:.2f}x"


def _card_html(
    color: str,
    type_label: str,
    title: str,
    content: str,
) -> str:
    """Generate styled card HTML."""
    return f"""<div style="background: {CARD_BG}; border-left: 4px solid {color}; border-radius: 8px; padding: 16px 20px; margin: 12px 0;">
  <div style="color: {color}; font-size: 13px; font-weight: 600; text-transform: uppercase; margin-bottom: 4px;">
    {type_label}
  </div>
  <div style="color: {TEXT_COLOR}; font-size: 18px; font-weight: 700; margin-bottom: 12px;">
    {title}
  </div>
  <div style="color: {TEXT_MUTED}; font-size: 14px; line-height: 1.6;">
    {content}
  </div>
</div>"""


def render_header_metrics(ads_data: dict[str, Any]) -> None:
    """Render header metrics row with st.metric."""
    cols = st.columns(6)
    with cols[0]:
        st.metric("Total Ads", ads_data.get("total", 0))
    with cols[1]:
        st.metric("Winners", ads_data.get("winners", 0))
    with cols[2]:
        st.metric("Losers", ads_data.get("losers", 0))
    with cols[3]:
        st.metric("Untested", ads_data.get("untested", 0))
    with cols[4]:
        st.metric("Total Spend", _format_spend(ads_data.get("total_spend", 0)))
    with cols[5]:
        st.metric("Avg ROAS", _format_roas(ads_data.get("avg_roas", 0)))


def render_compact_summary(dimension_data: list[dict[str, Any]], title: str = "DIMENSION SUMMARY") -> None:
    """Render compact summary cards — one card per dimension showing top pattern.

    Args:
        dimension_data: List of dicts with keys:
            - dimension: str (e.g., "Pain Point", "Root Cause")
            - top_value: str (e.g., "Kidney", "Molecular")
            - winner_pct: float (0-100)
            - loser_pct: float (0-100)
            - delta: float (winner_pct - loser_pct)
            - spend: float
            - avg_roas: float
        title: Section title
    """
    st.markdown(
        f'<div style="color: {TEXT_COLOR}; font-size: 20px; font-weight: 700; margin: 20px 0 10px 0;">{title}</div>',
        unsafe_allow_html=True,
    )

    for dim in dimension_data:
        delta = dim.get("delta", 0)
        color, emoji, label = _signal_color(delta)
        dimension_name = dim.get("dimension", "")
        top_value = dim.get("top_value", "")
        win_pct = dim.get("winner_pct", 0)
        lose_pct = dim.get("loser_pct", 0)
        spend = dim.get("spend", 0)
        avg_roas = dim.get("avg_roas", 0)

        delta_sign = "+" if delta >= 0 else ""

        html = f"""<div style="background: {CARD_BG}; border-left: 4px solid {color}; border-radius: 8px; padding: 12px 20px; margin: 6px 0; display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
  <div style="color: {TEXT_COLOR}; font-weight: 700; min-width: 130px; font-size: 14px;">
    {emoji} {dimension_name}
  </div>
  <div style="color: {color}; font-weight: 600; min-width: 160px; font-size: 15px;">
    {top_value}
  </div>
  <div style="color: {TEXT_MUTED}; font-size: 13px; display: flex; gap: 16px; flex-wrap: wrap;">
    <span>Winners: <b style="color: {TEXT_COLOR};">{win_pct:.0f}%</b></span>
    <span>Losers: <b style="color: {TEXT_COLOR};">{lose_pct:.0f}%</b></span>
    <span>Delta: <b style="color: {color};">{delta_sign}{delta:.0f}%</b></span>
    <span>Spend: <b style="color: {TEXT_COLOR};">{_format_spend(spend)}</b></span>
    <span>ROAS: <b style="color: {TEXT_COLOR};">{_format_roas(avg_roas)}</b></span>
  </div>
</div>"""
        st.markdown(html, unsafe_allow_html=True)


def render_detailed_breakdown(
    dimensions: dict[str, list[dict[str, Any]]],
    section_title: str = "Full Dimension Breakdown",
) -> None:
    """Render expandable detailed breakdown tables inside an expander.

    Args:
        dimensions: Dict mapping dimension name to list of value dicts:
            Each value dict has: value, winner_pct, loser_pct, delta, avg_roas, spend
    """
    with st.expander(f"📊 {section_title}", expanded=False):
        for dim_name, values in dimensions.items():
            if not values:
                continue

            # Sort by delta descending
            sorted_vals = sorted(values, key=lambda x: x.get("delta", 0), reverse=True)

            # Build HTML table
            rows_html = ""
            for i, v in enumerate(sorted_vals):
                bg = TABLE_BG if i % 2 == 0 else TABLE_ALT
                delta = v.get("delta", 0)
                delta_color = GREEN if delta > 0 else RED if delta < 0 else GRAY
                delta_sign = "+" if delta >= 0 else ""

                rows_html += f"""<tr style="background: {bg};">
  <td style="padding: 8px 12px; color: {TEXT_COLOR}; font-weight: 500;">{v.get('value', '')}</td>
  <td style="padding: 8px 12px; color: {TEXT_COLOR}; text-align: center;">{v.get('winner_pct', 0):.0f}%</td>
  <td style="padding: 8px 12px; color: {TEXT_COLOR}; text-align: center;">{v.get('loser_pct', 0):.0f}%</td>
  <td style="padding: 8px 12px; color: {delta_color}; text-align: center; font-weight: 600;">{delta_sign}{delta:.0f}%</td>
  <td style="padding: 8px 12px; color: {TEXT_COLOR}; text-align: center;">{_format_roas(v.get('avg_roas', 0))}</td>
  <td style="padding: 8px 12px; color: {TEXT_COLOR}; text-align: right;">{_format_spend(v.get('spend', 0))}</td>
</tr>"""

            table_html = f"""<div style="margin: 16px 0;">
  <div style="color: {TEXT_COLOR}; font-size: 16px; font-weight: 700; margin-bottom: 8px; text-transform: uppercase;">{dim_name}</div>
  <table style="width: 100%; border-collapse: collapse; border-radius: 8px; overflow: hidden;">
    <thead>
      <tr style="background: {TABLE_HEADER};">
        <th style="padding: 10px 12px; color: {TEXT_COLOR}; text-align: left; font-weight: 700;">{dim_name}</th>
        <th style="padding: 10px 12px; color: {TEXT_COLOR}; text-align: center; font-weight: 700;">Win %</th>
        <th style="padding: 10px 12px; color: {TEXT_COLOR}; text-align: center; font-weight: 700;">Lose %</th>
        <th style="padding: 10px 12px; color: {TEXT_COLOR}; text-align: center; font-weight: 700;">Delta</th>
        <th style="padding: 10px 12px; color: {TEXT_COLOR}; text-align: center; font-weight: 700;">Avg ROAS</th>
        <th style="padding: 10px 12px; color: {TEXT_COLOR}; text-align: right; font-weight: 700;">Spend</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>"""
            st.markdown(table_html, unsafe_allow_html=True)


def render_opportunity_card(opp: dict[str, Any]) -> None:
    """Render a single strategic opportunity card.

    Args:
        opp: Dict with keys:
            - score: int (0-100)
            - type: str (scale_winner, efficiency_gap, undertested, expensive_mistake, combination)
            - title: str
            - evidence: str
            - loser_comparison: str
            - why_it_works: str
            - how_to_execute: str (or dict)
            - risk: str
    """
    opp_type = opp.get("type", "scale_winner")
    color_map = {
        "scale_winner": GREEN,
        "efficiency_gap": BLUE,
        "undertested": YELLOW,
        "expensive_mistake": RED,
        "combination": PURPLE,
    }
    label_map = {
        "scale_winner": "SCALE WINNER",
        "efficiency_gap": "EFFICIENCY GAP",
        "undertested": "UNDERTESTED ANGLE",
        "expensive_mistake": "EXPENSIVE MISTAKE",
        "combination": "COMBINATION PLAY",
    }
    color = color_map.get(opp_type, GRAY)
    label = label_map.get(opp_type, opp_type.upper())
    score = opp.get("score", 0)

    # Build content sections
    sections = []

    evidence = opp.get("evidence", "")
    if evidence:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>THE EVIDENCE:</b><br/>{evidence}</div>")

    loser_comp = opp.get("loser_comparison", "")
    if loser_comp:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>WHAT LOSERS DID INSTEAD:</b><br/>{loser_comp}</div>")

    why = opp.get("why_it_works", "")
    if why:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>WHY IT WORKS:</b><br/>{why}</div>")

    how = opp.get("how_to_execute", "")
    if isinstance(how, dict):
        how_lines = "<br/>".join(f"<b>{k}:</b> {v}" for k, v in how.items())
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>HOW TO EXECUTE:</b><br/>{how_lines}</div>")
    elif how:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>HOW TO EXECUTE:</b><br/>{how}</div>")

    risk = opp.get("risk", "")
    if risk:
        sections.append(f"<div><b style='color: {TEXT_COLOR};'>RISK:</b> {risk}</div>")

    content = "\n".join(sections)

    html = f"""<div style="background: {CARD_BG}; border-left: 4px solid {color}; border-radius: 8px; padding: 16px 20px; margin: 12px 0;">
  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
    <div style="color: {color}; font-size: 13px; font-weight: 600; text-transform: uppercase;">{label}</div>
    <div style="color: {color}; font-size: 15px; font-weight: 700;">SCORE: {score}/100</div>
  </div>
  <div style="color: {TEXT_COLOR}; font-size: 18px; font-weight: 700; margin-bottom: 12px;">
    {opp.get('title', '')}
  </div>
  <div style="color: {TEXT_MUTED}; font-size: 14px; line-height: 1.6;">
    {content}
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def render_expensive_mistake_card(mistake: dict[str, Any]) -> None:
    """Render an expensive mistake card with red styling.

    Args:
        mistake: Dict with keys: title, cost, pattern, worst_offenders, what_to_do, action
    """
    sections = []

    cost = mistake.get("cost", "")
    if cost:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>COST:</b> {cost}</div>")

    pattern = mistake.get("pattern", "")
    if pattern:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>THE PATTERN:</b><br/>{pattern}</div>")

    offenders = mistake.get("worst_offenders", "")
    if offenders:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>WORST OFFENDERS:</b> {offenders}</div>")

    alternative = mistake.get("what_to_do", "")
    if alternative:
        sections.append(f"<div style='margin-bottom: 12px;'><b style='color: {TEXT_COLOR};'>WHAT TO DO INSTEAD:</b><br/>{alternative}</div>")

    action = mistake.get("action", "")
    if action:
        sections.append(f"<div style='color: {RED}; font-weight: 600;'>ACTION: {action}</div>")

    content = "\n".join(sections)
    html = _card_html(RED, "EXPENSIVE MISTAKE", mistake.get("title", ""), content)
    st.markdown(html, unsafe_allow_html=True)


def render_drift_alert_card(drift: dict[str, Any]) -> None:
    """Render a drift alert card for recent vs top 50 comparison.

    Args:
        drift: Dict with keys:
            - type: str (drift, consistent, new_discovery)
            - title: str
            - top50_stat: str
            - recent_stat: str
            - impact: str
            - recommendation: str
    """
    drift_type = drift.get("type", "drift")
    type_config = {
        "drift": (YELLOW, "⚠️ DRIFT", "DRIFT ALERT"),
        "consistent": (GREEN, "✅ CONSISTENT", "CONSISTENT"),
        "new_discovery": (PURPLE, "🆕 NEW", "NEW DISCOVERY"),
    }
    color, emoji_label, type_label = type_config.get(drift_type, (YELLOW, "⚠️", "ALERT"))

    sections = []

    top50 = drift.get("top50_stat", "")
    recent = drift.get("recent_stat", "")
    if top50 and recent:
        sections.append(f"<div style='margin-bottom: 8px;'>Top 50: {top50}</div>")
        sections.append(f"<div style='margin-bottom: 12px;'>Recent: {recent}</div>")

    impact = drift.get("impact", "")
    if impact:
        sections.append(f"<div style='margin-bottom: 12px;'>{impact}</div>")

    rec = drift.get("recommendation", "")
    if rec:
        sections.append(f"<div><b style='color: {TEXT_COLOR};'>RECOMMENDATION:</b> {rec}</div>")

    content = "\n".join(sections)
    html = _card_html(color, type_label, drift.get("title", ""), content)
    st.markdown(html, unsafe_allow_html=True)


def render_opportunities_section(opportunities: list[dict[str, Any]]) -> None:
    """Render the full strategic opportunities section.

    Renders opportunities sorted by score, then expensive mistakes separately.
    """
    # Split into opportunities and mistakes
    opps = [o for o in opportunities if o.get("type") != "expensive_mistake"]
    mistakes = [o for o in opportunities if o.get("type") == "expensive_mistake"]

    # Sort opportunities by score
    opps.sort(key=lambda x: x.get("score", 0), reverse=True)

    if opps:
        st.markdown(
            f'<div style="color: {TEXT_COLOR}; font-size: 20px; font-weight: 700; margin: 24px 0 10px 0;">STRATEGIC OPPORTUNITIES</div>',
            unsafe_allow_html=True,
        )
        for opp in opps:
            render_opportunity_card(opp)

    if mistakes:
        st.markdown(
            f'<div style="color: {RED}; font-size: 20px; font-weight: 700; margin: 24px 0 10px 0;">EXPENSIVE MISTAKES</div>',
            unsafe_allow_html=True,
        )
        for m in mistakes:
            render_expensive_mistake_card(m)


def render_drift_alerts(drifts: list[dict[str, Any]]) -> None:
    """Render drift alert cards for recent vs top 50 comparison."""
    if not drifts:
        return

    st.markdown(
        f'<div style="color: {TEXT_COLOR}; font-size: 20px; font-weight: 700; margin: 24px 0 10px 0;">DRIFT ALERTS: Recent vs Top 50</div>',
        unsafe_allow_html=True,
    )
    for drift in drifts:
        render_drift_alert_card(drift)


def compute_dimension_summary(
    ads_df: "pd.DataFrame",
    dimension_col: str,
    dimension_label: str,
    winner_mask: "pd.Series",
    loser_mask: "pd.Series",
) -> dict[str, Any]:
    """Compute summary for one dimension from the dataframe.

    Args:
        ads_df: DataFrame with ad data
        dimension_col: Column name for the dimension values
        dimension_label: Human-readable label (e.g., "Pain Point")
        winner_mask: Boolean mask for winner ads
        loser_mask: Boolean mask for loser ads

    Returns:
        Dict with dimension, top_value, winner_pct, loser_pct, delta, spend, avg_roas
    """
    import pandas as pd

    if dimension_col not in ads_df.columns:
        return {
            "dimension": dimension_label,
            "top_value": "N/A",
            "winner_pct": 0,
            "loser_pct": 0,
            "delta": 0,
            "spend": 0,
            "avg_roas": 0,
        }

    winners = ads_df[winner_mask]
    losers = ads_df[loser_mask]
    total_winners = len(winners)
    total_losers = len(losers)

    if total_winners == 0:
        return {
            "dimension": dimension_label,
            "top_value": "N/A",
            "winner_pct": 0,
            "loser_pct": 0,
            "delta": 0,
            "spend": 0,
            "avg_roas": 0,
        }

    # Get all unique values
    all_values = ads_df[dimension_col].dropna().unique()

    best_delta = -999
    best_result = None

    for val in all_values:
        if not val or str(val).lower() in ("unknown", "not specified", "nan", "none", ""):
            continue

        win_count = len(winners[winners[dimension_col] == val])
        lose_count = len(losers[losers[dimension_col] == val]) if total_losers > 0 else 0

        win_pct = (win_count / total_winners * 100) if total_winners > 0 else 0
        lose_pct = (lose_count / total_losers * 100) if total_losers > 0 else 0
        delta = win_pct - lose_pct

        val_ads = ads_df[ads_df[dimension_col] == val]
        spend = val_ads["spend"].sum() if "spend" in val_ads.columns else 0
        avg_roas = val_ads["roas"].mean() if "roas" in val_ads.columns and len(val_ads) > 0 else 0

        if abs(delta) > abs(best_delta) or best_result is None:
            best_delta = delta
            best_result = {
                "dimension": dimension_label,
                "top_value": str(val),
                "winner_pct": win_pct,
                "loser_pct": lose_pct,
                "delta": delta,
                "spend": spend,
                "avg_roas": avg_roas,
            }

    return best_result or {
        "dimension": dimension_label,
        "top_value": "N/A",
        "winner_pct": 0,
        "loser_pct": 0,
        "delta": 0,
        "spend": 0,
        "avg_roas": 0,
    }


def compute_detailed_breakdown(
    ads_df: "pd.DataFrame",
    dimension_col: str,
    winner_mask: "pd.Series",
    loser_mask: "pd.Series",
) -> list[dict[str, Any]]:
    """Compute detailed breakdown for one dimension.

    Returns list of dicts with: value, winner_pct, loser_pct, delta, avg_roas, spend
    """
    if dimension_col not in ads_df.columns:
        return []

    winners = ads_df[winner_mask]
    losers = ads_df[loser_mask]
    total_winners = len(winners)
    total_losers = len(losers)

    results = []
    for val in ads_df[dimension_col].dropna().unique():
        if not val or str(val).lower() in ("unknown", "not specified", "nan", "none", ""):
            continue

        win_count = len(winners[winners[dimension_col] == val])
        lose_count = len(losers[losers[dimension_col] == val]) if total_losers > 0 else 0

        win_pct = (win_count / total_winners * 100) if total_winners > 0 else 0
        lose_pct = (lose_count / total_losers * 100) if total_losers > 0 else 0

        val_ads = ads_df[ads_df[dimension_col] == val]
        spend = val_ads["spend"].sum() if "spend" in val_ads.columns else 0
        avg_roas = val_ads["roas"].mean() if "roas" in val_ads.columns and len(val_ads) > 0 else 0

        results.append({
            "value": str(val),
            "winner_pct": win_pct,
            "loser_pct": lose_pct,
            "delta": win_pct - lose_pct,
            "avg_roas": avg_roas,
            "spend": spend,
        })

    return results


def render_dashboard(ads_data: list, title: str = "Dashboard") -> dict:
    """Backward-compatible wrapper called from app.py with a list of ad dicts.

    Each ad dict has: ad_name, status, spend, roas, extraction (optional).
    Builds a DataFrame, computes dimension summaries, and renders them.
    """
    import pandas as pd
    import streamlit as st

    if not ads_data:
        st.info(f"No ads to display for {title}.")
        return {}

    # Build flat DataFrame from list of ad dicts
    rows = []
    for ad in ads_data:
        ext = ad.get("extraction") or ad.get("naming_extraction") or {}
        rows.append({
            "ad_name": ad.get("ad_name", ""),
            "status": ad.get("status", "untested"),
            "spend": float(ad.get("spend", 0)),
            "roas": float(ad.get("roas", 0)),
            "pain_point": ext.get("pain_point", "") or ext.get("pain_point_category", ""),
            "root_cause": ext.get("root_cause", "") if isinstance(ext.get("root_cause"), str) else ext.get("root_cause", {}).get("depth", ""),
            "mechanism": ext.get("mechanism", "") if isinstance(ext.get("mechanism"), str) else ext.get("mechanism", {}).get("ump", ""),
            "ad_format": ext.get("ad_format", ""),
            "awareness_level": ext.get("awareness_level", ""),
            "hook_type": ext.get("hook_type", ""),
        })
    df = pd.DataFrame(rows)

    winner_mask = df["status"] == "winner"
    loser_mask = df["status"] == "loser"

    dimension_cols = [
        ("pain_point", "Pain Point"),
        ("root_cause", "Root Cause"),
        ("mechanism", "Mechanism"),
        ("ad_format", "Ad Format"),
        ("awareness_level", "Awareness Level"),
        ("hook_type", "Hook Type"),
    ]

    st.markdown(f'<div style="color:#fafafa; font-size:18px; font-weight:700; margin:16px 0 8px 0;">{title}</div>', unsafe_allow_html=True)

    dimension_data = []
    detailed_data = {}
    for col, label in dimension_cols:
        if col in df.columns and df[col].astype(str).str.strip().replace("", float("nan")).dropna().shape[0] > 0:
            summary = compute_dimension_summary(df, col, label, winner_mask, loser_mask)
            dimension_data.append(summary)
            breakdown = compute_detailed_breakdown(df, col, winner_mask, loser_mask)
            if breakdown:
                detailed_data[label] = breakdown

    if dimension_data:
        render_compact_summary(dimension_data, title)
    if detailed_data:
        render_detailed_breakdown(detailed_data, title)

    return {"dimensions": dimension_data, "title": title, "detailed": detailed_data}
