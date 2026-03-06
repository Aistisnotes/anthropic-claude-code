"""Blue ocean report generator.

Used when no brands have 50+ qualifying ads in the market.
Generates a gold-standard loophole analysis using deep ad analysis
from adjacent category competitors.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from meta_ads_analyzer.compare.strategic_dimensions import (
    BlueOceanAdConcept,
    BlueOceanResult,
    BlueOceanWeekPlan,
)
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

# ── Prompts ────────────────────────────────────────────────────────────────────

_GOLD_STANDARD_PROMPT = """You are a world-class direct response strategist. You have deep ad analysis data from brands in markets adjacent to "{keyword}".

=== TARGET MARKET ===
Product: {keyword}
Blue Ocean Status: No brand has 30+ qualifying ads running Meta ads for this product
Max competing ads found by any brand: {max_qualifying_ads}

{adjacent_section}

{focus_section}

=== TASK ===
Generate a complete gold-standard loophole analysis for someone entering the "{keyword}" market.
Use the adjacent brand data above as the competitive landscape — these adjacent categories reveal what the market does and doesn't do, which surfaces the loopholes.

Return ONLY valid JSON with this EXACT structure (no markdown, no commentary):
{{
  "competitive_landscape": [
    {{
      "brand": "Exact brand name from data above",
      "category": "The adjacent category this brand is in",
      "root_cause": "What they actually claim causes the problem (quote or paraphrase their real claim)",
      "root_cause_depth": "surface|moderate|deep",
      "root_cause_gap": "What is missing from their explanation (e.g. 'No WHY explanation', 'No science backing')",
      "mechanism": "How they claim to fix it",
      "mechanism_depth": "claim-only|process-level|cellular",
      "mechanism_gap": "What cellular/molecular depth they are missing",
      "ingredient_story": "Ingredient story they tell OR 'NONE'",
      "ingredient_score": "0-10 (string)",
      "authority": "What credibility/authority they use OR 'None'"
    }}
  ],
  "what_nobody_does_well": [
    "Upstream root cause — WHY [the core biological problem] actually happens",
    "Cellular mechanism — HOW [the product type] works at molecular level",
    "Ingredient stories — origin, sourcing, why this specific form/concentration",
    "Clinical depth — specific study methodology, not just percentages"
  ],
  "upstream_root_cause_gap": {{
    "what_nobody_explains": "The upstream biological trigger nobody connects to the visible problem",
    "the_chain": [
      "Root biological cause (upstream)",
      "→ Intermediate step",
      "→ Intermediate step",
      "→ Visible symptom (what everyone treats)"
    ],
    "opportunity": "How to use this as an 'aha moment' hook for the target customer"
  }},
  "cellular_mechanism_gap": {{
    "what_nobody_explains": "HOW the product category actually works at the cellular/molecular level",
    "specific_questions": [
      "Scientific question nobody answers in ads",
      "Another specific mechanism question",
      "Why does X ratio/concentration matter specifically?"
    ],
    "example_depth": "Example of what real cellular-level copy would sound like in an ad"
  }},
  "ingredient_gap": {{
    "what_nobody_explains": "What ingredient transparency is missing across all adjacent brands",
    "opportunities": [
      {{"label": "Origin Stories", "example": "Specific believable origin story for this product type"}},
      {{"label": "Extraction/Process", "example": "Specific process story relevant to this product"}},
      {{"label": "Why This Form", "example": "Why this specific form/concentration matters vs alternatives"}},
      {{"label": "Founder/Discovery", "example": "Type of discovery story that would resonate"}}
    ],
    "specific_vulnerability": "Name the biggest specific ingredient transparency gap using a real brand name from the data"
  }},
  "loopholes": [
    {{
      "rank": 1,
      "title": "LOOPHOLE 1: [Specific Descriptive Name]",
      "score": 48,
      "loophole_type": "ROOT CAUSE",
      "risk_level": "LOW RISK",
      "effort": "Low",
      "timeline": "2-4 weeks",
      "the_gap": "Detailed specific explanation of the gap — what every adjacent brand misses and why it matters",
      "why_its_massive": [
        "Creates instant 'aha moment' — specific example for this product",
        "Positions competitors as treating symptoms not cause",
        "Validates the customer experience (it's not their fault, it's biology)",
        "No product changes needed — just educational positioning"
      ],
      "execution": [
        "Specific hook example: '...'",
        "How to frame the educational sequence",
        "Counter-positioning statement vs competitors"
      ]
    }}
  ],
  "execution_roadmap": {{
    "immediate_actions": [
      "Specific action 1 (most important)",
      "Specific action 2",
      "Specific action 3"
    ],
    "what_not_to_do": [
      "Generic mistake 1 — specific reason it won't work for this product",
      "Generic mistake 2 — specific reason",
      "Generic mistake 3 — specific reason"
    ]
  }},
  "blue_ocean_summary": "2-3 paragraphs explaining the blue ocean opportunity, competitive gap, and first-mover advantage specific to {keyword}",
  "adjacent_insights": "1-2 paragraphs on what adjacent categories teach us about what works and what's missing",
  "ad_concepts": [
    {{
      "title": "Short concept name",
      "hook": "Opening line/hook (specific and concrete, not a template)",
      "angle": "Core angle/mechanism being used",
      "root_cause": "Root cause this concept leads with",
      "mechanism": "Mechanism being positioned",
      "why_it_works": "Why this concept works for a blue ocean market entry"
    }}
  ],
  "testing_roadmap": [
    {{
      "week": "Week 1",
      "focus": "What to focus on",
      "actions": ["Specific action 1", "Specific action 2", "Specific action 3"]
    }},
    {{
      "week": "Weeks 2-3",
      "focus": "What to focus on",
      "actions": ["Specific action 1", "Specific action 2"]
    }},
    {{
      "week": "Week 4",
      "focus": "What to focus on",
      "actions": ["Specific action 1", "Specific action 2"]
    }}
  ],
  "focus_brand_strengths": [],
  "focus_brand_gaps": []
}}

