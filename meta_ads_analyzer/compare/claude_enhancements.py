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
    # Extract brand names
    brand_names = [p.name for p in market_map.profiles]

    # Build comparative analysis data from brand reports
    brand_analyses = []
    for report in brand_reports:
        pr = report.pattern_report
        brand_analyses.append({
            'brand': report.advertiser.page_name,
            'ads_analyzed': pr.total_ads_analyzed,
            'root_causes': pr.root_cause_patterns[:5],  # Top 5
            'mechanisms': pr.mechanism_patterns[:5],
            'proof_elements': pr.proof_gaps[:10],
            'belief_gaps': pr.belief_gaps[:10],
            'objection_gaps': pr.objection_gaps[:10],
            'ingredient_transparency': pr.ingredient_transparency_analysis,
            'unfalsifiability': pr.unfalsifiability_analysis,
            'awareness_level': pr.awareness_level_distribution,
        })

    # Summarize saturation zones
    saturation_summary = {}
    for dim_type, zone in market_map.saturation.items():
        saturation_summary[dim_type] = {
            'saturated': [{'dimension': c.dimension, 'coverage': c.coverage_percent, 'brands': list(c.brands.keys())}
                         for c in zone.saturated],
            'whitespace': [{'dimension': c.dimension, 'coverage': c.coverage_percent}
                          for c in zone.whitespace[:10]],
        }

    # Dataset size adaptation
    brand_count = len(brand_reports)
    dataset_context = ""

    if brand_count < 5:
        dataset_context = f"""

## Dataset Size Context

This analysis covers only {brand_count} brands. Apply these adjustments:

1. **Increased Scrutiny Per Brand**: With limited competitors, analyze each brand's strategy in greater depth
2. **Pattern Confidence**: Mark all patterns with confidence levels (low/medium/high based on sample size)
3. **Extrapolation Caution**: Note where conclusions are drawn from limited data
4. **Missing Market Segments**: Consider that {brand_count} brands may not represent full market spectrum

For each opportunity identified, annotate:
- Sample size used (e.g., "2 of 3 brands avoid X")
- Confidence level (high/medium/low)
- Risk of sampling bias
"""

    prompt = f"""You are an expert direct response copywriter and competitive strategist. Analyze this market comparison data with the depth of a Dan Kennedy or Eugene Schwartz competitive analysis.

## Market Context
- **Keyword**: {market_map.meta.get('keyword', 'Unknown')}
- **Brands Compared**: {', '.join(brand_names)}
- **Focus Brand**: {focus_brand or 'None (market-wide analysis)'}
{dataset_context}

## Brand Comparative Analysis
{json.dumps(brand_analyses, indent=2)}

## Market Saturation Zones
{json.dumps(saturation_summary, indent=2)}

## Your Task: Deep Competitive Intelligence

Provide strategic recommendations that match the depth of professional competitive loophole analysis. Your analysis MUST:

1. **Root Cause Chain Comparison**: Compare how deep each brand goes in their root cause explanations. WHO goes deepest? Where's the UPSTREAM gap? What causes the thing they claim is the root cause?

2. **Mechanism Depth Analysis**: Compare WHAT each brand claims their solution does at the molecular/cellular level. Who stops at surface claims? Who goes to cellular pathways? Where's the molecular gap?

3. **Proof Architecture Comparison**: Compare what proof exists across brands. What claims are unproven? What's the vulnerability? How can a competitor provide superior proof?

4. **Belief Installation Mapping**: What beliefs does this market collectively install in customers? What CRITICAL beliefs are missing that would unlock higher conversions?

5. **DR Psychology Explanations**: For each gap, explain WHY it's exploitable using direct response psychology principles. What "aha moment" does it create? What loss aversion does it trigger? What status anxiety does it address?

6. **Specific Hook Language**: Provide actual hook language examples, not generic recommendations. Show me the EXACT hooks that would exploit each gap.

7. **NO FABRICATED METRICS**: Do not invent engagement rates, conversion improvements, or other metrics. Only cite patterns from the actual data provided.

8. **What NOT To Do**: List specific strategic mistakes to avoid based on what competitors are doing wrong.

Return in this JSON structure:

```json
{{
  "market_narrative": "3-5 paragraph deep analysis: What's the competitive landscape? How deep do brands go in their root cause explanations? What's the universal mechanism positioning? What proof architecture vulnerabilities exist across all brands? What beliefs are installed vs missing? Write for someone who needs to exploit competitive weaknesses, not just understand them.",

  "root_cause_comparison": {{
    "deepest_brand": "Which brand goes deepest in root cause explanation",
    "average_depth": "surface/moderate/deep/cellular",
    "upstream_gap": "What causes the thing they all claim is the root cause? The missing upstream explanation.",
    "exploitation_hook": "Exact hook language that exploits this gap. Example: 'Your lymphatic system didn't just fail. Here's the upstream trigger that CAUSED the failure...'"
  }},

  "mechanism_comparison": {{
    "by_brand": [
      {{
        "brand": "Brand name",
        "mechanism_claim": "WHAT they claim it does",
        "depth": "claim-only/process-level/cellular/molecular",
        "molecular_gap": "What molecular pathway is missing from their explanation"
      }}
    ],
    "market_gap": "The molecular/cellular explanation NO ONE provides",
    "exploitation_hook": "Exact hook language. Example: 'Why oral supplements never reach your lymphatic vessels (and the delivery method that does)'"
  }},

  "proof_architecture_comparison": {{
    "unproven_claims": [
      {{
        "claim": "Specific claim made by brands",
        "frequency": "How many brands make this claim",
        "vulnerability": "Why this claim is unproven/unfalsifiable",
        "counter_proof": "What proof would destroy this claim"
      }}
    ],
    "proof_gaps": "What proof does NO brand provide that would be devastatingly credible?"
  }},

  "belief_installation_analysis": {{
    "installed_beliefs": ["What beliefs does the market collectively install"],
    "missing_beliefs": [
      {{
        "belief": "Specific belief that's missing",
        "why_critical": "Why this belief is necessary for conversions",
        "installation_hook": "Exact hook language to install this belief"
      }}
    ]
  }},

  "top_opportunities": [
    {{
      "dimension": "Specific dimension or strategic gap",
      "category": "root_cause/mechanism/proof/belief/dimension_gap",
      "why_exploitable": "DR psychology explanation: What aha moment does this create? What emotional trigger? What loss aversion?",
      "execution_hooks": [
        "Exact hook example 1",
        "Exact hook example 2",
        "Exact hook example 3"
      ],
      "defensibility": "Why this gap is hard for competitors to close once you establish it"
    }}
  ],

  "contrarian_plays": [
    {{
      "conventional_wisdom": "What the entire market does",
      "contrarian_approach": "The opposite strategic move",
      "psychological_rationale": "Why going against the grain works using DR psychology principles",
      "risk_mitigation": "How to derisk this contrarian approach"
    }}
  ],

  "what_not_to_do": [
    "Specific strategic mistake to avoid with reasoning"
  ]
}}
```

## CRITICAL RULES
- Compare actual root cause depth across brands using the data provided
- Explain molecular/cellular gaps in mechanism claims
- Cite actual proof architecture vulnerabilities from the data
- Provide SPECIFIC hook language, not generic templates
- NO fabricated metrics or made-up percentages
- Explain DR psychology behind every opportunity
- Ground everything in the actual brand analysis data provided

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
