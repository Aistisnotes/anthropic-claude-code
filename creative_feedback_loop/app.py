"""Creative Feedback Loop — Output renderer.

Renders the full creative feedback loop output with distinct sections:
  1. Executive Summary (from pattern analysis)
  2. Structured Splits Dashboard (signal cards)
  3. Opportunity Cards (with verified stats)
  4. Learnings (deduplicated, one section only)
  5. Hypotheses (deduplicated, one section only)

BUG 3 FIX: Previously, learnings and hypotheses appeared TWICE:
  - Once inside the raw "Pattern Insights" Claude response text
  - Again in their own dedicated sections
Now the raw Claude response is NOT displayed. Only the parsed/structured
output is rendered in each dedicated section.

BUG 6 FIX: Strips markdown formatting artifacts (**, ##, #, *) and
leaked section headers ("HYPOTHESES:", "LEARNINGS:") from display text.
"""

from __future__ import annotations

import re
from typing import Any

from creative_feedback_loop.analyzer.pattern_analyzer import (
    analyze_patterns,
    format_opportunity_card,
)
from creative_feedback_loop.dashboard.hypotheses import format_hypotheses
from creative_feedback_loop.dashboard.learnings import format_learnings
from creative_feedback_loop.dashboard.structured_splits import render_dashboard


def clean_markdown(text: str) -> str:
    """Strip markdown formatting artifacts from display text.

    Removes: **, ##, #+, *, and leaked section headers like
    "HYPOTHESES:", "LEARNINGS:", "## HYPOTHESES", etc.
    """
    if not text or not isinstance(text, str):
        return text or ""
    # Strip markdown bold/header markers
    cleaned = re.sub(r'\*\*|##|#+', '', text)
    # Strip leading section headers that leaked from Claude's response
    cleaned = re.sub(r'^\s*(?:HYPOTHESES|LEARNINGS|OPPORTUNITIES|EXECUTIVE SUMMARY)\s*:\s*', '', cleaned, flags=re.IGNORECASE)
    # Clean up leftover whitespace
    cleaned = re.sub(r'  +', ' ', cleaned).strip()
    return cleaned


def render_full_output(
    pattern_results: dict[str, Any],
    dashboard_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render the full creative feedback loop output.

    Args:
        pattern_results: Dict from Claude pattern analysis containing:
            - response_text: Raw Claude response (NOT displayed directly)
            - learnings: List of extracted learnings
            - hypotheses: List of extracted hypotheses
            - executive_summary: Optional summary text
        dashboard_data: Optional structured dashboard data with dimensions.

    Returns:
        Structured output dict with sections ready for display.
    """
    output: dict[str, Any] = {"sections": []}

    # ── 1. Executive Summary ──────────────────────────────────────────────
    summary = pattern_results.get("executive_summary", "")
    if summary:
        output["sections"].append({
            "type": "executive_summary",
            "title": "Executive Summary",
            "content": clean_markdown(summary),
        })

    # ── 2. Structured Splits Dashboard ────────────────────────────────────
    if dashboard_data:
        dashboard_result = render_dashboard(dashboard_data)
        output["sections"].append({
            "type": "dashboard",
            "title": "Structured Splits",
            "cards": dashboard_result.get("summary_cards", []),
            "all_signals": dashboard_result.get("all_signals", []),
        })

    # ── 3. Opportunity Cards (with verified stats from dashboard data) ────
    response_text = pattern_results.get("response_text", "")
    opportunities = analyze_patterns(response_text, dashboard_data)
    if opportunities:
        opp_cards = []
        for opp in opportunities:
            card_text = format_opportunity_card(opp)
            # Clean markdown from opportunity text
            opp["text"] = clean_markdown(opp.get("text", ""))
            opp_cards.append({
                "display_text": card_text,
                **opp,
            })
        output["sections"].append({
            "type": "opportunities",
            "title": "Opportunities",
            "cards": opp_cards,
        })

    # ── 4. Learnings (ONLY here — NOT in pattern insights) ────────────────
    raw_learnings = pattern_results.get("learnings", [])
    if raw_learnings:
        formatted = format_learnings(raw_learnings, dashboard_data)
        # Clean markdown artifacts from each learning's display text
        for learning in formatted:
            learning["display_text"] = clean_markdown(learning.get("display_text", ""))
            learning["observation"] = clean_markdown(learning.get("observation", ""))
        output["sections"].append({
            "type": "learnings",
            "title": "Learnings",
            "items": formatted,
        })

    # ── 5. Hypotheses (ONLY here — NOT in pattern insights) ───────────────
    raw_hypotheses = pattern_results.get("hypotheses", [])
    if raw_hypotheses:
        formatted = format_hypotheses(raw_hypotheses)
        # Clean markdown artifacts from each hypothesis
        for hyp in formatted:
            hyp["display_text"] = clean_markdown(hyp.get("display_text", ""))
            hyp["title"] = clean_markdown(hyp.get("title", ""))
            for bullet in hyp.get("bullets", []):
                bullet["value"] = clean_markdown(bullet.get("value", ""))
        output["sections"].append({
            "type": "hypotheses",
            "title": "Hypotheses",
            "items": formatted,
        })

    return output


def render_text_output(
    pattern_results: dict[str, Any],
    dashboard_data: dict[str, Any] | None = None,
) -> str:
    """Render the full output as plain text for CLI display."""
    result = render_full_output(pattern_results, dashboard_data)
    lines: list[str] = []

    for section in result.get("sections", []):
        section_type = section.get("type", "")
        title = section.get("title", "")

        lines.append("")
        lines.append(f"{'=' * 60}")
        lines.append(f"  {title}")
        lines.append(f"{'=' * 60}")
        lines.append("")

        if section_type == "executive_summary":
            lines.append(section.get("content", ""))

        elif section_type == "dashboard":
            for card in section.get("cards", []):
                lines.append(f"  {card.get('display_text', '')}")

        elif section_type == "opportunities":
            for i, card in enumerate(section.get("cards", []), 1):
                lines.append(f"  Opportunity #{i}")
                lines.append(f"  {card.get('display_text', '')}")
                text = card.get("text", "")
                if text:
                    # Indent opportunity text
                    for tline in text.split("\n"):
                        lines.append(f"    {tline}")
                lines.append("")

        elif section_type == "learnings":
            for item in section.get("items", []):
                idx = item.get("index", "")
                lines.append(f"  {idx}. {item.get('display_text', '')}")
                lines.append("")

        elif section_type == "hypotheses":
            for item in section.get("items", []):
                lines.append(f"  {item.get('display_text', '')}")
                lines.append(f"  {'-' * 40}")
                lines.append("")

    return "\n".join(lines)
