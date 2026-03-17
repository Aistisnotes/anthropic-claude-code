"""Pattern analysis using Claude API for creative feedback loop.

Analyzes classified ad data to find multi-dimensional patterns,
learnings, and testable hypotheses.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

import anthropic


async def analyze_patterns(
    classified_data: dict[str, Any],
    top50_data: dict[str, Any],
    brand_name: str = "",
    priority_focus: str = "General",
    specific_focus: str = "",
) -> dict[str, Any]:
    """Async wrapper for pattern analysis using Claude API.

    Args:
        classified_data: Dict with winners, losers, and dimension breakdowns from Section A
        top50_data: Dict with top 50 ads by spend and their dimension breakdowns from Section B
        brand_name: Brand name for context
        priority_focus: Analysis priority (General/Spend Volume/Efficiency/New Angles)
        specific_focus: Free text focus area

    Returns:
        Dict with insights, learnings, hypotheses, top_patterns
    """
    prompt = _build_analysis_prompt(classified_data, top50_data, brand_name, priority_focus, specific_focus)

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16384,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    return _parse_response(text)


def _build_analysis_prompt(
    classified_data: dict[str, Any],
    top50_data: dict[str, Any],
    brand_name: str,
    priority_focus: str,
    specific_focus: str,
) -> str:
    """Build the multi-dimensional pattern analysis prompt."""

    focus_instruction = ""
    if priority_focus == "Spend Volume":
        focus_instruction = "Prioritize patterns with the highest total spend. Volume signals market validation."
    elif priority_focus == "Efficiency":
        focus_instruction = "Prioritize patterns with the best ROAS efficiency, even at lower spend levels."
    elif priority_focus == "New Angles":
        focus_instruction = "Prioritize underexplored dimension combinations that show early promise."

    if specific_focus:
        focus_instruction += f"\n\nAdditional focus requested: {specific_focus}"

    prompt = f"""You are an expert direct response media buyer analyzing Meta ad performance data for {brand_name or 'a brand'}.

## Analysis Priority
{priority_focus}: {focus_instruction}

## Section A — Classified Ads (Winners vs Losers)
{json.dumps(classified_data, indent=2, default=str)}

## Section B — Top 50 Ads by Spend
{json.dumps(top50_data, indent=2, default=str)}

## YOUR TASK

Analyze the data above and produce multi-dimensional pattern insights.

## CRITICAL RULES — EVERY INSIGHT MUST FOLLOW THESE

1. **MULTI-DIMENSIONAL REQUIRED**: Every insight MUST connect 2-3+ dimensions (pain point + awareness, mechanism + format, avatar + pain point, etc.). Single-dimension insights are BANNED.
   - BAD: "Scale kidney campaigns — they have high spend."
   - BAD: "Problem Aware outperforms Solution Aware."
   - GOOD: "All 6 kidney winners use Problem Aware + RenalLymphaticClogged mechanism + LFS format (combined &#36;183k, 1.32x ROAS). All 4 thyroid losers use the SAME mechanism but with Solution Aware positioning (&#36;15k, 0.91x). The mechanism works — the awareness level kills it."

2. **DATA ON EVERYTHING**: Every insight MUST include:
   - Spend data (total spend for ads showing this pattern)
   - ROAS data (average ROAS)
   - Hit rate (X of Y winners/losers show this pattern)
   - Spend share (% of total winner/loser spend)
   - Named specific ads with their numbers

3. **SHOW CONTRAST**: Every insight MUST show "X works because Y doesn't" or "Pattern A in context B wins but in context C loses"

4. **LOGICAL COHERENCE**: The pattern must make logical sense — don't connect unrelated dimensions

5. **VOLUME-EFFICIENCY RATIO**: Prioritize high spend + good ROAS = strongest signal. Low spend with any ROAS = weak signal.

6. **AWARENESS HIERARCHY**: Most Aware / Product Aware are LESS valuable signals. Prioritize Unaware, Problem Aware, Solution Aware patterns.