RULES:
- "loopholes" must have 4-6 entries ordered by score highest first
- "ad_concepts" must have EXACTLY 5 entries
- "competitive_landscape" must have one row per brand from the adjacent analysis data (use exact brand names)
- Be SPECIFIC to "{keyword}" — use the actual biological/chemical mechanisms relevant to this product
- "what_nobody_does_well" should be 4-6 specific gaps, NOT generic advice
- upstream_root_cause_gap.the_chain must have 4-5 steps showing the actual biological cascade
- ingredient_gap.specific_vulnerability MUST name a real brand from the data and their specific claim
- All loophole scores use 0-50 scale
- loophole_type options: ROOT CAUSE, MECHANISM, INGREDIENT, AUTHORITY, PROOF, AVATAR
- risk_level options: LOW RISK, MEDIUM RISK, HIGH RISK
- focus_brand_strengths and focus_brand_gaps: only populate if focus brand data is provided; otherwise keep as []
"""

_FALLBACK_PROMPT = """You are a world-class direct response strategist analyzing a blue ocean market opportunity.

MARKET: {keyword}

FINDING:
- Scanned {brands_scanned} brands on Meta Ads Library for "{keyword}"
- No brand is running 30+ qualifying ads in this market
- Maximum qualifying ads found by any single brand: {max_qualifying_ads}
- Brands found (ad counts):
{brand_counts_list}

{focus_section}

