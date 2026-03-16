"""Pattern analyzer for creative feedback loop.

Uses Claude to generate insights from extracted ad components.
Enforces insight quality rules: specific numbers, named ads, A vs B comparisons.
Respects operator priority settings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

import anthropic

logger = logging.getLogger(__name__)

PATTERN_ANALYSIS_PROMPT = """You are a senior media buyer analyzing ad performance data. You speak like a practitioner talking to your team — direct, specific, data-driven. NOT like an academic.

ANALYSIS DATA:
{analysis_data}

{priority_injection}

{previous_notes_injection}

RULES — FOLLOW EXACTLY:
1. Every insight MUST include specific numbers: how many winners, how many losers, what ROAS, what spend.
2. Every insight MUST name specific ads as examples (use ad names from the data).
3. Every insight MUST use clear A vs B comparison language: "Winners do X while losers do Y."
4. Write like a media buyer talking to their team, NOT like an academic paper.
5. If a pattern appears in > 85% of ALL ads (winners AND losers), label it "BASELINE — already standard, not a differentiator" and do NOT present it as an insight.
6. Focus on the DELTA — patterns where winners and losers diverge significantly.

GOOD insight format:
"First-person organ personification hooks appear in 4 of 5 top winners (avg ROAS 1.52, avg spend $45k) but 0 of 8 losers. Scripts like B310_V1 used 'Your kidneys are drowning in sludge' while losing scripts used authority claims like 'Doctors recommend...'"

BAD insight format (DO NOT generate):
"General(LCC) avatar targeting with symptom specificity creates broad reach while maintaining relevance"

