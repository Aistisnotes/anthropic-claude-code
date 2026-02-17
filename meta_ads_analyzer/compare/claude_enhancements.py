"""Optional Claude-powered strategic analysis for compare command."""

from __future__ import annotations

import json
from typing import Optional

import anthropic

from meta_ads_analyzer.models import BrandReport, MarketMap, StrategicRecommendations
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def generate_strategic_recommendations(
    market_map: MarketMap,
    brand_reports: list[BrandReport],
    focus_brand: Optional[str] = None,
    config: dict = None,
) -> StrategicRecommendations:
    """Generate Claude-enhanced strategic recommendations for market comparison.

    Args:
        market_map: Market map with dimension matrices and saturation zones
        brand_reports: List of brand reports
        focus_brand: Optional focus brand for brand-specific recommendations
        config: Config dict with API settings

    Returns:
        StrategicRecommendations with market narrative, opportunities, contrarian plays, actions
    """
    if config is None:
        config = {}

    logger.info("Generating Claude-enhanced strategic recommendations")

    prompt = _build_strategic_prompt(market_map, brand_reports, focus_brand)

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514"),
        max_tokens=8192,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse Claude's response
    data = _parse_strategic_response(response.content[0].text)

    return StrategicRecommendations(**data)


def _build_strategic_prompt(
    market_map: MarketMap, brand_reports: list[BrandReport], focus_brand: Optional[str]
) -> str:
    """Build strategic analysis prompt for Claude.

    Args:
        market_map: Market map with coverage data
        brand_reports: List of brand reports
        focus_brand: Optional focus brand

    Returns:
        Prompt string
    """
    # Summarize market overview
    brand_names = [p.name for p in market_map.profiles]

    # Summarize saturation zones
    saturation_summary = {}
    for dim_type, zone in market_map.saturation.items():
        saturation_summary[dim_type] = {
            'saturated': len(zone.saturated),
            'moderate': len(zone.moderate),
            'whitespace': len(zone.whitespace),
        }

    # Find top gaps by coverage
    top_gaps = []
    for dim_type, coverages in market_map.matrices.items():
        for cov in coverages:
            if cov.coverage_percent < 30:  # Whitespace
                top_gaps.append(
                    {
                        'dimension': cov.dimension,
                        'category': dim_type,
                        'coverage': cov.coverage_percent,
                        'brands_using': list(cov.brands.keys()),
                    }
                )

    # Sort by coverage ascending (biggest gaps first)
    top_gaps.sort(key=lambda g: g['coverage'])
    top_gaps = top_gaps[:20]  # Top 20 gaps

    prompt = f"""You are a senior competitive strategy analyst. Analyze this market comparison data and provide strategic recommendations.

## Market Overview
- **Keyword**: {market_map.meta.get('keyword', 'Unknown')}
- **Brands Compared**: {', '.join(brand_names)}
- **Focus Brand**: {focus_brand or 'None (market-wide analysis)'}

## Saturation Analysis
{json.dumps(saturation_summary, indent=2)}

## Top Market Gaps (Low Coverage = Opportunity)
{json.dumps(top_gaps[:10], indent=2)}

## Brand Profiles
{json.dumps([p.model_dump() for p in market_map.profiles], indent=2)}

## Your Task

Provide strategic recommendations in JSON format:

```json
{{
  "market_narrative": "3-4 paragraph executive summary: What's the competitive landscape? What are the major gaps? What's the overall strategic picture? Write for a CMO who needs to understand market positioning.",

  "top_opportunities": [
    {{
      "dimension": "Specific dimension name",
      "category": "hooks/angles/emotions/formats/offers/ctas",
      "why_opportunity": "Why this is a high-impact opportunity (2-3 sentences)",
      "exploitation_strategy": "Specific execution approach with hook examples (2-3 sentences)",
      "expected_impact": "What competitive advantage this creates"
    }}
  ],

  "contrarian_plays": [
    {{
      "conventional_wisdom": "What everyone in the market is doing",
      "contrarian_approach": "The opposite/different approach to take",
      "rationale": "Why going against the grain works here",
      "risk_assessment": "What could go wrong and how to mitigate"
    }}
  ],

  "immediate_actions": [
    {{
      "action": "Specific action to take",
      "timeline": "How long to execute (e.g., '2-4 weeks')",
      "resources_needed": "What's required",
      "success_metric": "How to measure success"
    }}
  ]
}}
```

## Guidelines
- Focus on **actionable** opportunities with **specific** execution guidance
- Identify 3-5 top opportunities (prioritize high-gap dimensions with validation signals)
- Provide 2-3 contrarian plays (opportunities from doing the opposite of market consensus)
- List 3-5 immediate actions (can be executed in next 30 days)
- If focus brand specified, tailor recommendations to their blind spots and strengths
- Be **ruthlessly specific** - no generic advice like "improve messaging"
- Ground recommendations in the actual gap data provided

Return ONLY valid JSON, no markdown formatting."""

    return prompt


def _parse_strategic_response(text: str) -> dict:
    """Parse Claude's strategic recommendations response.

    Args:
        text: Raw response text from Claude

    Returns:
        Dict with parsed recommendations
    """
    # Try to extract JSON from response
    try:
        # Look for JSON code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            json_text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            json_text = text[start:end].strip()
        else:
            # Assume entire response is JSON
            json_text = text.strip()

        data = json.loads(json_text)
        return data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        logger.debug(f"Response text: {text[:500]}...")

        # Return minimal valid structure
        return {
            'market_narrative': text[:1000],  # Use first 1000 chars as narrative
            'top_opportunities': [],
            'contrarian_plays': [],
            'immediate_actions': [],
        }
