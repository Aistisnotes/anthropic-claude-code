"""Report Generator — generates PDF reports from analysis results.

Uses HTML template + Playwright (headless Chromium) for PDF generation.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .classifier import ClassificationResult, ClassifiedAd, WeightTier
from .hypothesis_generator import HypothesisReport
from .pattern_analyzer import PatternAnalysis

REPORTS_DIR = Path(__file__).parent.parent / "output" / "reports"


def _ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def _weight_badge(tier: WeightTier) -> str:
    colors = {
        WeightTier.PILLAR: "#FFD700",
        WeightTier.STRONG: "#6C63FF",
        WeightTier.NORMAL: "#4CAF50",
        WeightTier.MINOR: "#888888",
    }
    color = colors.get(tier, "#888888")
    return f'<span style="background:{color};color:#0E1117;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{tier.value.upper()}</span>'


def _classification_badge(classification: str) -> str:
    colors = {
        "winner": "#4CAF50",
        "average": "#FF9800",
        "loser": "#F44336",
        "untested": "#888888",
    }
    color = colors.get(classification, "#888888")
    return f'<span style="background:{color};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{classification.upper()}</span>'


def _confidence_badge(confidence: str) -> str:
    colors = {"HIGH": "#4CAF50", "MEDIUM": "#FF9800", "LOW": "#F44336"}
    color = colors.get(confidence.upper(), "#888888")
    return f'<span style="background:{color};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{confidence}</span>'


def _priority_badge(priority: str) -> str:
    colors = {"HIGH": "#F44336", "MEDIUM": "#FF9800", "LOW": "#4CAF50"}
    color = colors.get(priority.upper(), "#888888")
    return f'<span style="background:{color};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{priority}</span>'


def generate_html_report(
    brand_name: str,
    classification: ClassificationResult,
    pattern_analysis: PatternAnalysis,
    hypothesis_report: HypothesisReport,
    date_range: Optional[str] = None,
    top_performers: Optional[list] = None,
) -> str:
    """Generate a full HTML report with dark theme, cover page, and all sections."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Executive Summary ──────────────────────────────────────────────────────
    top3_winners = sorted(classification.winners, key=lambda x: x.match.weighted_roas, reverse=True)[:3]
    exec_bullets = []
    for w in top3_winners:
        exec_bullets.append(f"<li>{w.match.task.name[:60]} — ROAS {w.match.weighted_roas:.2f}x, spend ${w.match.total_spend:,.0f}</li>")
    exec_bullets.append(f"<li>Total account spend analysed: ${classification.total_account_spend:,.0f}</li>")
    exec_bullets.append(f"<li>{len(classification.winners)} winners, {len(classification.losers)} losers identified across {len(classification.all_classified)} matched ads</li>")
    exec_summary_html = "<ul style='color:#fafafa;line-height:1.8;'>" + "".join(exec_bullets) + "</ul>"

    # ── Classification table ───────────────────────────────────────────────────
    sorted_classified = sorted(classification.all_classified, key=lambda x: x.value_score, reverse=True)
    ad_rows = ""
    for ad in sorted_classified:
        ad_rows += f"""
        <tr>
            <td style="padding:8px;color:#fafafa;font-size:13px;">{ad.match.task.name[:60]}</td>
            <td style="padding:8px;text-align:center;">{_classification_badge(ad.classification.value)}</td>
            <td style="padding:8px;text-align:center;">{_weight_badge(ad.weight_tier)}</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">${ad.match.total_spend:,.0f}</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">{ad.spend_share*100:.1f}%</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">{ad.match.weighted_roas:.2f}x</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">${ad.value_score:,.0f}</td>
        </tr>"""

    # ── Pattern split: winner vs loser ────────────────────────────────────────
    raw = pattern_analysis.raw_analysis
    loser_marker = "LOSER PATTERNS"
    if loser_marker in raw.upper():
        split_idx = raw.upper().index(loser_marker)
        winner_pattern_raw = raw[:split_idx]
        loser_pattern_raw = raw[split_idx:]
    else:
        winner_pattern_raw = raw
        loser_pattern_raw = ""

    winner_pattern_html = winner_pattern_raw.replace("\n", "<br>")
    loser_pattern_html = loser_pattern_raw.replace("\n", "<br>")

    # ── Cross-pattern insights ─────────────────────────────────────────────────
    cross_html = ""
    for insight in pattern_analysis.cross_insights:
        cross_html += f'<div class="card"><p style="color:#fafafa;margin:0;">{insight}</p></div>'
    if not cross_html:
        cross_html = '<p style="color:#aaa;">No cross-pattern insights generated.</p>'

    # ── Top performers section ─────────────────────────────────────────────────
    top_performers_section = ""
    if top_performers:
        tp_rows = ""
        for i, item in enumerate(top_performers, 1):
            ad = item["ad"]
            mr = item.get("match_result")
            cls = item.get("classification") or ""
            cls_color = {"winner": "#4CAF50", "average": "#FF9800", "loser": "#F44336", "untested": "#888"}.get(cls, "#888")
            task_name = mr.task.name[:60] if mr else "Not matched to ClickUp"
            match_note = "" if mr else '<span style="color:#FF9800;">⚠ Unmatched</span>'
            tp_rows += f"""
            <tr>
                <td style="padding:8px;color:#fafafa;font-size:13px;">#{i} {ad.ad_name[:60]}</td>
                <td style="padding:8px;text-align:right;color:#fafafa;">${ad.spend:,.0f}</td>
                <td style="padding:8px;text-align:right;color:#fafafa;">{ad.roas:.2f}x</td>
                <td style="padding:8px;text-align:center;">{_classification_badge(cls) if cls else match_note}</td>
                <td style="padding:8px;color:#aaa;font-size:12px;">{task_name}</td>
            </tr>"""
        top_performers_section = f"""
    <h2>Top Performers Comparison</h2>
    <table>
        <thead>
            <tr>
                <th>Ad Name</th>
                <th style="text-align:right;">Spend</th>
                <th style="text-align:right;">ROAS</th>
                <th style="text-align:center;">Class</th>
                <th>ClickUp Task</th>
            </tr>
        </thead>
        <tbody>{tp_rows}</tbody>
    </table>"""

    # ── Learnings ──────────────────────────────────────────────────────────────
    learnings_html = ""
    for i, learning in enumerate(hypothesis_report.learnings, 1):
        evidence = ", ".join(learning.supporting_evidence) if learning.supporting_evidence else "See pattern analysis"
        learnings_html += f"""
        <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <h4 style="color:#fafafa;margin:0;">Learning {i}</h4>
                {_confidence_badge(learning.confidence)}
            </div>
            <p style="color:#fafafa;margin:4px 0;">{learning.observation}</p>
            <p style="color:#aaa;font-size:13px;margin:4px 0;"><strong>Evidence:</strong> {evidence}</p>
        </div>"""
    if not learnings_html:
        learnings_html = '<p style="color:#aaa;">No learnings generated yet.</p>'

    # ── Hypotheses ─────────────────────────────────────────────────────────────
    hypotheses_html = ""
    for i, hyp in enumerate(hypothesis_report.hypotheses, 1):
        hooks = "".join(f"<li style='color:#fafafa;font-size:13px;'>{h}</li>" for h in hyp.suggested_hook_ideas) if hyp.suggested_hook_ideas else "<li style='color:#aaa;'>See pattern analysis for ideas</li>"
        hypotheses_html += f"""
        <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <h4 style="color:#fafafa;margin:0;">Hypothesis {i}</h4>
                {_priority_badge(hyp.priority)}
            </div>
            <p style="color:#aaa;font-size:13px;margin:4px 0;"><em>Based on: {hyp.based_on_learning}</em></p>
            <p style="color:#fafafa;margin:4px 0;"><strong>Test:</strong> {hyp.independent_variable}</p>
            <p style="color:#fafafa;margin:4px 0;"><strong>Expected:</strong> {hyp.expected_outcome}</p>
            <div style="margin-top:8px;padding:12px;background:#0E1117;border-radius:4px;">
                <p style="color:#6C63FF;margin:0 0 4px 0;font-weight:bold;font-size:13px;">Script Outline</p>
                <ul style="margin:4px 0;padding-left:16px;">{hooks}</ul>
                <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Body:</strong> {hyp.suggested_body_structure or 'See analysis'}</p>
                <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Format:</strong> {hyp.recommended_format or 'Based on winner patterns'}</p>
            </div>
        </div>"""
    if not hypotheses_html:
        hypotheses_html = '<p style="color:#aaa;">No hypotheses generated yet.</p>'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Creative Feedback Loop — {brand_name}</title>
    <style>
        body {{
            background: #0E1117;
            color: #fafafa;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 32px;
            max-width: 1100px;
            margin: 0 auto;
        }}
        h1 {{ color: #fafafa; border-bottom: 3px solid #6C63FF; padding-bottom: 12px; }}
        h2 {{ color: #fafafa; border-bottom: 1px solid #333; margin-top: 28px; padding-bottom: 8px; }}
        h3, h4 {{ color: #fafafa; }}
        .cover {{ page-break-after: always; padding: 48px; }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 20px 0; }}
        .stat-card {{ background: #1A1D24; border-radius: 8px; padding: 16px; text-align: center; }}
        .stat-value {{ font-size: 32px; font-weight: 800; color: #6C63FF; }}
        .stat-label {{ font-size: 13px; color: #aaa; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ color: #aaa; font-size: 13px; border-bottom: 2px solid #333; padding: 8px; text-align: left; }}
        tr {{ border-bottom: 1px solid #222; }}
        .card {{ background: #1A1D24; border-radius: 8px; padding: 16px; margin-bottom: 12px; }}
        .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
        a {{ color: #6C63FF; }}
    </style>
</head>
<body>

    <!-- COVER PAGE -->
    <div class="cover">
        <h1>Creative Feedback Loop Report</h1>
        <h2 style="border:none;color:#6C63FF;font-size:28px;margin-top:8px;">{brand_name}</h2>
        <p style="color:#aaa;">Generated: {now}{f' | Date range: {date_range}' if date_range else ''}</p>
        <div class="stat-grid" style="margin-top:40px;">
            <div class="stat-card">
                <div class="stat-value" style="color:#4CAF50;">{len(classification.winners)}</div>
                <div class="stat-label">Winners ({classification.pillar_winners} pillar, {classification.strong_winners} strong)</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color:#FF9800;">{len(classification.average)}</div>
                <div class="stat-label">Average</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color:#F44336;">{len(classification.losers)}</div>
                <div class="stat-label">Losers</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${classification.total_account_spend:,.0f}</div>
                <div class="stat-label">Total Account Spend</div>
            </div>
        </div>
    </div>

    <!-- EXECUTIVE SUMMARY -->
    <h2>Executive Summary</h2>
    {exec_summary_html}

    <!-- CLASSIFICATION OVERVIEW -->
    <h2>Classification Overview</h2>
    <table>
        <thead>
            <tr>
                <th>Ad Name</th>
                <th style="text-align:center;">Class</th>
                <th style="text-align:center;">Weight</th>
                <th style="text-align:right;">Spend</th>
                <th style="text-align:right;">Share%</th>
                <th style="text-align:right;">ROAS</th>
                <th style="text-align:right;">Value Score</th>
            </tr>
        </thead>
        <tbody>
            {ad_rows}
        </tbody>
    </table>

    <!-- WINNER PATTERNS -->
    <h2>Winner Patterns</h2>
    <div style="background:#1A1D24;border-radius:8px;padding:20px;color:#fafafa;line-height:1.6;">
        {winner_pattern_html if winner_pattern_html else '<p style="color:#aaa;">See full pattern analysis.</p>'}
    </div>

    <!-- LOSER PATTERNS -->
    {f'<h2>Loser Patterns</h2><div style="background:#1A1D24;border-radius:8px;padding:20px;color:#fafafa;line-height:1.6;">{loser_pattern_html}</div>' if loser_pattern_html else ''}

    <!-- CROSS-PATTERN INSIGHTS -->
    <h2>Cross-Pattern Insights</h2>
    {cross_html}

    <!-- TOP PERFORMERS COMPARISON -->
    {top_performers_section}

    <!-- KEY LEARNINGS -->
    <h2>Key Learnings</h2>
    {learnings_html}

    <!-- TESTABLE HYPOTHESES -->
    <h2>Testable Hypotheses</h2>
    {hypotheses_html}

    <!-- FOOTER -->
    <div style="margin-top:40px;padding-top:20px;border-top:1px solid #333;color:#666;font-size:12px;">
        Creative Feedback Loop Analyzer | Generated: {now}
    </div>

</body>
</html>"""

    return html


async def _render_pdf_async(html_content: str, output_path: Path) -> None:
    """Render HTML to PDF using headless Chromium via Playwright."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html_content, wait_until="networkidle")
        await page.pdf(
            path=str(output_path),
            format="A4",
            margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
        )
        await browser.close()


def _render_pdf(html_content: str, output_path: Path) -> None:
    """Sync wrapper around the async Playwright PDF renderer."""
    try:
        loop = asyncio.get_running_loop()
        # Already inside an event loop (e.g. Streamlit) — use nest_asyncio
        import nest_asyncio
        nest_asyncio.apply()
        loop.run_until_complete(_render_pdf_async(html_content, output_path))
    except RuntimeError:
        asyncio.run(_render_pdf_async(html_content, output_path))


def save_report(
    brand_name: str,
    html_content: str,
    format: str = "html",
) -> Path:
    """Save report to file. Returns path to saved file."""
    _ensure_reports_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = brand_name.replace(" ", "_").replace("/", "_")

    if format == "pdf":
        pdf_path = REPORTS_DIR / f"{safe_name}_{timestamp}.pdf"
        _render_pdf(html_content, pdf_path)
        return pdf_path

    html_path = REPORTS_DIR / f"{safe_name}_{timestamp}.html"
    html_path.write_text(html_content, encoding="utf-8")
    return html_path


def list_reports() -> list[dict[str, Any]]:
    """List all saved reports."""
    _ensure_reports_dir()
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.suffix in (".html", ".pdf"):
            reports.append({
                "name": f.stem,
                "path": str(f),
                "format": f.suffix[1:],
                "size": f.stat().st_size,
                "created": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    return reports
