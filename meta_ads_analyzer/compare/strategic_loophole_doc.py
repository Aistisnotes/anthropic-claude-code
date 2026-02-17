"""Strategic loophole document generator - produces 5-7 execution-ready arbitrage opportunities.

A loophole is NOT "use question hooks" but an ARBITRAGE OPPORTUNITY:
- High TAM (large addressable audience)
- Low Meta Competition (few/no brands running this angle)
- Believable Mechanism (credible root cause + mechanism combo)

Each loophole is a COMPLETE AD STRATEGY combining all 6 dimensions.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import anthropic

from meta_ads_analyzer.compare.strategic_dimensions import (
    LoopholeOpportunity,
    StrategicLoopholeDocument,
    StrategicMarketMap,
)
from meta_ads_analyzer.models import BrandReport
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def generate_strategic_loophole_doc(
    market_map: StrategicMarketMap,
    brand_reports: list[BrandReport],
    focus_brand: Optional[str],
    config: dict[str, Any],
) -> StrategicLoopholeDocument:
    """Generate strategic loophole document with 5-7 execution-ready opportunities.

    Args:
        market_map: StrategicMarketMap with 6-dimension analysis
        brand_reports: List of brand reports
        focus_brand: Optional focus brand
        config: Config dict with API settings

    Returns:
        StrategicLoopholeDocument with validated loopholes
    """
    logger.info("Generating strategic loophole document with Claude analysis")

    # Build competitive landscape table
    competitive_landscape = _build_competitive_landscape(market_map)

    # Generate loopholes using Claude
    loopholes = await _generate_loopholes_with_claude(
        market_map, brand_reports, focus_brand, config
    )

    # Generate market narrative
    market_narrative = await _generate_market_narrative(
        market_map, brand_reports, config
    )

    # Generate what NOT to do
    what_not_to_do = _generate_what_not_to_do(market_map)

    # Build metadata
    meta = {
        "keyword": market_map.meta.get("keyword", ""),
        "focus_brand": focus_brand,
        "brands_compared": market_map.meta.get("brands_compared", 0),
        "generated_at": datetime.utcnow().isoformat(),
    }

    return StrategicLoopholeDocument(
        meta=meta,
        market_narrative=market_narrative,
        sophistication_assessment=market_map.sophistication_level,
        loopholes=loopholes,
        competitive_landscape=competitive_landscape,
        what_not_to_do=what_not_to_do,
    )


def _build_competitive_landscape(market_map: StrategicMarketMap) -> list[dict]:
    """Build competitive landscape table comparing brands across key dimensions."""
    landscape = []

    for summary in market_map.brand_summaries:
        landscape.append(
            {
                "brand": summary["brand"],
                "root_cause": summary["primary_root_cause"],
                "mechanism": summary["primary_mechanism"],
                "pain_point": summary["primary_pain_point"],
                "desire": summary["primary_desire"],
            }
        )

    return landscape


async def _generate_loopholes_with_claude(
    market_map: StrategicMarketMap,
    brand_reports: list[BrandReport],
    focus_brand: Optional[str],
    config: dict,
) -> list[LoopholeOpportunity]:
    """Use Claude to generate 5-7 validated loopholes as complete ad strategies."""

    prompt = _build_loophole_generation_prompt(market_map, brand_reports, focus_brand)

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514"),
        max_tokens=16384,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse response
    text = response.content[0].text.strip()
    data = _parse_loopholes_response(text)

    # Convert to LoopholeOpportunity models
    loopholes = []
    for i, loop_data in enumerate(data.get("loopholes", [])[:7], 1):
        loop_data["loophole_id"] = f"L{i}"
        loopholes.append(LoopholeOpportunity(**loop_data))

    return loopholes


def _build_loophole_generation_prompt(
    market_map: StrategicMarketMap,
    brand_reports: list[BrandReport],
    focus_brand: Optional[str],
) -> str:
    """Build prompt for Claude to generate execution-ready loopholes."""

    # Extract dimension comparisons
    root_causes = market_map.root_cause_comparison.model_dump()
    mechanisms = market_map.mechanism_comparison.model_dump()
    audiences = market_map.audience_comparison.model_dump()
    pain_points = market_map.pain_point_comparison.model_dump()
    symptoms = market_map.symptom_comparison.model_dump()
    desires = market_map.desire_comparison.model_dump()

    sophistication = market_map.sophistication_level.model_dump()

    prompt = f"""You are an expert direct response strategist analyzing competitive advertising for loophole opportunities.