7. **EXPANSION THINKING**: If something has high spend tolerance AND efficiency, flag it: "This combo works at &#36;117k. Test it with different mechanisms to find the next &#36;100k winner."

## OUTPUT FORMAT

Return valid JSON:

```json
{{
  "insights": [
    {{
      "title": "Short actionable title (max 80 chars)",
      "description": "Full multi-dimensional insight with specific ad names, spend, ROAS data for BOTH winning and losing sides. Must reference 2-3+ dimensions.",
      "dimensions_connected": ["Pain Point", "Awareness Level", "Mechanism"],
      "evidence_from": "Pain Point + Awareness Level + Mechanism",
      "confidence": "HIGH — 6 winners, &#36;183k spend, consistent pattern",
      "score": 87,
      "spend_volume": "&#36;285k",
      "hit_rate": "6/8 winners",
      "winner_data": {{
        "count": 6,
        "total_spend": 183000,
        "avg_roas": 1.32,
        "spend_share_pct": 25,
        "ads": ["B310_V1", "B175_V1", "B229"]
      }},
      "loser_data": {{
        "count": 4,
        "total_spend": 15000,
        "avg_roas": 0.91,
        "spend_share_pct": 8,
        "ads": ["B255_V1", "B255_V2"]
      }}
    }}
  ],
  "top_patterns": [
    {{
      "pattern": "Kidney + Problem Aware + LFS + RenalLymphaticClogged",
      "total_spend": 183000,
      "avg_roas": 1.32,
      "hit_rate": "6/8 winners",
      "hit_rate_pct": 75,
      "expansion_opportunities": [
        "Cholesterol uses same mechanism depth but untested at Problem Aware — test it",
        "Liver + Truckers avatar works with similar mechanism — cross-test format"
      ]
    }}
  ],
  "learnings": [
    {{
      "title": "Problem Aware Beats Solution Aware Across All Pain Points",
      "description": "18 of 24 winners use Problem Aware (combined &#36;395k, 1.29x ROAS) vs 0 Solution Aware winners. 6 Solution Aware losers spent &#36;11k at 0.77x ROAS. Pattern holds for kidney, liver, and thyroid.",
      "confidence": "HIGH",
      "spend_share_pct": 85,
      "hit_rate": "18/24"
    }}
  ],
  "hypotheses": [
    {{
      "title": "Test Problem Aware Framework on Thyroid Scripts",
      "test": "Take B310_V1's Problem Aware + Renal Lymphatic framework and apply to thyroid mechanism",
      "expected_outcome": "1.3x+ ROAS based on kidney pattern (&#36;183k proven). Thyroid with Solution Aware currently at 0.91x — switching awareness level alone should improve by 40%+",
      "based_on_ads": ["B310_V1", "B175_V1", "B279_V3"],
      "risk_level": "MEDIUM",
      "risk_rationale": "Mechanism proven but awareness level switch untested for thyroid",
      "priority": "HIGH"
    }}
  ]
}}
```

## SCORING INSIGHTS (rank by):
- Number of dimensions connected (more = better)
- Spend volume of the pattern (&#36;50k+ = strong, &#36;10k+ = moderate, <&#36;10k = weak)
- ROAS advantage over the counter-pattern
- Logical coherence

Generate 5-7 insights maximum, 5 top patterns, 5-8 learnings, and 3-5 hypotheses.

Return ONLY valid JSON, no markdown formatting."""

    return prompt


def _parse_response(text: str) -> dict[str, Any]:
    """Parse Claude's JSON response."""
    try:
        # Extract JSON from code block if present
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = text.strip()

        data = json.loads(json_str)
        return data

    except json.JSONDecodeError:
        # Return minimal structure
        return {
            "insights": [],
            "top_patterns": [],
            "learnings": [],
            "hypotheses": [],
            "error": "Failed to parse Claude response",
        }
