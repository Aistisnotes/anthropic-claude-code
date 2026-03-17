"""PDF report generator for Creative Feedback Loop.

Uses Jinja2 + Playwright for HTML -> PDF conversion.
Dark theme matching the Streamlit UI.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _format_spend(amount: float) -> str:
    """Format spend as human-readable."""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M"
    elif amount >= 1_000:
        return f"{amount / 1_000:.0f}k"
    else:
        return f"{amount:.0f}"


def _escape(text: str) -> str:
    """Escape HTML and dollar signs."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("$", "&#36;")
    )


def _build_html_report(
    brand_name: str,
    classified_df: pd.DataFrame,
    top50_df: pd.DataFrame,
    classified_dims: dict[str, list],
    top50_dims: dict[str, list],
    results: dict[str, Any],
) -> str:
    """Build the full HTML report string."""

    total_ads = len(classified_df)
    winners = len(classified_df[classified_df["classification"] == "Winner"]) if "classification" in classified_df.columns else 0
    losers = len(classified_df[classified_df["classification"] == "Loser"]) if "classification" in classified_df.columns else 0
    total_spend = classified_df["Amount Spent (USD)"].sum() if "Amount Spent (USD)" in classified_df.columns else 0
    avg_roas = classified_df["ROAS (Purchase)"].mean() if "ROAS (Purchase)" in classified_df.columns else 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build dimension tables HTML
    dim_labels = {
        "pain_point": "Pain Points",
        "symptoms": "Symptoms",
        "avatar": "Avatar",
        "root_cause": "Root Cause",
        "mechanism": "Mechanism (UMP)",
        "awareness_level": "Awareness Level",
        "ad_format": "Ad Format",
    }

    def _dim_table_html(dims: dict, section: str) -> str:
        html = ""
        for dim_key, dim_label in dim_labels.items():
            rows = dims.get(dim_key, [])
            if not rows:
                continue
            html += f'<h3 style="color:#fafafa; margin-top:20px;">{_escape(dim_label)} ({section})</h3>'
            html += '<table style="width:100%; border-collapse:collapse; margin-bottom:16px;">'
            html += '<tr style="background:#2d2d3d;">'
            html += '<th style="padding:8px; color:#fafafa; text-align:left;">Value</th>'
            html += '<th style="padding:8px; color:#fafafa; text-align:center;">% All</th>'
            html += '<th style="padding:8px; color:#fafafa; text-align:center;">% Win</th>'
            html += '<th style="padding:8px; color:#fafafa; text-align:center;">% Lose</th>'
            html += '<th style="padding:8px; color:#fafafa; text-align:right;">Avg ROAS</th>'
            html += '<th style="padding:8px; color:#fafafa; text-align:right;">Spend</th>'
            html += '</tr>'
            for i, row in enumerate(rows):
                bg = "#1e1e2e" if i % 2 == 0 else "#262730"
                roas_color = "#4ade80" if row.get("avg_roas", 0) >= 1.0 else "#f87171"
                html += f'<tr style="background:{bg};">'
                html += f'<td style="padding:6px 8px; color:#fafafa;">{_escape(row.get("value", ""))}</td>'
                html += f'<td style="padding:6px 8px; color:#fafafa; text-align:center;">{row.get("pct_all", 0)}%</td>'
                html += f'<td style="padding:6px 8px; color:#fafafa; text-align:center;">{row.get("pct_win", 0)}%</td>'
                html += f'<td style="padding:6px 8px; color:#fafafa; text-align:center;">{row.get("pct_lose", 0)}%</td>'
                html += f'<td style="padding:6px 8px; color:{roas_color}; text-align:right;">{row.get("avg_roas", 0):.2f}x</td>'
                html += f'<td style="padding:6px 8px; color:#fafafa; text-align:right;">&#36;{_format_spend(row.get("total_spend", 0))}</td>'
                html += '</tr>'
            html += '</table>'
        return html

    classified_tables = _dim_table_html(classified_dims, "Section A")
    top50_tables = _dim_table_html(top50_dims, "Section B")

    # Build insight cards HTML
    insights_html = ""
    for i, insight in enumerate(results.get("insights", []), 1):
        w = insight.get("winner_data", {})
        l = insight.get("loser_data", {})
        insights_html += f"""
        <div style="background:#1e1e2e; border-radius:12px; padding:20px; margin-bottom:16px; border:1px solid #333; page-break-inside:avoid;">
          <div style="margin-bottom:8px;">
            <span style="background:#e91e8c; color:white; padding:4px 12px; border-radius:6px; font-size:13px; font-weight:600;">
              PATTERN #{i} — Score: {insight.get("score", 0)}/100
            </span>
          </div>
          <h3 style="color:#fafafa; margin:8px 0; font-size:16px;">{_escape(insight.get("title", ""))}</h3>
          <p style="color:#ccc; font-size:13px; line-height:1.6;">{_escape(insight.get("description", ""))}</p>
          <div style="display:flex; gap:16px; margin:8px 0;">
            <div style="flex:1; background:#262730; padding:8px; border-radius:6px;">
              <div style="color:#888; font-size:10px;">EVIDENCE FROM</div>
              <div style="color:#fafafa; font-size:12px;">{_escape(str(insight.get("evidence_from", "")))}</div>
            </div>
            <div style="flex:1; background:#262730; padding:8px; border-radius:6px;">
              <div style="color:#888; font-size:10px;">CONFIDENCE</div>
              <div style="color:#fafafa; font-size:12px;">{_escape(str(insight.get("confidence", "")))}</div>
            </div>
          </div>
          <div style="background:#262730; padding:8px; border-radius:6px;">
            <div style="color:#888; font-size:10px;">DATA</div>
            <div style="color:#fafafa; font-size:12px;">
              Winners: {w.get("count", 0)} ads | &#36;{w.get("total_spend", 0):,.0f} | {w.get("avg_roas", 0):.2f}x ROAS<br>
              Losers: {l.get("count", 0)} ads | &#36;{l.get("total_spend", 0):,.0f} | {l.get("avg_roas", 0):.2f}x ROAS
            </div>
          </div>
        </div>"""

    # Top patterns
    top_patterns_html = ""
    for i, pat in enumerate(results.get("top_patterns", [])[:5], 1):
        exps = "".join(f"<div style='color:#ccc; font-size:12px; margin-top:2px;'>→ {_escape(str(e))}</div>" for e in pat.get("expansion_opportunities", []))
        top_patterns_html += f"""
        <div style="background:#1e1e2e; border-radius:12px; padding:16px; margin-bottom:12px; border:1px solid #f59e0b; page-break-inside:avoid;">
          <span style="background:#f59e0b; color:#000; padding:4px 10px; border-radius:6px; font-size:12px; font-weight:600;">TOP #{i}</span>
          <h4 style="color:#fafafa; margin:8px 0 4px;">{_escape(str(pat.get("pattern", "")))}</h4>
          <div style="color:#888; font-size:12px;">&#36;{pat.get("total_spend", 0):,.0f} spend | {pat.get("avg_roas", 0):.2f}x ROAS | {_escape(str(pat.get("hit_rate", "")))}</div>
          <div style="background:#262730; padding:8px; border-radius:6px; margin-top:8px;">{exps}</div>
        </div>"""

    # Learnings
    learnings_html = ""
    for learning in results.get("learnings", []):
        learnings_html += f"""
        <div style="background:#1e1e2e; border-left:3px solid #3b82f6; padding:12px 16px; margin-bottom:8px; border-radius:0 8px 8px 0; page-break-inside:avoid;">
          <div style="color:#fafafa; font-weight:600; font-size:13px;">{_escape(str(learning.get("title", "")))}</div>
          <div style="color:#ccc; font-size:12px; margin-top:4px;">{_escape(str(learning.get("description", "")))}</div>
          <div style="color:#888; font-size:10px; margin-top:4px;">Confidence: {_escape(str(learning.get("confidence", "")))} | Hit rate: {_escape(str(learning.get("hit_rate", "")))}</div>
        </div>"""

    # Hypotheses
    hypotheses_html = ""
    for hyp in results.get("hypotheses", []):
        based = ", ".join(str(a) for a in hyp.get("based_on_ads", []))
        hypotheses_html += f"""
        <div style="background:#1e1e2e; border-left:3px solid #f59e0b; padding:12px 16px; margin-bottom:8px; border-radius:0 8px 8px 0; page-break-inside:avoid;">
          <div style="color:#fafafa; font-weight:600; font-size:13px;">{_escape(str(hyp.get("title", "")))}</div>
          <div style="color:#ccc; font-size:12px; margin-top:4px;">
            TEST: {_escape(str(hyp.get("test", "")))}<br>
            EXPECTED: {_escape(str(hyp.get("expected_outcome", "")))}<br>
            BASED ON: {_escape(based)}
          </div>
          <div style="color:#888; font-size:10px; margin-top:4px;">Risk: {_escape(str(hyp.get("risk_level", "")))} | Priority: {_escape(str(hyp.get("priority", "")))}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{
    background: #0e1117;
    color: #fafafa;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 40px;
    font-size: 14px;
  }}
  h1 {{ color: #fafafa; font-size: 28px; margin-bottom: 4px; }}
  h2 {{ color: #fafafa; font-size: 20px; border-bottom: 1px solid #333; padding-bottom: 8px; margin-top: 32px; }}
  h3 {{ color: #ccc; font-size: 16px; }}
  .metrics-bar {{
    display: flex; gap: 16px; margin: 20px 0;
  }}
  .metric-box {{
    flex: 1; background: #1e1e2e; padding: 16px; border-radius: 8px; text-align: center;
  }}
  .metric-label {{ color: #888; font-size: 11px; text-transform: uppercase; }}
  .metric-value {{ color: #fafafa; font-size: 22px; font-weight: 700; margin-top: 4px; }}
  table {{ font-size: 12px; }}
  th, td {{ border: none; }}
</style>
</head>
<body>
  <h1>Creative Feedback Loop Report</h1>
  <div style="color:#888; font-size:13px;">{_escape(brand_name or "Unknown Brand")} | Generated {now}</div>

  <div class="metrics-bar">
    <div class="metric-box"><div class="metric-label">Total Ads</div><div class="metric-value">{total_ads}</div></div>
    <div class="metric-box"><div class="metric-label">Winners</div><div class="metric-value">{winners}</div></div>
    <div class="metric-box"><div class="metric-label">Losers</div><div class="metric-value">{losers}</div></div>
    <div class="metric-box"><div class="metric-label">Total Spend</div><div class="metric-value">&#36;{_format_spend(total_spend)}</div></div>
    <div class="metric-box"><div class="metric-label">Avg ROAS</div><div class="metric-value">{avg_roas:.2f}x</div></div>
  </div>

  <h2>Dashboard — Section A (Classified Ads)</h2>
  {classified_tables}

  <h2>Dashboard — Section B (Top 50 by Spend)</h2>
  {top50_tables}

  <h2>Pattern Insights</h2>
  {insights_html}

  <h2>Top 5 Strongest Patterns — Expansion Opportunities</h2>
  {top_patterns_html}

  <h2>Learnings</h2>
  {learnings_html}

  <h2>Hypotheses to Test</h2>
  {hypotheses_html}
</body>
</html>"""

    return html


async def generate_pdf_report(
    brand_name: str,
    classified_df: pd.DataFrame,
    top50_df: pd.DataFrame,
    classified_dims: dict[str, list],
    top50_dims: dict[str, list],
    results: dict[str, Any],
) -> Optional[str]:
    """Generate a PDF report using Playwright.

    Args:
        brand_name: Brand name
        classified_df: Classified ads DataFrame
        top50_df: Top 50 DataFrame
        classified_dims: Dimension breakdowns for classified ads
        top50_dims: Dimension breakdowns for top 50
        results: Pattern analysis results dict

    Returns:
        Path to generated PDF file, or None on failure
    """
    from playwright.async_api import async_playwright

    html = _build_html_report(
        brand_name, classified_df, top50_df, classified_dims, top50_dims, results
    )

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_brand = "".join(c for c in (brand_name or "report") if c.isalnum() or c in "._- ")
    pdf_path = output_dir / f"creative_feedback_{safe_brand}_{date_str}.pdf"

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        await page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
        )
        await browser.close()

    return str(pdf_path) if pdf_path.exists() else None
