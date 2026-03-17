"""Strategic opportunity analyzer for internal creative performance data.

Modeled after meta_ads_analyzer/compare/strategic_loophole_doc.py but adapted
for INTERNAL creative data (not competitive analysis).

Generates 5-7 SCORED STRATEGIC OPPORTUNITIES using Claude:
a. SCALE WINNERS: Patterns proven at high spend across multiple ads
b. EFFICIENCY GAPS: Same spend level, different ROAS
c. UNDERTESTED ANGLES: Low spend but promising early signals
d. EXPENSIVE MISTAKES: High-spend losers sharing a pattern
e. COMBINATION PLAYS: Pain point + mechanism + avatar combos

Also generates:
- 2-3 Expensive Mistake cards
- 3-5 Drift Alert cards (recent vs top 50 comparison)
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import anthropic
import pandas as pd


OPPORTUNITY_PROMPT = """You are an expert media buyer analyzing internal creative performance data for a direct response brand.

## OPERATOR PRIORITY: {priority}
{priority_instruction}

## PERFORMANCE DATA

### Winner Ads (ROAS above threshold):
{winners_json}

### Loser Ads (ROAS below threshold, significant spend):
{losers_json}

### Untested Ads (insufficient spend to judge):
{untested_json}

### DIMENSION SPLITS (winner % vs loser % for each pattern):
{dimension_splits_json}

## YOUR TASK

Generate 5-7 SCORED STRATEGIC OPPORTUNITIES based on the data above.

OPPORTUNITY TYPES (generate a mix):

a. **SCALE WINNERS**: Patterns proven at high spend across multiple ads.
   "This works. Keep doing it. Test more variations."
   Requirements: 3+ winner ads using pattern, $50k+ combined spend

b. **EFFICIENCY GAPS**: Same spend level, different ROAS.
   "Switching from X to Y improves returns."
   Requirements: Compare ads at similar spend ($5k+), show ROAS difference

c. **UNDERTESTED ANGLES**: Low spend but promising early signals.
   "Promising but unproven at scale. Test at higher budget before committing."
   Requirements: 1-2 ads with ROAS > 1.5x but spend < $5k
   CRITICAL: Never call these "massive opportunity" — call them "early signal worth testing"

d. **EXPENSIVE MISTAKES**: High-spend losers sharing a pattern.
   "Stop doing this immediately. It's costing money."
   Requirements: 3+ loser ads, $20k+ combined wasted spend

e. **COMBINATION PLAYS**: Pain point + mechanism + avatar combos that winners use but losers don't.
   Look at Root Cause × Mechanism matrix patterns.

## SCORING FORMULA (0-100):
- Evidence strength: 3+ winner ads using pattern = 25pts, 5+ = 35pts
- Spend proof: $50k+ combined spend on pattern = 20pts, $100k+ = 30pts
- Delta: winner% - loser% > 30% = 20pts, > 20% = 10pts
- Consistency: pattern works across different ad formats/editors = 15pts

## EXPENSIVE MISTAKES (generate 2-3 separately):
Look for high-spend loser patterns. Each needs:
- title: what the mistake is
- cost: total wasted spend and avg ROAS
- pattern: what these losers have in common
- worst_offenders: specific ad names with spend and ROAS
- what_to_do: what works instead (reference winning patterns)
- action: clear "stop/pause/change" directive

## RULES
- Every insight MUST reference specific ad names with their spend and ROAS
- Every comparison MUST be between SIMILAR spend levels
- Never call something "massive opportunity" without $10k+ combined spend proof
- Write like a media buyer talking to their team, not an academic paper
- Use "did/didn't" language: "Winners did X, losers didn't"
- If a pattern appears in > 85% of ALL ads (winners AND losers), label it "BASELINE" and skip it
- Always specify: "Among ads spending $X+, pattern Y produced Z ROAS vs pattern W at Q ROAS"

## OUTPUT FORMAT

Return valid JSON:

```json
{{
  "opportunities": [
    {{
      "score": 87,
      "type": "scale_winner",
      "title": "Scale Molecular Kidney Scripts at High Spend",
      "evidence": "8 winner ads use molecular kidney root causes, spending $285k combined at 1.38x avg ROAS. Top examples: B310_V1 ($117k, 1.29x), B150_V1 ($89k, 1.24x), B279_V3 ($31k, 1.38x)",
      "loser_comparison": "12 loser ads used surface-level root causes ('toxins in your body') averaging 0.7x ROAS at $45k combined spend.",
      "why_it_works": "Molecular depth creates believable mechanism that surface claims can't match. Educated buyers convert at higher rates.",
      "how_to_execute": {{
        "Root cause": "Renal lymphatic clogging",
        "Mechanism": "Drainage compound targets vessel walls",
        "Avatar": "Women who drink wine weekly",
        "Hook approach": "First-person organ personification",
        "Format": "UGC or Long Form Static"
      }},
      "risk": "LOW — proven at $100k+ scale across multiple ads"
    }}
  ],
  "expensive_mistakes": [
    {{
      "title": "Surface-Level Thyroid Scripts",
      "cost": "$45,000 wasted across 6 loser ads at 0.72x avg ROAS",
      "pattern": "Thyroid ads using surface root causes without explaining WHY consistently underperform.",
      "worst_offenders": "B255_V1 ($6.4k, 0.91x), B398_V2 ($3k, 0.65x)",
      "what_to_do": "Kidney ads with molecular depth average 1.38x. Apply same depth to thyroid if testing thyroid.",
      "action": "Stop all surface-level thyroid scripts. Either go molecular depth or pause thyroid testing entirely."
    }}
  ]
}}
```

