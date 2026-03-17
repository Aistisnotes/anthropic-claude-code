"""PDF report generator for Creative Feedback Loop.

Builds an HTML report from dashboard data and pattern results,
then converts to PDF using Playwright.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any


def _fmt_spend(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1000:
        return f"${v/1000:.0f}k"
    return f"${v:.0f}"


def _escape(text: str) -> str:
    """Escape HTML special chars and dollar signs."""
    if not isinstance(text, str):
        text = str(text)
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("$", "&#36;"))


def build_html_report(
    brand_name: str,
    csv_start: str,
    csv_end: str,
    classification_counts: dict,
    dashboard_data: dict,
    pattern_results: dict,
    top50_dashboard_data: dict | None = None,
) -> str:
    """Build full HTML report from run data."""

    winners = classification_counts.get("winners", 0)
    losers = classification_counts.get("losers", 0)
    untested = classification_counts.get("untested", 0)
    total = winners + losers + untested

    date_range = f"{csv_start} \u2013 {csv_end}" if csv_start and csv_end else "All dates"
    generated = datetime.now().strftime("%B %d, %Y at %H:%M")

    # \u2500\u2500 Executive Summary \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    exec_summary = _escape(pattern_results.get("executive_summary", ""))

    # \u2500\u2500 Insights HTML \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    insights_html = ""
    for i, ins in enumerate(pattern_results.get("insights", []), 1):
        title = _escape(ins.get("title", ""))
        detail = _escape(ins.get("detail", ""))
        conf = _escape(ins.get("confidence", ""))
        score = ins.get("score", 0)
        score_str = f" \u2014 Score: {score}/100" if score else ""
        insights_html += f"""
        <div class="card" style="margin-bottom:16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <span class="badge">PATTERN #{i}{score_str}</span>
            <span style="color:#888; font-size:12px;">{conf}</span>
          </div>
          <h3 style="color:#fafafa; margin:0 0 8px 0; font-size:15px;">{title}</h3>
          <p style="color:#ccc; font-size:13px; line-height:1.6; margin:0;">{detail}</p>
        </div>"""

    # \u2500\u2500 Learnings HTML \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    learnings_html = ""
    for item in pattern_results.get("learnings", []):
        text = _escape(item)
        learnings_html += f'<div class="learning-card">\u2022 {text}</div>'

    # \u2500\u2500 Hypotheses HTML \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    hyp_html = ""
    for item in pattern_results.get("hypotheses", []):
        text = _escape(item)
        hyp_html += f'<div class="hyp-card">\u2022 {text}</div>'

    # \u2500\u2500 Dashboard Tables HTML \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    def _dim_table(dims: list) -> str:
        if not dims:
            return "<p style='color:#888;'>No dimension data.</p>"
        out = ""
        for dim in dims:
            name = _escape(dim.get("name", ""))
            values = sorted(dim.get("values", []), key=lambda v: v.get("spend", 0), reverse=True)
            rows = ""
            for j, v in enumerate(values):
                bg = "#1e1e2e" if j % 2 == 0 else "#262730"
                roas = v.get("avg_roas", 0)
                roas_color = "#27ae60" if roas >= 1.0 else "#e74c3c" if roas > 0 else "#888"
                wp = v.get("winner_pct", 0)
                lp = v.get("loser_pct", 0)
                wp_color = "#27ae60" if wp > lp else "#e74c3c" if wp < lp else "#888"
                spend = v.get("spend", 0)
                rows += f"""
                <tr style="background:{bg};">
                  <td style="padding:8px 12px; color:#fafafa; font-size:13px;">{_escape(str(v.get("value","")))} </td>
                  <td style="padding:8px 12px; color:#ccc; text-align:right; font-size:13px;">{v.get("pct_all",0):.1f}%</td>
                  <td style="padding:8px 12px; color:{wp_color}; text-align:right; font-size:13px;">{wp:.0f}%</td>
                  <td style="padding:8px 12px; color:#e74c3c; text-align:right; font-size:13px;">{lp:.0f}%</td>
                  <td style="padding:8px 12px; color:{roas_color}; text-align:right; font-size:13px;">{roas:.2f}x</td>
                  <td style="padding:8px 12px; color:#fafafa; text-align:right; font-size:13px;">{_fmt_spend(spend)}</td>
                </tr>"""
            out += f"""
            <div style="margin-bottom:20px;">
              <h4 style="color:#fafafa; margin:0 0 8px 0;">{name}</h4>
              <table style="width:100%; border-collapse:collapse; border-radius:8px; overflow:hidden;">
                <thead>
                  <tr style="background:#2d2d3d;">
                    <th style="padding:8px 12px; color:#fafafa; text-align:left; font-size:12px;">Value</th>
                    <th style="padding:8px 12px; color:#fafafa; text-align:right; font-size:12px;">% All</th>
                    <th style="padding:8px 12px; color:#fafafa; text-align:right; font-size:12px;">% Winners</th>
                    <th style="padding:8px 12px; color:#fafafa; text-align:right; font-size:12px;">% Losers</th>
                    <th style="padding:8px 12px; color:#fafafa; text-align:right; font-size:12px;">Avg ROAS</th>
                    <th style="padding:8px 12px; color:#fafafa; text-align:right; font-size:12px;">Spend</th>
                  </tr>
                </thead>
                <tbody>{rows}</tbody>
              </table>
            </div>"""
        return out

    dash_html = _dim_table(dashboard_data.get("dimensions", []))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0e1117; color: #fafafa; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 32px; }}
  h1 {{ font-size: 28px; margin-bottom: 4px; }}
  h2 {{ font-size: 20px; color: #fafafa; margin: 24px 0 12px 0; }}
  h3 {{ font-size: 16px; }}
  .subtitle {{ color: #888; font-size: 14px; margin-bottom: 32px; }}
  .metrics {{ display: flex; gap: 12px; margin-bottom: 24px; }}
  .metric {{ background: #1e1e2e; border-radius: 8px; padding: 16px; flex: 1; text-align: center; }}
  .metric .value {{ font-size: 28px; font-weight: 700; color: #fafafa; }}
  .metric .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
  .card {{ background: #1e1e2e; border-radius: 12px; padding: 20px; border: 1px solid #333; }}
  .badge {{ background: #e91e8c; color: white; padding: 4px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; }}
  .exec-summary {{ background: #1e1e2e; border-left: 3px solid #e91e8c; padding: 16px; border-radius: 0 8px 8px 0; margin-bottom: 24px; color: #fafafa; font-size: 14px; line-height: 1.6; }}
  .learning-card {{ background: #1e1e2e; border-left: 3px solid #3b82f6; padding: 12px 16px; margin-bottom: 8px; border-radius: 0 8px 8px 0; color: #ccc; font-size: 13px; }}
  .hyp-card {{ background: #1e1e2e; border-left: 3px solid #f59e0b; padding: 12px 16px; margin-bottom: 8px; border-radius: 0 8px 8px 0; color: #ccc; font-size: 13px; }}
  .divider {{ border: none; border-top: 1px solid #333; margin: 24px 0; }}
</style>
</head>
<body>
  <h1>Creative Feedback Loop Report</h1>
  <div class="subtitle">{_escape(brand_name)} \u00b7 {_escape(date_range)} \u00b7 Generated {generated}</div>

  <div class="metrics">
    <div class="metric"><div class="value">{total}</div><div class="label">Total Ads</div></div>
    <div class="metric"><div class="value" style="color:#27ae60;">{winners}</div><div class="label">Winners</div></div>
    <div class="metric"><div class="value" style="color:#e74c3c;">{losers}</div><div class="label">Losers</div></div>
    <div class="metric"><div class="value" style="color:#888;">{untested}</div><div class="label">Untested</div></div>
  </div>

  {"<div class='exec-summary'>" + exec_summary + "</div>" if exec_summary else ""}

  <h2>\U0001f4ca Dimension Analysis</h2>
  {dash_html}

  <hr class="divider">
  <h2>\U0001f50d Pattern Insights</h2>
  {insights_html}

  <hr class="divider">
  <h2>\U0001f4da Learnings</h2>
  {learnings_html or "<p style='color:#888;'>No learnings generated.</p>"}

  <hr class="divider">
  <h2>\U0001f4a1 Hypotheses</h2>
  {hyp_html or "<p style='color:#888;'>No hypotheses generated.</p>"}
</body>
</html>"""
    return html


async def generate_pdf(html_content: str, output_path: str) -> None:
    """Convert HTML to PDF using Playwright."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html_content, wait_until="networkidle")
        await page.pdf(
            path=output_path,
            format="A4",
            margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
            print_background=True,
        )
        await browser.close()


def generate_pdf_sync(html_content: str, output_path: str) -> None:
    """Synchronous wrapper for generate_pdf."""
    asyncio.run(generate_pdf(html_content, output_path))