## Market Context

**Keyword**: {market_map.meta['keyword']}
**Brands Compared**: {market_map.meta['brands_compared']}
**Focus Brand**: {focus_brand or 'None (market-wide analysis)'}
**Market Sophistication**: {sophistication['stage_name']}
**Strategic Response**: {sophistication['strategic_response']}

## 6-Dimension Market Analysis

### ROOT CAUSES
{json.dumps(root_causes, indent=2)}

### MECHANISMS
{json.dumps(mechanisms, indent=2)}

### TARGET AUDIENCES
{json.dumps(audiences, indent=2)}

### PAIN POINTS
{json.dumps(pain_points, indent=2)}

### SYMPTOMS
{json.dumps(symptoms, indent=2)}

### MASS DESIRES
{json.dumps(desires, indent=2)}

## ROOT CAUSE × MECHANISM MATRIX (CRITICAL - USE THIS!)

This matrix shows which root cause + mechanism combinations are actually used by brands:

{json.dumps(market_map.root_cause_mechanism_matrix, indent=2)}

**Matrix Key**:
- **SATURATED** (60%+ market share): Avoid - too crowded
- **MODERATE** (30-59% market share): Competitive but viable
- **Underexploited** (<30% market share): Good opportunity
- **WIDE OPEN** (0% market share): Best opportunity if believable

## Your Task: Generate 5-7 Validated Loopholes FROM THE MATRIX

**CRITICAL RULE**: Loopholes MUST be derived from actual competitive gaps in the matrix above. DO NOT invent new mechanisms that aren't based on what competitors are (or aren't) doing.

A loophole is NOT "use question hooks" but an ARBITRAGE OPPORTUNITY where:
- **High TAM** (large addressable audience)
- **Low Meta Competition** (few/no brands running this angle per matrix)
- **Believable Mechanism** (credible root cause + mechanism combo)

Each loophole must be a COMPLETE AD STRATEGY combining:
- Specific root cause to lead with (from or missing from matrix)
- Specific mechanism to position (from or missing from matrix)
- Specific avatar (demographics + psychographics)
- Pain point and symptoms to reference
- Mass desire/transformation promise
- Market sophistication response (new_mechanism / new_information / new_identity)
- 3-5 specific hook examples (NOT generic templates)
- Proof strategy
- Objection handling

## Loophole Identification Rules (USE MATRIX DATA ONLY!)

1. **PRIMARY: Analyze the Root Cause × Mechanism matrix**:
   - If matrix shows "none stated" is SATURATED: Opportunity is "be the first to clearly explain root cause + mechanism"
   - If matrix shows multiple combos at MODERATE: Find underexploited variations or go deeper on depth
   - If matrix shows specific combo at 0%: Assess if it's believable (not just theoretically possible)
   - DO NOT invent new mechanisms - identify what's MISSING from actual competitive landscape

2. **SECONDARY: Look for depth/specificity gaps**:
   - Root causes: Do brands explain at surface level when molecular/cellular depth is missing?
   - Mechanisms: Do brands claim "supports X" when specific pathways aren't explained?
   - Audiences: Are there identity/tribe variations within the same pain point?
   - Pain points: Are there intensity levels or contexts not covered?
   - Symptoms: Are there specific daily experiences not referenced?
   - Desires: Are there specific timeframes/measurable outcomes missing?