Generate a complete blue ocean execution strategy. Return ONLY valid JSON:
{{
  "competitive_landscape": [],
  "what_nobody_does_well": [
    "Upstream root cause — WHY the core problem actually happens biologically",
    "Cellular mechanism — HOW the product type works at molecular level",
    "Ingredient stories — origin, sourcing, why this specific form",
    "Clinical depth — specific study methodology, not just percentages"
  ],
  "upstream_root_cause_gap": {{
    "what_nobody_explains": "The upstream biological trigger",
    "the_chain": ["Root cause", "→ Intermediate", "→ Visible symptom"],
    "opportunity": "How to position this insight"
  }},
  "cellular_mechanism_gap": {{
    "what_nobody_explains": "How the product type works at cellular level",
    "specific_questions": ["Question 1", "Question 2"],
    "example_depth": "Example of real cellular-level copy"
  }},
  "ingredient_gap": {{
    "what_nobody_explains": "Missing ingredient transparency",
    "opportunities": [
      {{"label": "Origin Stories", "example": "Specific example"}},
      {{"label": "Why This Form", "example": "Specific example"}}
    ],
    "specific_vulnerability": "General gap — no specific competitor data available"
  }},
  "loopholes": [
    {{
      "rank": 1,
      "title": "LOOPHOLE 1: Upstream Root Cause Nobody Explains",
      "score": 45,
      "loophole_type": "ROOT CAUSE",
      "risk_level": "LOW RISK",
      "effort": "Low",
      "timeline": "2-4 weeks",
      "the_gap": "No brand explains WHY the problem happens at a biological level",
      "why_its_massive": ["Creates aha moment", "Validates customer experience"],
      "execution": ["Lead with upstream cause hook", "Educational sequence"]
    }}
  ],
  "execution_roadmap": {{
    "immediate_actions": ["Own the category keyword on Meta", "Test root cause depth levels", "Identify best ad format"],
    "what_not_to_do": ["Generic product claims", "Celebrity endorsement without mechanism"]
  }},
  "blue_ocean_summary": "Blue ocean opportunity detected in '{keyword}'. No brand is running significant ads in this market.",
  "adjacent_insights": "Adjacent markets can teach us what messaging frameworks work in similar categories.",
  "ad_concepts": [
    {{"title": "Root Cause Hook", "hook": "Here's WHY your [problem] keeps happening...", "angle": "Upstream cause education", "root_cause": "Biological root cause", "mechanism": "How product addresses it", "why_it_works": "No competition, first-mover educational positioning"}},
    {{"title": "Mechanism Depth", "hook": "Most [products] fail because they don't understand...", "angle": "Mechanism superiority", "root_cause": "Surface vs deep cause", "mechanism": "Cellular-level explanation", "why_it_works": "Establishes scientific authority"}},
    {{"title": "Avatar Story", "hook": "If you've tried everything and nothing works...", "angle": "Identity/validation", "root_cause": "Why previous solutions failed", "mechanism": "Why this is different", "why_it_works": "Validates frustration, builds trust"}},
    {{"title": "Ingredient Transparency", "hook": "We'll show you exactly what's in this and why", "angle": "Full transparency", "root_cause": "Mystery ingredients fail trust", "mechanism": "Proven ingredients with sourcing", "why_it_works": "Builds trust in skeptical audience"}},
    {{"title": "Category Creation", "hook": "This isn't a [generic category]. This is...", "angle": "New category framing", "root_cause": "Old solutions incomplete", "mechanism": "New mechanism/approach", "why_it_works": "Owns the narrative, avoids comparison"}}
  ],
  "testing_roadmap": [
    {{"week": "Week 1", "focus": "Launch 3 root cause hook variants", "actions": ["Create upstream cause educational ad", "Test mechanism depth variation", "Launch avatar validation ad"]}},
    {{"week": "Weeks 2-3", "focus": "Scale winner, test ingredient angle", "actions": ["Scale best performer 2x budget", "Launch ingredient transparency variant"]}},
    {{"week": "Week 4", "focus": "Category ownership", "actions": ["Develop category creation angle", "Build retargeting sequence for viewers"]}}
  ],
  "focus_brand_strengths": [],
  "focus_brand_gaps": []
}}
"""

_FOCUS_SECTION = """FOCUS BRAND ANALYSIS — {focus_brand}:
Total ads analyzed: {ads_analyzed}

Root causes used in ads:
{root_causes}

Mechanisms used in ads:
{mechanisms}

Target avatar/audience:
{avatar}

Top pain points:
{pain_points}

