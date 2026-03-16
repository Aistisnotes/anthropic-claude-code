"""Report generator — produces markdown and PDF reports from pipeline results."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def generate_markdown_report(
    brand_name: str,
    aggregation_stats: dict[str, Any],
    classification_counts: dict[str, int],
    winners: list[dict[str, Any]],
    losers: list[dict[str, Any]],
    top50: list[dict[str, Any]],
    pattern_analysis: dict[str, Any] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    novelty: Any | None = None,
) -> str:
    """Generate a markdown report from pipeline results.

    Returns:
        Markdown string.
    """
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append(f"# Creative Feedback Loop Report — {brand_name}")
    lines.append(f"*Generated: {now}*")
    lines.append("")

    # Aggregation stats
    lines.append("## Data Summary")
    lines.append(f"- CSV Rows: {aggregation_stats.get('raw_rows', 0):,}")
    lines.append(f"- Unique Ads (after aggregation): {aggregation_stats.get('unique_ads', 0):,}")
    lines.append(f"- Total Spend: ${aggregation_stats.get('total_spend', 0):,.2f}")
    lines.append("")

    # Classification
    lines.append("## Classification")
    lines.append(f"- Winners: {classification_counts.get('winner', 0)}")
    lines.append(f"- Losers: {classification_counts.get('loser', 0)}")
    lines.append(f"- Untested: {classification_counts.get('untested', 0)}")
    lines.append("")

    # Winners table
    if winners:
        lines.append("## Winners")
        lines.append("| Ad Name | Spend | ROAS | Revenue |")
        lines.append("|---|---|---|---|")
        for w in winners[:20]:
            lines.append(
                f"| {w.get('ad_name', '')} | "
                f"${w.get('spend', 0):,.2f} | "
                f"{w.get('roas', 0):.2f} | "
                f"${w.get('revenue', 0):,.2f} |"
            )
        lines.append("")

    # Losers table
    if losers:
        lines.append("## Losers")
        lines.append("| Ad Name | Spend | ROAS | Revenue |")
        lines.append("|---|---|---|---|")
        for lo in losers[:20]:
            lines.append(
                f"| {lo.get('ad_name', '')} | "
                f"${lo.get('spend', 0):,.2f} | "
                f"{lo.get('roas', 0):.2f} | "
                f"${lo.get('revenue', 0):,.2f} |"
            )
        lines.append("")

    # Pattern Analysis
    if pattern_analysis and not pattern_analysis.get("error"):
        lines.append("## Pattern Analysis")
        summary = pattern_analysis.get("executive_summary", "")
        if summary:
            lines.append(f"> {summary}")
            lines.append("")

        winning_pats = pattern_analysis.get("winning_patterns", [])
        if winning_pats:
            lines.append("### Winning Patterns")
            for p in winning_pats:
                lines.append(f"- **{p.get('pattern', '')}** ({p.get('frequency', '')})")
                lines.append(f"  - Why: {p.get('why_it_works', '')}")
            lines.append("")

        losing_pats = pattern_analysis.get("losing_patterns", [])
        if losing_pats:
            lines.append("### Losing Patterns")
            for p in losing_pats:
                lines.append(f"- **{p.get('pattern', '')}** ({p.get('frequency', '')})")
                lines.append(f"  - Why: {p.get('why_it_fails', '')}")
            lines.append("")

        key_diffs = pattern_analysis.get("key_differences", [])
        if key_diffs:
            lines.append("### Key Differences")
            lines.append("| Dimension | Winners Do | Losers Do | Insight |")
            lines.append("|---|---|---|---|")
            for d in key_diffs:
                lines.append(
                    f"| {d.get('dimension', '')} | "
                    f"{d.get('winners_do', '')} | "
                    f"{d.get('losers_do', '')} | "
                    f"{d.get('insight', '')} |"
                )
            lines.append("")

    # Hypotheses
    if hypotheses:
        lines.append("## Creative Hypotheses")
        for h in hypotheses:
            lines.append(f"### {h.get('hypothesis_id', '')} [{h.get('priority', '')}]")
            lines.append(f"**{h.get('hypothesis', '')}**")
            lines.append(f"- Format: {h.get('test_format', '')}")
            lines.append(f"- Brief: {h.get('script_direction', '')}")
            lines.append(f"- Metric: {h.get('success_metric', '')}")
            lines.append(f"- Confidence: {h.get('confidence', '')}")
            lines.append("")

    # Novelty filter
    if novelty:
        lines.append("## Pattern Novelty Analysis")
        if hasattr(novelty, "winner_signals") and novelty.winner_signals:
            lines.append("### Differentiating Winner Patterns")
            for sig in novelty.winner_signals:
                lines.append(
                    f"- `{sig.pattern}`: {sig.winner_rate*100:.0f}% winners vs "
                    f"{sig.loser_rate*100:.0f}% losers ({sig.signal_strength})"
                )
            lines.append("")
        if hasattr(novelty, "baseline_patterns") and novelty.baseline_patterns:
            lines.append("### Baseline (Non-Differentiating)")
            for sig in novelty.baseline_patterns:
                lines.append(f"- `{sig.pattern}`: {sig.total_rate*100:.0f}% of all ads")
            lines.append("")

    return "\n".join(lines)