Generate 5-7 opportunities and 2-3 expensive mistakes. Return ONLY valid JSON."""


DRIFT_PROMPT = """You are an expert media buyer comparing RECENT creative performance against TOP 50 proven ads.

## TOP 50 PROVEN ADS (historical best performers):
{top50_json}

## TOP 50 DIMENSION SPLITS:
{top50_splits_json}

## RECENT ADS:
{recent_json}

## RECENT DIMENSION SPLITS:
{recent_splits_json}

## YOUR TASK

Generate 3-5 DRIFT ALERT CARDS comparing recent creative direction against proven top 50 patterns.

ALERT TYPES:

1. **DRIFT** (⚠️): Recent creative is moving AWAY from a proven pattern
   - Show what % of top 50 used the pattern vs what % of recent ads
   - Show ROAS comparison
   - Recommend returning to the proven pattern

2. **CONSISTENT** (✅): Recent creative is correctly doubling down on what works
   - Show the pattern being maintained or strengthened
   - Show if ROAS is improving or stable

3. **NEW DISCOVERY** (🆕): Recent creative has found something not in top 50
   - Must have 2+ recent winner ads using the new pattern
   - Show spend and ROAS of the new pattern
   - Recommend careful scaling

## RULES
- Reference specific ad names with spend and ROAS
- Only flag meaningful differences (>15% shift in usage)
- Don't flag patterns that are in <5% of both sets

## OUTPUT FORMAT

Return valid JSON:

```json
{{
  "drift_alerts": [
    {{
      "type": "drift",
      "title": "Shifting away from proven kidney focus",
      "top50_stat": "55% target kidney ($300k spend)",
      "recent_stat": "Only 30% target kidney",
      "impact": "Recent creative is diversifying into cholesterol (20%) but cholesterol ads average 0.9x ROAS vs kidney at 1.4x.",
      "recommendation": "Return to kidney as primary pain point. Test cholesterol only at small budget until ROAS improves."
    }}
  ]
}}
```