2. **Assess TAM size**:
   - Large: Broad pain point affecting 30%+ of target market
   - Medium: Specific pain point affecting 10-30%
   - Small: Niche pain point affecting <10%

3. **Assess Meta Competition**:
   - None: 0 brands running this angle
   - Low: 1-2 brands running lightly (not their primary angle)
   - Medium: 3+ brands or 1-2 running heavily

4. **Assess Believability** (0-1 score):
   - Root cause feels obvious? +0.3
   - Mechanism connects directly to root cause? +0.3
   - Proof strategy is strong? +0.2
   - Avoids unfalsifiable claims? +0.2

5. **Apply Market Sophistication Framework**:
   - If Stage 3-4: Prioritize new_mechanism and new_information loopholes
   - If Stage 5: Prioritize new_identity loopholes (tribal, anti-establishment, cultural)

6. **Score each loophole** (0-100):
   - TAM size: large=40pts, medium=25pts, small=10pts
   - Competition: none=40pts, low=25pts, medium=10pts
   - Believability: score * 20pts

7. **Effort & Timeline**:
   - Low effort: Can launch within 2 weeks (content only)
   - Medium effort: 4-8 weeks (requires new creative, maybe ingredient story)
   - High effort: 8+ weeks (requires R&D, clinical studies, or product reformulation)

8. **Risk Level**:
   - Low: Claims are provable, mainstream acceptance
   - Medium: Claims require education, moderate skepticism
   - High: Contrarian claims, high customer skepticism

## Output Format

Return valid JSON with this structure:

```json
{{
  "loopholes": [
    {{
      "title": "The Hormonal Trigger Nobody Explains (30-word max)",
      "the_gap": "3-5 paragraph explanation: What's missing from the market? Why is this a gap? What do ALL brands fail to explain? Be specific - reference the actual patterns from dimension analysis.",
      "tam_size": "large",
      "tam_rationale": "2-3 sentences: Why is the addressable audience large? What % of the target market has this pain point?",
      "meta_competition": "none",
      "meta_competition_evidence": "2-3 sentences: Proof that few/no brands run this angle. Reference dimension analysis data showing 0 or 1-2 brands.",
      "believability_score": 0.85,
      "root_cause": "Specific root cause to lead with (exact text, not generic)",
      "mechanism": "Specific mechanism to position (exact explanation, not generic)",
      "target_avatar": "Specific avatar: Women 45-65, health-conscious, frustrated with failed solutions, refuse to accept aging as inevitable",
      "pain_point": "Crepey skin on arms and neck causing daily embarrassment",
      "symptoms": ["Avoiding sleeveless shirts in summer", "Feeling self-conscious in photos", "Hiding arms with cardigans year-round"],
      "mass_desire": "Smooth, firm skin that looks 10 years younger in 8 weeks",
      "sophistication_response": "new_mechanism",
      "response_rationale": "At Stage 3-4, new mechanism explanation breaks through skepticism by showing HOW this works differently.",
      "hook_examples": [
        "The upstream hormonal trigger that CAUSES lymphatic congestion (and why no cream can fix it without this)",
        "Why your lymphatic system didn't just fail—here's the hidden hormone that shut it down first",
        "After 45, this hormone drops 60%. Here's what happens to your lymphatic drainage (and your skin)"
      ],
      "proof_strategy": "Clinical study showing hormone levels correlate with lymphatic function. Before/after skin elasticity measurements. Ingredient mechanism of action data.",
      "objection_handling": "Objection: 'Is this just another hormone cream?' → Answer: 'No. This targets the UPSTREAM trigger before hormones drop, preventing the cascade.' Objection: 'How long until I see results?' → Answer: 'Lymphatic drainage improves within 2 weeks. Visible skin improvement by week 4-6.'",
      "priority_score": 95,
      "effort_level": "medium",
      "timeline": "4-6 weeks (new creative + ingredient story, no R&D needed)",
      "risk_level": "low",
      "defensibility": "Once you establish the upstream hormonal trigger narrative, competitors look surface-level. Requires clinical research to match depth."
    }}
  ]
}}
```

