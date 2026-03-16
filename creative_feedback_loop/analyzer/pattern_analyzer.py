"""Claude-powered pattern analysis for creative feedback loop.

Analyzes winner and loser ad scripts to find patterns that differentiate
high-performing creatives from low-performing ones.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


async def analyze_creative_patterns(
    winners: list[dict[str, Any]],
    losers: list[dict[str, Any]],
    brand_name: str,
    model: str = "claude-sonnet-4-20250514",
) -> dict[str, Any]:
    """Run Claude-powered pattern analysis on winners vs losers.

    Args:
        winners: List of winner ad dicts with 'ad_name', 'script', 'spend', 'roas'.
        losers: List of loser ad dicts with same keys.
        brand_name: Brand name for context.
        model: Claude model to use.

    Returns:
        Dict with pattern analysis results.
    """
    client = anthropic.AsyncAnthropic()

    winners_text = _format_ads_for_prompt(winners, "WINNER")
    losers_text = _format_ads_for_prompt(losers, "LOSER")

    prompt = f"""You are a direct-response advertising analyst. Analyze these winning and losing ad creatives for {brand_name}.

WINNERS (ROAS above threshold, profitable):
{winners_text}

LOSERS (ROAS below threshold or zero, unprofitable):
{losers_text}

Analyze the differences. Return JSON with:
{{
  "winning_patterns": [
    {{"pattern": "description", "frequency": "X of Y winners", "example": "quote from ad", "why_it_works": "explanation"}}
  ],
  "losing_patterns": [
    {{"pattern": "description", "frequency": "X of Y losers", "example": "quote from ad", "why_it_fails": "explanation"}}
  ],
  "key_differences": [
    {{"dimension": "hook/angle/format/offer/etc", "winners_do": "what winners do", "losers_do": "what losers do", "insight": "why this matters"}}
  ],
  "actionable_recommendations": [
    {{"priority": 1, "action": "specific action", "expected_impact": "what should happen", "based_on": "which pattern"}}
  ],
  "executive_summary": "2-3 sentence summary of the most important findings"
}}"""

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=8192,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        # Extract JSON
        import re
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            return json.loads(json_match.group())
        logger.error("No JSON found in Claude response")
        return {"error": "No JSON in response", "raw": text[:500]}

    except Exception as e:
        logger.error(f"Pattern analysis failed: {e}")
        return {"error": str(e)}


def _format_ads_for_prompt(ads: list[dict[str, Any]], label: str) -> str:
    """Format ads for the analysis prompt."""
    if not ads:
        return f"(No {label.lower()} ads with scripts)"

    lines = []
    for i, ad in enumerate(ads, 1):
        name = ad.get("ad_name", "Unknown")
        spend = ad.get("spend", 0)
        roas = ad.get("roas", 0)
        script = ad.get("script", "").strip()

        lines.append(f"--- {label} #{i}: {name} ---")
        lines.append(f"Spend: ${spend:,.2f} | ROAS: {roas:.2f}")
        if script:
            # Truncate very long scripts
            if len(script) > 2000:
                script = script[:2000] + "... [truncated]"
            lines.append(f"Script:\n{script}")
        else:
            lines.append("(No script available)")
        lines.append("")

    return "\n".join(lines)
