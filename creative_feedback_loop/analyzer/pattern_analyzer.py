"""Pattern analyzer for creative feedback loop.

Wraps Claude API pattern analysis and enriches opportunity dicts with actual
structured fields (winner_count, loser_count, avg_roas) parsed from the
response text and/or dashboard data.

BUG 2 FIX: Previously returned winner_count=0, loser_count=0, avg_roas=0 on
every opportunity card because the structured fields were never populated.
Now parses these numbers from Claude's response text (e.g. "8 winner ads")
and falls back to dashboard data counts.
"""

from __future__ import annotations

import re
from typing import Any


def analyze_patterns(
    response_text: str,
    dashboard_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse opportunity cards from Claude pattern analysis response.

    Extracts structured fields (winner_count, loser_count, avg_roas, score)
    from the response text. Falls back to dashboard_data counts if text
    parsing fails.

    Args:
        response_text: Raw text from Claude pattern analysis.
        dashboard_data: Optional dashboard data dict with dimension-level
            winner/loser counts and ROAS values.

    Returns:
        List of opportunity dicts with populated structured fields.
    """
    opportunities = _parse_opportunities_from_text(response_text)

    # Enrich with dashboard data if available
    if dashboard_data:
        _enrich_from_dashboard(opportunities, dashboard_data)

    return opportunities


def _parse_opportunities_from_text(text: str) -> list[dict[str, Any]]:
    """Parse opportunity sections from Claude response text.

    Looks for structured opportunity blocks and extracts both the narrative
    text and embedded numeric fields.
    """
    opportunities = []

    # Split on common opportunity delimiters
    # Claude typically outputs numbered opportunities or ### headers
    sections = re.split(r'(?:^|\n)(?:#{1,3}\s*)?(?:Opportunity\s*#?\d+|OPPORTUNITY\s*#?\d+)[:\s]*', text, flags=re.IGNORECASE)

    # If no structured sections found, treat entire text as one opportunity
    if len(sections) <= 1:
        opp = _extract_fields_from_section(text)
        if opp.get("text"):
            opportunities.append(opp)
        return opportunities

    for section in sections[1:]:  # Skip preamble before first opportunity
        section = section.strip()
        if not section:
            continue
        opp = _extract_fields_from_section(section)
        if opp.get("text"):
            opportunities.append(opp)

    return opportunities


def _extract_fields_from_section(section: str) -> dict[str, Any]:
    """Extract structured fields from an opportunity section.

    Parses patterns like:
        "8 winner ads", "12 loser ads", "1.42x ROAS", "Score: 85/100"
        "Winners: 8", "Losers: 12", "Avg ROAS: 1.42x"
    """
    opp: dict[str, Any] = {"text": section.strip()}

    # Parse winner count: "8 winner ads", "Winners: 8", "8 winners"
    winner_patterns = [
        r'(\d+)\s+winner\s*(?:ads?)?',
        r'[Ww]inners?[:\s]+(\d+)',
    ]
    for pattern in winner_patterns:
        m = re.search(pattern, section, re.IGNORECASE)
        if m:
            opp["winner_count"] = int(m.group(1))
            break

    # Parse loser count: "12 loser ads", "Losers: 12", "12 losers"
    loser_patterns = [
        r'(\d+)\s+loser\s*(?:ads?)?',
        r'[Ll]osers?[:\s]+(\d+)',
    ]
    for pattern in loser_patterns:
        m = re.search(pattern, section, re.IGNORECASE)
        if m:
            opp["loser_count"] = int(m.group(1))
            break

    # Parse ROAS: "1.42x ROAS", "ROAS: 1.42x", "Avg ROAS: 1.42x"
    roas_patterns = [
        r'(\d+\.?\d*)\s*x\s*ROAS',
        r'ROAS[:\s]+(\d+\.?\d*)\s*x?',
        r'[Aa]vg\s*ROAS[:\s]+(\d+\.?\d*)',
    ]
    for pattern in roas_patterns:
        m = re.search(pattern, section, re.IGNORECASE)
        if m:
            opp["avg_roas"] = float(m.group(1))
            break

    # Parse score: "Score: 85/100", "85/100"
    score_match = re.search(r'[Ss]core[:\s]+(\d+)\s*/\s*100', section)
    if not score_match:
        score_match = re.search(r'(\d+)\s*/\s*100', section)
    if score_match:
        opp["score"] = int(score_match.group(1))

    # Parse title: first line or bold text
    title_match = re.search(r'^[#*]*\s*(.+?)(?:\n|$)', section.strip())
    if title_match:
        opp["title"] = re.sub(r'[#*]', '', title_match.group(1)).strip()

    # Ensure defaults for missing fields
    opp.setdefault("winner_count", 0)
    opp.setdefault("loser_count", 0)
    opp.setdefault("avg_roas", 0.0)
    opp.setdefault("score", 0)
    opp.setdefault("title", "Untitled Opportunity")

    return opp


def _enrich_from_dashboard(
    opportunities: list[dict[str, Any]],
    dashboard_data: dict[str, Any],
) -> None:
    """Enrich opportunity dicts with data from the dashboard.

    If an opportunity still has 0 for winner_count/loser_count/avg_roas,
    try to pull actual values from the dashboard dimension data.
    """
    dimensions = dashboard_data.get("dimensions", [])
    if not dimensions:
        return

    # Compute aggregate winner/loser counts across all dimensions
    total_winners = 0
    total_losers = 0
    roas_values = []

    for dim in dimensions:
        for val in dim.get("values", []):
            w = val.get("winner_count", 0)
            l = val.get("loser_count", 0)
            total_winners += w
            total_losers += l
            if val.get("avg_roas", 0) > 0:
                roas_values.append(val["avg_roas"])

    avg_roas = sum(roas_values) / len(roas_values) if roas_values else 0.0

    # Also try to match opportunities to specific dimensions by keyword
    for opp in opportunities:
        # If fields are still at default 0, fill from dashboard aggregates
        if opp.get("winner_count", 0) == 0 and total_winners > 0:
            # Try dimension-specific matching first
            matched = _match_opportunity_to_dimension(opp, dimensions)
            if matched:
                opp["winner_count"] = matched.get("winner_count", total_winners)
                opp["loser_count"] = matched.get("loser_count", total_losers)
                opp["avg_roas"] = matched.get("avg_roas", avg_roas)
            else:
                opp["winner_count"] = total_winners
                opp["loser_count"] = total_losers
                opp["avg_roas"] = round(avg_roas, 2)


def _match_opportunity_to_dimension(
    opp: dict[str, Any],
    dimensions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Try to match an opportunity to a specific dimension value by keyword overlap."""
    opp_text = (opp.get("text", "") + " " + opp.get("title", "")).lower()

    best_match = None
    best_score = 0

    for dim in dimensions:
        dim_name = dim.get("name", "").lower()
        for val in dim.get("values", []):
            val_name = val.get("value", "").lower()
            # Simple keyword matching
            score = 0
            if val_name and val_name in opp_text:
                score += 3
            if dim_name and dim_name in opp_text:
                score += 1
            if score > best_score:
                best_score = score
                best_match = val

    return best_match


def format_opportunity_card(opp: dict[str, Any]) -> str:
    """Format a single opportunity as a display string.

    Output:
        Title of Opportunity
        Winners: 8 | Losers: 12 | Avg ROAS: 1.42x | Score: 85/100
        [opportunity text]
    """
    title = opp.get("title", "Untitled Opportunity")
    winner_count = opp.get("winner_count", 0)
    loser_count = opp.get("loser_count", 0)
    avg_roas = opp.get("avg_roas", 0.0)
    score = opp.get("score", 0)

    stats_line = (
        f"Winners: {winner_count} | Losers: {loser_count} | "
        f"Avg ROAS: {avg_roas:.2f}x | Score: {score}/100"
    )

    return f"{title}\n{stats_line}"