## CRITICAL RULES

1. **USE THE MATRIX** - ALL loopholes must be derived from Root Cause × Mechanism matrix gaps. If matrix shows "none stated" is SATURATED, the loophole is "be first to explain clearly" NOT "try fascia/glymphatic/estrogen" unless those appear in competitor data
2. **Reference actual dimension data** - cite specific patterns, frequencies, gaps from the analysis with exact percentages from matrix
3. **NO inventing mechanisms** - if competitors don't mention fascia/glymphatic/estrogen/inflammation/circadian, don't create loopholes around them. Use what IS or ISN'T in the data
4. **NO generic advice** - every loophole must be execution-ready THIS WEEK based on real competitive gaps
5. **Specific hook language** - write actual hooks, not "use emotional triggers"
6. **Score rigorously** - TAM + Competition + Believability formula must match output
7. **Apply sophistication framework** - match loopholes to market stage
8. **Prioritize focus brand** - if focus brand specified, tailor loopholes to their gaps

Generate 5-7 loopholes, ranked by priority_score descending.

Return ONLY valid JSON, no markdown formatting."""

    return prompt


async def _generate_market_narrative(
    market_map: StrategicMarketMap, brand_reports: list[BrandReport], config: dict
) -> str:
    """Generate 3-5 paragraph market narrative using Claude."""

    prompt = f"""You are an expert direct response strategist writing a market overview.

## Market Context

**Keyword**: {market_map.meta['keyword']}
**Brands Compared**: {market_map.meta['brands_compared']}
**Market Sophistication**: {market_map.sophistication_level.stage_name}

## Dimension Analysis Summary

- **Root Causes**: {market_map.root_cause_comparison.how_patterns_differ}
- **Mechanisms**: {market_map.mechanism_comparison.how_patterns_differ}
- **Audiences**: {market_map.audience_comparison.how_patterns_differ}
- **Pain Points**: {market_map.pain_point_comparison.how_patterns_differ}
- **Symptoms**: {market_map.symptom_comparison.how_patterns_differ}
- **Desires**: {market_map.desire_comparison.how_patterns_differ}

## Your Task

Write a 3-5 paragraph market narrative that answers:

1. **What's the competitive landscape?** How deep do brands go in their root cause explanations? What's the universal mechanism positioning? What proof architecture vulnerabilities exist across all brands?

2. **What beliefs are installed vs missing?** What do customers believe after seeing these ads? What critical beliefs are NOT being installed?

3. **What's the sophistication level?** Is this Stage 3 (new mechanisms), Stage 4 (mechanism competition), or Stage 5 (identity-driven)? What evidence supports this?

4. **Where are the exploitable gaps?** Summarize the 2-3 biggest strategic opportunities for someone entering this market.

Write for someone who needs to EXPLOIT competitive weaknesses, not just understand them.