Return ONLY valid JSON with this structure:
{{
  "insights": [
    {{
      "title": "Short pattern name",
      "detail": "Full insight with numbers, ad names, and A vs B comparison",
      "winner_count": 4,
      "loser_count": 0,
      "avg_roas": 1.52,
      "avg_spend": 45000,
      "is_baseline": false,
      "confidence": "high | medium | low"
    }}
  ],
  "learnings": [
    "Key learning 1 — actionable takeaway with data",
    "Key learning 2"
  ],
  "hypotheses": [
    "Hypothesis 1 — what to test next and why, based on data patterns",
    "Hypothesis 2"
  ],
  "executive_summary": "2-3 sentence summary of the most important findings"
}}"""


async def analyze_patterns(
    ads_with_extractions: list[dict[str, Any]],
    dashboard_data: dict[str, list[dict]],
    priority_prompt: str = "",
    previous_notes: str = "",
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Run Claude pattern analysis on extracted ad data.

    Args:
        ads_with_extractions: List of ad dicts with extraction data.
        dashboard_data: Pre-computed dimension tables from structured_splits.
        priority_prompt: Operator priority injection string.
        previous_notes: Previous operator notes for context.
        api_key: Anthropic API key.

    Returns:
        Pattern analysis results dict.
    """
    client = anthropic.AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    # Build analysis data summary
    analysis_summary = _build_analysis_summary(ads_with_extractions, dashboard_data)

    # Build priority injection
    priority_injection = priority_prompt if priority_prompt else ""

    # Build previous notes injection
    notes_injection = ""
    if previous_notes:
        notes_injection = f"The operator previously noted: {previous_notes}\nConsider this when analyzing new data."

    prompt = PATTERN_ANALYSIS_PROMPT.format(
        analysis_data=analysis_summary,
        priority_injection=priority_injection,
        previous_notes_injection=notes_injection,
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        return json.loads(text)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse pattern analysis response: {e}")
        return {"insights": [], "learnings": [], "hypotheses": [], "executive_summary": "Analysis failed to parse."}
    except Exception as e:
        logger.error(f"Pattern analysis failed: {e}")
        return {"insights": [], "learnings": [], "hypotheses": [], "executive_summary": f"Analysis error: {str(e)}"}


def _build_analysis_summary(
    ads: list[dict[str, Any]],
    dashboard_data: dict[str, list[dict]],
) -> str:
    """Build a structured text summary of ad data for Claude analysis."""
    lines = []

    # Overall stats
    total = len(ads)
    winners = [a for a in ads if a.get("status") == "winner"]
    losers = [a for a in ads if a.get("status") == "loser"]

    lines.append(f"DATASET: {total} ads total — {len(winners)} winners, {len(losers)} losers")
    lines.append("")

    # Top winners summary
    lines.append("TOP WINNERS:")
    for ad in sorted(winners, key=lambda a: a.get("spend", 0), reverse=True)[:10]:
        name = ad.get("ad_name", "unknown")
        spend = ad.get("spend", 0)
        roas = ad.get("roas", 0)
        ext = ad.get("extraction", {})
        pain = ext.get("pain_point", "")
        hook_type = ext.get("hook_type", "")
        lines.append(f"  - {name}: ${spend:,.0f} spend, {roas:.2f}x ROAS | Pain: {pain} | Hook: {hook_type}")
    lines.append("")

    # Top losers summary
    lines.append("TOP LOSERS:")
    for ad in sorted(losers, key=lambda a: a.get("spend", 0), reverse=True)[:10]:
        name = ad.get("ad_name", "unknown")
        spend = ad.get("spend", 0)
        roas = ad.get("roas", 0)
        ext = ad.get("extraction", {})
        pain = ext.get("pain_point", "")
        hook_type = ext.get("hook_type", "")
        lines.append(f"  - {name}: ${spend:,.0f} spend, {roas:.2f}x ROAS | Pain: {pain} | Hook: {hook_type}")
    lines.append("")

    # Dashboard dimension summaries (top delta patterns)
    lines.append("DIMENSION ANALYSIS (sorted by winner-loser delta):")
    dim_labels = {
        "pain_point": "Pain Points", "symptoms": "Symptoms",
        "root_cause_depth": "Root Cause Depth", "root_cause_chain": "Root Cause Chain",
        "mechanism_ump": "Mechanisms UMP", "mechanism_ums": "Mechanisms UMS",
        "ad_format": "Ad Formats", "avatar": "Avatars",
        "awareness_level": "Awareness Levels", "lead_type": "Lead Types",
        "hook_type": "Hook Patterns", "emotional_triggers": "Emotional Triggers",
        "language_patterns": "Language Patterns",
    }
    for dim_key, rows in dashboard_data.items():
        label = dim_labels.get(dim_key, dim_key)
        lines.append(f"\n  {label}:")
        for row in rows[:5]:  # Top 5 by delta
            prefix = "+" if row["delta"] > 0 else ""
            lines.append(
                f"    {row['value']}: {row['pct_all']:.0f}% all, "
                f"{row['pct_winners']:.0f}% winners, {row['pct_losers']:.0f}% losers, "
                f"delta {prefix}{row['delta']:.0f}%, avg ROAS {row['avg_roas']:.2f}x, "
                f"spend ${row['total_spend']:,.0f}"
            )

    # Individual ad extractions for detail
    lines.append("\n\nINDIVIDUAL AD EXTRACTIONS:")
    for ad in ads[:30]:  # Limit to avoid token overflow
        name = ad.get("ad_name", "unknown")
        status = ad.get("status", "unknown")
        spend = ad.get("spend", 0)
        roas = ad.get("roas", 0)
        ext = ad.get("extraction", {})

        lines.append(f"\n  [{status.upper()}] {name} — ${spend:,.0f} spend, {roas:.2f}x ROAS")
        if ext.get("hooks"):
            lines.append(f"    Hooks: {'; '.join(ext['hooks'][:2])}")
        if ext.get("pain_point"):
            lines.append(f"    Pain Point: {ext['pain_point']}")
        if ext.get("root_cause", {}).get("chain"):
            lines.append(f"    Root Cause Chain: {ext['root_cause']['chain']}")
        if ext.get("mechanism", {}).get("ump"):
            lines.append(f"    UMP: {ext['mechanism']['ump']}")
        if ext.get("avatar", {}).get("behavior"):
            avatar = ext["avatar"]
            lines.append(f"    Avatar: {avatar['behavior']} → {avatar.get('impact', '')}")

    return "\n".join(lines)
