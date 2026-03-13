"""Report Generator — generates PDF reports from analysis results.

Supports three report sections:
  A. Recent Creative Analysis
  B. Top 50 All-Time Account Analysis
  C. Recent vs All-Time Comparison (drift detection)

Uses HTML template + weasyprint for PDF generation.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .classifier import ClassificationResult, ClassifiedAd, WeightTier
from .hypothesis_generator import HypothesisReport
from .pattern_analyzer import ComparisonAnalysis, PatternAnalysis

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


def _build_classification_table(classification: ClassificationResult) -> str:
    """Build an HTML table of classified ads."""
    rows = ""
    for ad in classification.all_classified:
        rows += f"""
        <tr style="border-bottom:1px solid #333;">
            <td style="padding:8px;color:#fafafa;">{ad.match.task.name[:60]}</td>
            <td style="padding:8px;text-align:center;">{_classification_badge(ad.classification.value)}</td>
            <td style="padding:8px;text-align:center;">{_weight_badge(ad.weight_tier)}</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">${ad.match.total_spend:,.0f}</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">{ad.spend_share*100:.1f}%</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">{ad.match.weighted_roas:.2f}x</td>
            <td style="padding:8px;text-align:right;color:#fafafa;">${ad.value_score:,.0f}</td>
        </tr>"""
    return f"""
    <table>
        <thead><tr>
            <th style="color:#aaa;">Ad Name</th>
            <th style="text-align:center;color:#aaa;">Class</th>
            <th style="text-align:center;color:#aaa;">Weight</th>
            <th style="text-align:right;color:#aaa;">Spend</th>
            <th style="text-align:right;color:#aaa;">Share</th>
            <th style="text-align:right;color:#aaa;">ROAS</th>
            <th style="text-align:right;color:#aaa;">Value</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def _build_stats_grid(classification: ClassificationResult) -> str:
    """Build the stats grid for a classification."""
    return f"""
    <div class="stats-grid">
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
    </div>"""


def _build_learnings_html(hypothesis_report: HypothesisReport) -> str:
    """Build learnings HTML section."""
    html = ""
    for i, learning in enumerate(hypothesis_report.learnings, 1):
        evidence = ", ".join(learning.supporting_evidence) if learning.supporting_evidence else "See pattern analysis"
        html += f"""
        <div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <h4 style="color:#fafafa;margin:0;">Learning {i}</h4>
                {_confidence_badge(learning.confidence)}
            </div>
            <p style="color:#fafafa;margin:4px 0;">{learning.observation}</p>
            <p style="color:#aaa;font-size:13px;margin:4px 0;"><strong>Evidence:</strong> {evidence}</p>
        </div>"""
    return html


def _build_hypotheses_html(hypothesis_report: HypothesisReport) -> str:
    """Build hypotheses HTML section."""
    html = ""
    for i, hyp in enumerate(hypothesis_report.hypotheses, 1):
        hooks = "".join(f"<li style='color:#fafafa;'>{h}</li>" for h in hyp.suggested_hook_ideas) if hyp.suggested_hook_ideas else "<li style='color:#aaa;'>See pattern analysis for ideas</li>"
        html += f"""
        <div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <h4 style="color:#fafafa;margin:0;">Hypothesis {i}</h4>
                {_priority_badge(hyp.priority)}
            </div>
            <p style="color:#aaa;font-size:13px;margin:4px 0;"><em>Based on: {hyp.based_on_learning}</em></p>
            <p style="color:#fafafa;margin:4px 0;"><strong>Test:</strong> {hyp.independent_variable}</p>
            <p style="color:#fafafa;margin:4px 0;"><strong>Expected:</strong> {hyp.expected_outcome}</p>
            <div style="margin-top:8px;padding:12px;background:#0E1117;border-radius:4px;">
                <p style="color:#6C63FF;margin:0 0 4px 0;font-weight:bold;">Suggested Script Outline</p>
                <p style="color:#fafafa;margin:2px 0;"><strong>Hook ideas:</strong></p>
                <ul style="margin:4px 0;">{hooks}</ul>
                <p style="color:#fafafa;margin:2px 0;"><strong>Body:</strong> {hyp.suggested_body_structure or 'See analysis'}</p>
                <p style="color:#fafafa;margin:2px 0;"><strong>Format:</strong> {hyp.recommended_format or 'Based on winner patterns'}</p>
            </div>
        </div>"""
    return html


def _build_section_html(
    title: str,
    subtitle: str,
    classification: ClassificationResult,
    pattern_analysis: PatternAnalysis,
    hypothesis_report: Optional[HypothesisReport] = None,
) -> str:
    """Build a complete analysis section (used for both Recent and Top 50)."""
    pattern_html = pattern_analysis.raw_analysis.replace("\n", "<br>")
    cross_html = ""
    for insight in pattern_analysis.cross_insights:
        cross_html += f'<li style="color:#fafafa;margin-bottom:8px;">{insight}</li>'

    section = f"""
    <h2 style="color:#6C63FF;border-bottom:2px solid #6C63FF;padding-bottom:8px;margin-top:40px;">{title}</h2>
    <p style="color:#aaa;">{subtitle}</p>
    {_build_stats_grid(classification)}
    <h3 style="color:#fafafa;">Ad Classification (by Value Score)</h3>
    {_build_classification_table(classification)}
    <h3 style="color:#fafafa;">Pattern Analysis</h3>
    <div style="background:#1A1D24;border-radius:8px;padding:20px;color:#fafafa;line-height:1.6;">
        {pattern_html}
    </div>
    <h3 style="color:#fafafa;">Cross-Pattern Insights</h3>
    <ul style="list-style:none;padding:0;">
        {cross_html if cross_html else '<li style="color:#aaa;">No insights generated</li>'}
    </ul>"""

    if hypothesis_report:
        learnings = _build_learnings_html(hypothesis_report)
        hypotheses = _build_hypotheses_html(hypothesis_report)
        section += f"""
        <h3 style="color:#fafafa;">Key Learnings</h3>
        {learnings if learnings else '<p style="color:#aaa;">No learnings generated</p>'}
        <h3 style="color:#fafafa;">Testable Hypotheses</h3>
        {hypotheses if hypotheses else '<p style="color:#aaa;">No hypotheses generated</p>'}"""

    return section