Return ONLY valid JSON."""


PRIORITY_INSTRUCTIONS = {
    "Spend Volume": "Rank opportunities by total spend generated. An ad spending $70k at 1.5x matters more than $500 at 3x. Focus on patterns with the MOST dollars flowing through them.",
    "Efficiency": "Rank by ROAS advantage. Focus on what delivers the best return per dollar. A pattern with 2x ROAS at $10k beats 1.2x ROAS at $100k.",
    "New Angles": "Highlight patterns appearing in <20% of ads with ROAS > 1.0. Find underexplored territory with early promise. Weight novelty over proven scale.",
    "General": "Rank by the standard opportunity score formula (evidence strength + spend proof + delta + consistency).",
}


def _prepare_ad_json(df: pd.DataFrame, max_ads: int = 50) -> str:
    """Prepare ad data as JSON for Claude prompt."""
    if df.empty:
        return "[]"

    cols_to_include = [
        "ad_name", "spend", "revenue", "roas", "impressions",
        "pain_point_category", "root_cause", "root_cause_depth",
        "mechanism", "mechanism_depth", "avatar_category",
        "awareness_level", "hook_type", "ad_format",
    ]
    available_cols = [c for c in cols_to_include if c in df.columns]
    subset = df[available_cols].head(max_ads)
    records = subset.to_dict(orient="records")

    # Clean up NaN values
    cleaned = []
    for r in records:
        cleaned.append({k: ("" if pd.isna(v) else v) for k, v in r.items()})

    return json.dumps(cleaned, indent=2, default=str)


def _prepare_dimension_splits(
    df: pd.DataFrame,
    winner_mask: pd.Series,
    loser_mask: pd.Series,
    dimensions: list[str],
) -> str:
    """Prepare dimension split data for the prompt."""
    splits = {}
    total_winners = winner_mask.sum()
    total_losers = loser_mask.sum()

    for dim in dimensions:
        if dim not in df.columns:
            continue

        dim_splits = []
        for val in df[dim].dropna().unique():
            if not val or str(val).lower() in ("unknown", "not specified", "nan", "none", ""):
                continue

            win_count = len(df[winner_mask & (df[dim] == val)])
            lose_count = len(df[loser_mask & (df[dim] == val)])

            win_pct = (win_count / total_winners * 100) if total_winners > 0 else 0
            lose_pct = (lose_count / total_losers * 100) if total_losers > 0 else 0

            val_ads = df[df[dim] == val]
            spend = val_ads["spend"].sum() if "spend" in val_ads.columns else 0
            avg_roas = val_ads["roas"].mean() if "roas" in val_ads.columns else 0

            dim_splits.append({
                "value": str(val),
                "winner_pct": round(win_pct, 1),
                "loser_pct": round(lose_pct, 1),
                "delta": round(win_pct - lose_pct, 1),
                "avg_roas": round(float(avg_roas), 2) if not pd.isna(avg_roas) else 0,
                "spend": round(float(spend), 2) if not pd.isna(spend) else 0,
                "count": len(val_ads),
            })

        if dim_splits:
            splits[dim] = sorted(dim_splits, key=lambda x: abs(x["delta"]), reverse=True)

    return json.dumps(splits, indent=2)


async def generate_strategic_opportunities(
    ads_df: pd.DataFrame,
    winner_mask: pd.Series,
    loser_mask: pd.Series,
    priority: str = "General",
    model: str = "claude-sonnet-4-20250514",
) -> list[dict[str, Any]]:
    """Generate 5-7 scored strategic opportunities using Claude.

    Args:
        ads_df: DataFrame with all ads and extracted dimensions
        winner_mask: Boolean mask for winner ads
        loser_mask: Boolean mask for loser ads
        priority: Operator priority (Spend Volume, Efficiency, New Angles, General)
        model: Claude model to use

    Returns:
        List of opportunity dicts
    """
    untested_mask = ~winner_mask & ~loser_mask

    dimensions = [
        "pain_point_category", "root_cause_depth", "mechanism_depth",
        "avatar_category", "awareness_level", "hook_type", "ad_format",
    ]

    winners_json = _prepare_ad_json(ads_df[winner_mask])
    losers_json = _prepare_ad_json(ads_df[loser_mask])
    untested_json = _prepare_ad_json(ads_df[untested_mask], max_ads=20)
    splits_json = _prepare_dimension_splits(ads_df, winner_mask, loser_mask, dimensions)

    priority_instruction = PRIORITY_INSTRUCTIONS.get(priority, PRIORITY_INSTRUCTIONS["General"])

    prompt = OPPORTUNITY_PROMPT.format(
        priority=priority,
        priority_instruction=priority_instruction,
        winners_json=winners_json,
        losers_json=losers_json,
        untested_json=untested_json,
        dimension_splits_json=splits_json,
    )

    client = anthropic.AsyncAnthropic()
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=8192,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        data = _parse_json_response(text)

        opportunities = data.get("opportunities", [])
        mistakes = data.get("expensive_mistakes", [])

        # Add type to mistakes
        for m in mistakes:
            m["type"] = "expensive_mistake"

        return opportunities + mistakes

    except Exception as e:
        return [{
            "score": 0,
            "type": "scale_winner",
            "title": f"Analysis failed: {str(e)[:100]}",
            "evidence": "Could not generate opportunities. Check API key and try again.",
            "loser_comparison": "",
            "why_it_works": "",
            "how_to_execute": "",
            "risk": "N/A",
        }]


async def generate_drift_alerts(
    recent_df: pd.DataFrame,
    top50_df: pd.DataFrame,
    recent_winner_mask: pd.Series,
    recent_loser_mask: pd.Series,
    top50_winner_mask: pd.Series,
    top50_loser_mask: pd.Series,
    model: str = "claude-sonnet-4-20250514",
) -> list[dict[str, Any]]:
    """Generate 3-5 drift alert cards comparing recent vs top 50 ads.

    Args:
        recent_df: DataFrame with recent ads
        top50_df: DataFrame with top 50 proven ads
        recent_winner_mask, recent_loser_mask: Masks for recent ads
        top50_winner_mask, top50_loser_mask: Masks for top 50 ads
        model: Claude model to use

    Returns:
        List of drift alert dicts
    """
    dimensions = [
        "pain_point_category", "root_cause_depth", "mechanism_depth",
        "avatar_category", "awareness_level", "hook_type", "ad_format",
    ]

    recent_json = _prepare_ad_json(recent_df)
    top50_json = _prepare_ad_json(top50_df)
    recent_splits = _prepare_dimension_splits(recent_df, recent_winner_mask, recent_loser_mask, dimensions)
    top50_splits = _prepare_dimension_splits(top50_df, top50_winner_mask, top50_loser_mask, dimensions)

    prompt = DRIFT_PROMPT.format(
        top50_json=top50_json,
        top50_splits_json=top50_splits,
        recent_json=recent_json,
        recent_splits_json=recent_splits,
    )

    client = anthropic.AsyncAnthropic()
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        data = _parse_json_response(text)
        return data.get("drift_alerts", [])

    except Exception as e:
        return [{
            "type": "drift",
            "title": f"Drift analysis failed: {str(e)[:80]}",
            "top50_stat": "",
            "recent_stat": "",
            "impact": "Could not compare datasets. Check API key.",
            "recommendation": "Retry analysis.",
        }]


def _parse_json_response(text: str) -> dict:
    """Parse Claude's JSON response."""
    try:
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = text.strip()
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"opportunities": [], "expensive_mistakes": [], "drift_alerts": []}