Return the narrative as plain text (no JSON, no markdown formatting)."""

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514"),
        max_tokens=2048,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()


def _generate_what_not_to_do(market_map: StrategicMarketMap) -> list[str]:
    """Generate what NOT to do based on market map analysis."""
    what_not_to_do = []

    # Root cause warnings
    if market_map.root_cause_comparison.pattern_1:
        pattern1 = market_map.root_cause_comparison.pattern_1
        if len(pattern1.get("brands_using", [])) >= 2:
            what_not_to_do.append(
                f"DON'T use the same root cause as {len(pattern1['brands_using'])} competitors: '{pattern1.get('text', '')[:60]}...'"
            )

    # Mechanism warnings
    if market_map.mechanism_comparison.pattern_1:
        pattern1 = market_map.mechanism_comparison.pattern_1
        if len(pattern1.get("brands_using", [])) >= 2:
            what_not_to_do.append(
                f"DON'T claim the same mechanism as {len(pattern1['brands_using'])} competitors: '{pattern1.get('text', '')[:60]}...'"
            )

    # Sophistication warnings
    soph = market_map.sophistication_level
    if soph.stage >= 4:
        what_not_to_do.append(
            f"DON'T use simple benefit claims - market is at {soph.stage_name}, customers need {soph.strategic_response.replace('_', ' ')}"
        )

    # Generic warning
    what_not_to_do.append(
        "DON'T copy competitor angles without differentiation - in sophisticated markets, being 10% better is invisible"
    )

    return what_not_to_do


def _parse_loopholes_response(text: str) -> dict:
    """Parse Claude's loopholes generation response."""
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
        logger.error(f"Failed to parse loopholes response as JSON: {e}")
        logger.debug(f"Response text: {text[:500]}...")

        # Return empty structure
        return {"loopholes": []}


def save_strategic_loophole_doc(
    doc: StrategicLoopholeDocument, output_dir: Path
) -> Path:
    """Save strategic loophole document to JSON file.

    Args:
        doc: StrategicLoopholeDocument to save
        output_dir: Output directory

    Returns:
        Path to saved file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "strategic_loophole_doc.json"
    with open(json_path, "w") as f:
        json.dump(doc.model_dump(mode="json"), f, indent=2, default=str)

    logger.info(f"Strategic loophole document saved: {json_path}")
    return json_path


def format_strategic_loophole_doc_text(doc: StrategicLoopholeDocument) -> str:
    """Format strategic loophole document for console display.

    Args:
        doc: StrategicLoopholeDocument to format

    Returns:
        Formatted text string
    """
    from rich.table import Table
    from rich.console import Console

    console = Console()
    lines = []

    lines.append(
        f"\n[bold cyan]═══ STRATEGIC LOOPHOLE DOCUMENT: {doc.meta['keyword']} ═══[/bold cyan]\n"
    )
    lines.append(f"Brands compared: {doc.meta['brands_compared']}")
    if doc.meta.get("focus_brand"):
        lines.append(f"Focus brand: [yellow]{doc.meta['focus_brand']}[/yellow]")
    lines.append(f"Generated: {doc.meta['generated_at']}\n")

    # Market narrative
    if doc.market_narrative:
        lines.append("[bold]Market Overview:[/bold]")
        lines.append(doc.market_narrative)
        lines.append("")

    # Sophistication
    soph = doc.sophistication_assessment
    lines.append(f"[bold yellow]Market Sophistication: {soph.stage_name}[/bold yellow]")
    lines.append(f"Strategic Response: [green]{soph.strategic_response}[/green]\n")

    # Loopholes table
    if doc.loopholes:
        lines.append(
            f"[bold green]✓ {len(doc.loopholes)} Validated Loopholes (Execution-Ready):[/bold green]"
        )
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("ID", width=4)
        table.add_column("Title", width=40)
        table.add_column("TAM", width=8)
        table.add_column("Competition", width=12)
        table.add_column("Score", justify="right", width=6)
        table.add_column("Effort", width=8)

        for loop in doc.loopholes:
            table.add_row(
                loop.loophole_id,
                loop.title[:38],
                loop.tam_size,
                loop.meta_competition,
                str(loop.priority_score),
                loop.effort_level,
            )

        console.print(table)
        lines.append("")

    # What NOT to do
    if doc.what_not_to_do:
        lines.append("[bold red]⚠ What NOT To Do:[/bold red]")
        for item in doc.what_not_to_do:
            lines.append(f"  • {item}")
        lines.append("")

    lines.append(
        f"[dim]✓ Compare complete: {len(doc.loopholes)} execution-ready loopholes generated[/dim]"
    )

    return "\n".join(lines)