def _build_comparison_html(comparison: ComparisonAnalysis) -> str:
    """Build the comparison section HTML."""
    comparison_md = comparison.raw_comparison.replace("\n", "<br>")

    # Build drift alerts
    drift_html = ""
    for d in comparison.drift_alerts:
        drift_html += f'<div style="background:#1A1D24;border-left:4px solid #F44336;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{d}</p></div>'

    consistent_html = ""
    for c in comparison.consistent_patterns:
        consistent_html += f'<div style="background:#1A1D24;border-left:4px solid #4CAF50;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{c}</p></div>'

    new_html = ""
    for n in comparison.new_patterns:
        new_html += f'<div style="background:#1A1D24;border-left:4px solid #FF9800;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{n}</p></div>'

    recs_html = ""
    for r in comparison.recommendations:
        recs_html += f'<div style="background:#1A1D24;border-left:4px solid #6C63FF;padding:10px 14px;margin-bottom:8px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{r}</p></div>'

    return f"""
    <h2 style="color:#FF9800;border-bottom:2px solid #FF9800;padding-bottom:8px;margin-top:40px;">Section C — Recent vs All-Time Comparison</h2>
    <p style="color:#aaa;">Pattern drift detection: Is your creative team getting better or worse?</p>

    <h3 style="color:#fafafa;">Full Comparison Analysis</h3>
    <div style="background:#1A1D24;border-radius:8px;padding:20px;color:#fafafa;line-height:1.6;">
        {comparison_md}
    </div>

    <h3 style="color:#F44336;">Pattern Drifts (Areas of Concern)</h3>
    {drift_html if drift_html else '<p style="color:#aaa;">No drifts detected</p>'}

    <h3 style="color:#4CAF50;">Consistent Patterns (Keep Going)</h3>
    {consistent_html if consistent_html else '<p style="color:#aaa;">No consistent patterns detected</p>'}

    <h3 style="color:#FF9800;">New Patterns (Potential Discoveries)</h3>
    {new_html if new_html else '<p style="color:#aaa;">No new patterns detected</p>'}

    <h3 style="color:#6C63FF;">Recommendations</h3>
    {recs_html if recs_html else '<p style="color:#aaa;">No recommendations generated</p>'}"""


# ── Public API ────────────────────────────────────────────────────────────────

def generate_html_report(
    brand_name: str,
    classification: ClassificationResult,
    pattern_analysis: PatternAnalysis,
    hypothesis_report: HypothesisReport,
    date_range: Optional[str] = None,
    alltime_classification: Optional[ClassificationResult] = None,
    alltime_pattern_analysis: Optional[PatternAnalysis] = None,
    alltime_hypothesis_report: Optional[HypothesisReport] = None,
    comparison: Optional[ComparisonAnalysis] = None,
) -> str:
    """Generate a full HTML report with up to 3 sections.

    Section A: Recent Creative Analysis (always present)
    Section B: Top 50 All-Time (if alltime data provided)
    Section C: Comparison (if comparison data provided)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Section A — Recent
    section_a = _build_section_html(
        "Section A — Recent Creative Analysis",
        f"Recently launched ads{f' (last {date_range})' if date_range else ''} — What's working in recent launches?",
        classification,
        pattern_analysis,
        hypothesis_report,
    )

    # Section B — Top 50 All-Time (optional)
    section_b = ""
    if alltime_classification and alltime_pattern_analysis:
        section_b = _build_section_html(
            "Section B — Top 50 All-Time Account Analysis",
            "Top 50 ads by spend across all time — What has historically worked best?",
            alltime_classification,
            alltime_pattern_analysis,
            alltime_hypothesis_report,
        )

    # Section C — Comparison (optional)
    section_c = ""
    if comparison:
        section_c = _build_comparison_html(comparison)

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
            padding: 40px;
            max-width: 1100px;
            margin: 0 auto;
        }}
        h1, h2, h3 {{ color: #fafafa; }}
        h1 {{ border-bottom: 2px solid #6C63FF; padding-bottom: 12px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 10px 8px; color: #aaa; font-size: 13px; border-bottom: 2px solid #333; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: #1A1D24;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: #6C63FF; }}
        .stat-label {{ font-size: 13px; color: #aaa; margin-top: 4px; }}
    </style>
</head>
<body>
    <h1>Creative Feedback Loop Report — {brand_name}</h1>
    <p style="color:#aaa;">Generated: {now}{f' | Date range: {date_range}' if date_range else ''}</p>

    {section_a}
    {section_b}
    {section_c}

    <div style="margin-top:40px;padding-top:20px;border-top:1px solid #333;color:#666;font-size:12px;">
        Creative Feedback Loop Analyzer | {now}
    </div>
</body>
</html>"""

    return html


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
        try:
            from weasyprint import HTML
            pdf_path = REPORTS_DIR / f"{safe_name}_{timestamp}.pdf"
            HTML(string=html_content).write_pdf(str(pdf_path))
            return pdf_path
        except ImportError:
            format = "html"

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