Executive summary from ad patterns:
{summary}
"""


# ── Main function ─────────────────────────────────────────────────────────────


async def generate_blue_ocean_doc(
    keyword: str,
    focus_brand: Optional[str],
    brand_ad_counts: dict[str, int],
    focus_brand_pattern_report: Any,  # PatternReport | None
    config: dict,
    adjacent_brand_reports: Optional[list] = None,  # list[BrandReport]
) -> BlueOceanResult:
    """Generate a gold-standard blue ocean analysis report.

    Args:
        keyword: Market keyword
        focus_brand: Optional focus brand name
        brand_ad_counts: Dict of brand_name → qualifying ad count
        focus_brand_pattern_report: PatternReport from Pipeline.run() or None
        config: Full config dict
        adjacent_brand_reports: BrandReport list from cross-category deep analysis

    Returns:
        BlueOceanResult
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
    model = config.get("claude", {}).get("model", "claude-sonnet-4-20250514")

    brands_scanned = len(brand_ad_counts)
    max_qualifying_ads = max(brand_ad_counts.values()) if brand_ad_counts else 0
    sorted_counts = sorted(brand_ad_counts.items(), key=lambda x: x[1], reverse=True)

    # Build focus section
    focus_section = ""
    focus_brand_data: dict = {}
    if focus_brand and focus_brand_pattern_report:
        pr = focus_brand_pattern_report
        root_causes = _extract_patterns(pr.root_cause_patterns, "root_cause", 5)
        mechanisms = _extract_patterns(pr.mechanism_patterns, "mechanism", 5)
        avatar_patterns = _extract_patterns(pr.target_customer_patterns, "profile", 3)
        pain_points = _extract_patterns(pr.common_pain_points, "pain_point", 5)
        focus_section = _FOCUS_SECTION.format(
            focus_brand=focus_brand,
            ads_analyzed=pr.total_ads_analyzed,
            root_causes=root_causes,
            mechanisms=mechanisms,
            avatar=avatar_patterns,
            pain_points=pain_points,
            summary=pr.executive_summary[:800] if pr.executive_summary else "N/A",
        )
        focus_brand_data = {
            "ads_analyzed": pr.total_ads_analyzed,
            "root_causes": [p.get("root_cause", p.get("pattern", "")) for p in pr.root_cause_patterns[:5]],
            "mechanisms": [p.get("mechanism", p.get("pattern", "")) for p in pr.mechanism_patterns[:5]],
            "avatar": avatar_patterns,
            "pain_points": [p.get("pain_point", p.get("pattern", "")) for p in pr.common_pain_points[:5]],
        }

    # Use gold standard prompt if we have adjacent brand analyses
    has_adjacent_data = bool(adjacent_brand_reports)
    if has_adjacent_data:
        adjacent_section = _format_adjacent_brands_for_prompt(adjacent_brand_reports)
        prompt = _GOLD_STANDARD_PROMPT.format(
            keyword=keyword,
            max_qualifying_ads=max_qualifying_ads,
            adjacent_section=adjacent_section,
            focus_section=focus_section,
        )
    else:
        brand_counts_list = "\n".join(
            f"  - {brand}: {count} qualifying ads" for brand, count in sorted_counts[:10]
        )
        prompt = _FALLBACK_PROMPT.format(
            keyword=keyword,
            brands_scanned=brands_scanned,
            max_qualifying_ads=max_qualifying_ads,
            brand_counts_list=brand_counts_list,
            focus_section=focus_section,
        )

    # Call Claude
    logger.info(f"Generating blue ocean strategy for '{keyword}' with Claude...")
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
        claude_data = json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Claude blue ocean generation failed: {e}")
        claude_data = _fallback_claude_data(keyword)

    # Scan adjacent keywords for blue ocean confirmation table
    adjacent_keywords = await _scan_adjacent_keywords(keyword, config)

    # Build ad concepts
    ad_concepts = [
        BlueOceanAdConcept(
            title=c.get("title", ""),
            hook=c.get("hook", ""),
            angle=c.get("angle", ""),
            root_cause=c.get("root_cause", ""),
            mechanism=c.get("mechanism", ""),
            why_it_works=c.get("why_it_works", ""),
        )
        for c in claude_data.get("ad_concepts", [])[:5]
    ]

    # Build roadmap
    roadmap = [
        BlueOceanWeekPlan(
            week=w.get("week", ""),
            focus=w.get("focus", ""),
            actions=w.get("actions", []),
        )
        for w in claude_data.get("testing_roadmap", [])
    ]

    return BlueOceanResult(
        keyword=keyword,
        focus_brand=focus_brand,
        generated_at=datetime.utcnow().isoformat(),
        brands_scanned=brands_scanned,
        max_qualifying_ads=max_qualifying_ads,
        brand_ad_counts=[{"brand": b, "qualifying_ads": c} for b, c in sorted_counts],
        blue_ocean_summary=claude_data.get("blue_ocean_summary", ""),
        focus_brand_ads_analyzed=focus_brand_data.get("ads_analyzed", 0),
        focus_brand_root_causes=focus_brand_data.get("root_causes", []),
        focus_brand_mechanisms=focus_brand_data.get("mechanisms", []),
        focus_brand_avatar=focus_brand_data.get("avatar", ""),
        focus_brand_top_pain_points=focus_brand_data.get("pain_points", []),
        focus_brand_strengths=claude_data.get("focus_brand_strengths", []),
        focus_brand_gaps=claude_data.get("focus_brand_gaps", []),
        execution_recommendations=claude_data.get("execution_recommendations", []),
        first_5_ad_concepts=ad_concepts,
        testing_roadmap=roadmap,
        adjacent_keywords=adjacent_keywords,
        adjacent_insights=claude_data.get("adjacent_insights", ""),
        # Gold standard sections
        competitive_landscape=claude_data.get("competitive_landscape", []),
        what_nobody_does_well=claude_data.get("what_nobody_does_well", []),
        upstream_root_cause_gap=claude_data.get("upstream_root_cause_gap", {}),
        cellular_mechanism_gap=claude_data.get("cellular_mechanism_gap", {}),
        ingredient_gap=claude_data.get("ingredient_gap", {}),
        market_loopholes=claude_data.get("loopholes", []),
        execution_roadmap=claude_data.get("execution_roadmap", {}),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_adjacent_brands_for_prompt(brand_reports: list) -> str:
    """Format adjacent brand reports into a clear prompt section."""
    if not brand_reports:
        return ""

    lines = ["=== ADJACENT CATEGORY AD ANALYSES ===",
             "(Real ad analysis from brands in related markets. Use these as your competitive landscape.)\n"]

    for report in brand_reports:
        pr = report.pattern_report
        brand_name = report.advertiser.page_name
        category = report.cross_category_product_type or "adjacent category"
        ads_count = pr.total_ads_analyzed

        lines.append(f"{'─'*60}")
        lines.append(f"Brand: {brand_name} | Category: {category} | Ads Analyzed: {ads_count}")
        lines.append(f"{'─'*60}")

        # Root causes
        if pr.root_cause_patterns:
            lines.append("ROOT CAUSES USED:")
            for rc in pr.root_cause_patterns[:4]:
                rc_text = rc.get("root_cause", rc.get("pattern", ""))
                depth = rc.get("depth_level", rc.get("depth", ""))
                gap = rc.get("upstream_gap", "")
                sci = rc.get("scientific_explanation", "")
                freq = rc.get("frequency", 0)
                line = f"  - {rc_text[:120]} (freq:{freq}, depth:{depth})"
                if gap:
                    line += f", gap: {gap[:80]}"
                if sci:
                    line += f", science: {sci[:80]}"
                lines.append(line)

        # Mechanisms
        if pr.mechanism_patterns:
            lines.append("MECHANISMS POSITIONED:")
            for mech in pr.mechanism_patterns[:4]:
                m_text = mech.get("mechanism", mech.get("pattern", ""))
                depth = mech.get("depth", "")
                sci = mech.get("scientific_explanation", "")
                ings = mech.get("ingredients_involved", [])
                freq = mech.get("frequency", 0)
                line = f"  - {m_text[:120]} (freq:{freq}, depth:{depth})"
                if sci:
                    line += f", science: {sci[:80]}"
                if ings:
                    line += f", ingredients: {', '.join(str(i) for i in ings[:3])}"
                lines.append(line)

        # Pain points
        if pr.common_pain_points:
            lines.append("PAIN POINTS:")
            for pp in pr.common_pain_points[:4]:
                pp_text = pp.get("pain_point", pp.get("pattern", ""))
                syms = pp.get("symptoms", [])
                freq = pp.get("frequency", 0)
                line = f"  - {pp_text[:100]} (freq:{freq})"
                if syms:
                    line += f", symptoms: {', '.join(str(s) for s in syms[:3])}"
                lines.append(line)

        # Avatars
        if pr.avatars:
            lines.append("TARGET AVATAR:")
            av = pr.avatars[0]
            demo = av.get("demographics", "")
            psycho = av.get("psychographics", "")
            if demo:
                lines.append(f"  - Demographics: {demo[:120]}")
            if psycho:
                lines.append(f"  - Psychographics: {psycho[:120]}")

        # Ingredient transparency
        if pr.ingredient_transparency_analysis:
            it = pr.ingredient_transparency_analysis
            score = it.get("avg_score", it.get("score", "N/A"))
            summary = it.get("summary", it.get("analysis", ""))
            lines.append(f"INGREDIENT TRANSPARENCY: Score {score}/10")
            if summary:
                lines.append(f"  - {str(summary)[:200]}")

        # Ad formats
        if pr.creative_format_distribution:
            fmt_str = ", ".join(f"{k}:{v}" for k, v in list(pr.creative_format_distribution.items())[:5])
            lines.append(f"AD FORMATS: {fmt_str}")

        # What nobody does well
        if pr.what_nobody_does_well:
            lines.append("WHAT NOBODY DOES WELL (gaps identified in this brand's analysis):")
            for gap in pr.what_nobody_does_well[:4]:
                lines.append(f"  - {str(gap)[:150]}")

        # Executive summary
        if pr.executive_summary:
            lines.append(f"EXECUTIVE SUMMARY: {pr.executive_summary[:400]}")

        lines.append("")

    return "\n".join(lines)


def _extract_patterns(patterns: list, key: str, limit: int) -> str:
    """Extract pattern text from a list of pattern dicts."""
    results = []
    for p in patterns[:limit]:
        text = p.get(key) or p.get("pattern") or p.get("text") or ""
        if text:
            results.append(f"  - {str(text)[:120]}")
    return "\n".join(results) if results else "  - (none detected)"


def _fallback_claude_data(keyword: str) -> dict:
    return {
        "competitive_landscape": [],
        "what_nobody_does_well": [
            "Upstream root cause — WHY the core biological problem actually happens",
            "Cellular mechanism — HOW the product works at molecular level",
            "Ingredient stories — origin, sourcing, why this specific form",
            "Clinical depth — specific study methodology, not just percentages",
        ],
        "upstream_root_cause_gap": {
            "what_nobody_explains": f"The upstream biological trigger behind the problem {keyword} addresses",
            "the_chain": ["Root biological cause", "→ Intermediate cascade", "→ Visible symptom"],
            "opportunity": "Explain the upstream WHY to create the 'aha moment' for customers",
        },
        "cellular_mechanism_gap": {
            "what_nobody_explains": f"HOW {keyword} products actually work at the cellular level",
            "specific_questions": ["What happens at the cellular level?", "Which specific pathways are activated?"],
            "example_depth": "Example: 'When [ingredient] reaches [cell type], it activates [pathway]...'",
        },
        "ingredient_gap": {
            "what_nobody_explains": "Origin, sourcing, and why specific ingredient forms matter",
            "opportunities": [
                {"label": "Origin Stories", "example": f"Where the key ingredients in {keyword} products come from"},
                {"label": "Why This Form", "example": "Why this specific form/concentration outperforms alternatives"},
            ],
            "specific_vulnerability": "No specific competitor data available — first to market",
        },
        "loopholes": [
            {
                "rank": 1,
                "title": "LOOPHOLE 1: Upstream Root Cause Nobody Explains",
                "score": 45,
                "loophole_type": "ROOT CAUSE",
                "risk_level": "LOW RISK",
                "effort": "Low",
                "timeline": "2-4 weeks",
                "the_gap": f"No brand explains WHY the core problem {keyword} addresses actually happens at a biological level.",
                "why_its_massive": [
                    "Creates instant 'aha moment' for the customer",
                    "Positions any future competitors as treating symptoms",
                    "Validates customer experience — it's not their fault, it's biology",
                    "No product changes needed — just educational positioning",
                ],
                "execution": [
                    f"Lead with: 'Here's WHY [the problem] actually happens...'",
                    "Explain the biological cascade in simple terms",
                    "Counter-position: 'They treat what you see. We explain WHY it happens.'",
                ],
            }
        ],
        "execution_roadmap": {
            "immediate_actions": [
                "Own the category keyword on Meta before competition arrives",
                "Test root cause depth levels (surface → cellular → molecular)",
                "Identify and scale the highest-performing ad format",
            ],
            "what_not_to_do": [
                "Generic product claims — no differentiation in a blue ocean",
                "Celebrity endorsement without mechanism depth — easily copied",
                "Before/after without explanation — won't build category authority",
            ],
        },
        "blue_ocean_summary": f"Blue ocean opportunity detected in '{keyword}'. No brand is running significant ads in this market.",
        "adjacent_insights": "Adjacent markets reveal what messaging frameworks resonate in similar categories.",
        "ad_concepts": [],
        "testing_roadmap": [],
        "focus_brand_strengths": [],
        "focus_brand_gaps": [],
    }


async def _scan_adjacent_keywords(keyword: str, config: dict) -> list[dict]:
    """Scan 3-4 adjacent keywords to confirm neighboring markets are also blue ocean."""
    try:
        from meta_ads_analyzer.classifier.keyword_expander import generate_related_keywords
        from meta_ads_analyzer.models import ProductType
        from meta_ads_analyzer.scanner import run_scan
        from meta_ads_analyzer.classifier.product_type import (
            get_dominant_product_type,
            filter_ads_by_product_type,
        )
        from meta_ads_analyzer.selector import aggregate_by_advertiser

        related = await generate_related_keywords(keyword, ProductType.UNKNOWN, config, count=4)
        if not related:
            return []

        results = []
        for kw in related[:4]:
            try:
                scan = await run_scan(kw, config)
                dominant_type, _ = get_dominant_product_type(scan.ads)
                if dominant_type != ProductType.UNKNOWN:
                    filtered = filter_ads_by_product_type(scan.ads, dominant_type, allow_unknown=True)
                else:
                    filtered = scan.ads

                advertisers = aggregate_by_advertiser(filtered)
                brands_with_50_plus = sum(1 for adv in advertisers if adv.ad_count >= 50)
                max_ads = max((adv.ad_count for adv in advertisers), default=0)

                results.append({
                    "keyword": kw,
                    "total_brands": len(advertisers),
                    "brands_with_50_plus": brands_with_50_plus,
                    "max_ads": max_ads,
                    "has_competition": brands_with_50_plus >= 3,
                })
            except Exception as e:
                logger.warning(f"Adjacent scan failed for '{kw}': {e}")

        return results
    except Exception as e:
        logger.warning(f"Adjacent keyword scanning failed: {e}")
        return []


def save_blue_ocean_doc(result: BlueOceanResult, output_dir) -> None:
    """Save blue ocean result to JSON file."""
    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "blue_ocean_report.json"
    with open(path, "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)
    logger.info(f"Blue ocean report saved: {path}")
