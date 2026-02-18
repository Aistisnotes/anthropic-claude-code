"""Blue ocean report generator.

Used when no brands have 50+ qualifying ads in the market.
Generates:
  1. Finding statement (data-driven)
  2. Focus brand deep dive (from PatternReport, if provided)
  3. Execution strategy (Claude-generated: exec recs, 5 ad concepts, testing roadmap)
  4. Adjacent keyword scan (find neighbouring markets with competition)
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

# ── Prompt ────────────────────────────────────────────────────────────────────

_BLUE_OCEAN_PROMPT = """You are a world-class direct response strategist analyzing a blue ocean market opportunity.

MARKET: {keyword}

FINDING:
- Scanned {brands_scanned} brands on Meta Ads Library for "{keyword}"
- No brand is running 50+ qualifying ads in this market
- Maximum qualifying ads found by any single brand: {max_qualifying_ads}
- Brands found (ad counts):
{brand_counts_list}

{focus_section}

Your job: Generate a complete blue ocean execution strategy.

Return ONLY valid JSON with exactly this structure (no markdown, no commentary):
{{
  "blue_ocean_summary": "2-3 paragraphs explaining the blue ocean opportunity, what it means competitively, and the first-mover advantage available",
  "execution_recommendations": [
    "Specific recommendation 1",
    "Specific recommendation 2",
    "Specific recommendation 3",
    "Specific recommendation 4",
    "Specific recommendation 5",
    "Specific recommendation 6"
  ],
  "ad_concepts": [
    {{
      "title": "Short concept name",
      "hook": "Opening line/hook (specific, not generic)",
      "angle": "The core angle/mechanism being used",
      "root_cause": "Root cause this concept leads with",
      "mechanism": "Mechanism being positioned",
      "why_it_works": "Why this concept works for a blue ocean market"
    }}
  ],
  "testing_roadmap": [
    {{
      "week": "Week 1",
      "focus": "What to focus on this week",
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
  "focus_brand_strengths": ["Strength 1", "Strength 2", "Strength 3"],
  "focus_brand_gaps": ["Gap 1", "Gap 2", "Gap 3"],
  "adjacent_insights": "1-2 paragraphs on what adjacent markets can teach us even though this specific market is blue ocean"
}}

RULES:
- "ad_concepts" must have EXACTLY 5 entries
- "execution_recommendations" must have 5-7 entries
- "testing_roadmap" must have 3-4 week entries
- All content must be specific to "{keyword}" — no generic advice
- focus_brand_strengths and focus_brand_gaps: only populate if focus brand analysis is provided below; otherwise use empty lists []
- Make hooks specific and concrete, not templates like "Are you tired of X?"
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
) -> BlueOceanResult:
    """Generate a blue ocean analysis report.

    Args:
        keyword: Market keyword (e.g. "ESOPHAGUS")
        focus_brand: Optional focus brand name
        brand_ad_counts: Dict of brand_name → qualifying ad count
        focus_brand_pattern_report: PatternReport from Pipeline.run() or None
        config: Full config dict

    Returns:
        BlueOceanResult
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
    model = config.get("claude", {}).get("model", "claude-sonnet-4-20250514")

    brands_scanned = len(brand_ad_counts)
    max_qualifying_ads = max(brand_ad_counts.values()) if brand_ad_counts else 0

    # Build brand counts list
    sorted_counts = sorted(brand_ad_counts.items(), key=lambda x: x[1], reverse=True)
    brand_counts_list = "\n".join(
        f"  - {brand}: {count} qualifying ads" for brand, count in sorted_counts[:10]
    )

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

    # Build prompt
    prompt = _BLUE_OCEAN_PROMPT.format(
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
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]

        claude_data = json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Claude blue ocean generation failed: {e}")
        claude_data = {
            "blue_ocean_summary": f"Blue ocean opportunity detected in '{keyword}'. No brand is running significant ads in this market.",
            "execution_recommendations": [
                "Own the category keyword on Meta before competition arrives",
                "Test root cause depth levels (surface → cellular → molecular)",
                "Identify and scale the highest-performing ad format",
            ],
            "ad_concepts": [],
            "testing_roadmap": [],
            "focus_brand_strengths": [],
            "focus_brand_gaps": [],
            "adjacent_insights": "",
        }

    # Scan adjacent keywords
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
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_patterns(patterns: list, key: str, limit: int) -> str:
    """Extract pattern text from a list of pattern dicts."""
    results = []
    for p in patterns[:limit]:
        text = p.get(key) or p.get("pattern") or p.get("text") or ""
        if text:
            results.append(f"  - {str(text)[:120]}")
    return "\n".join(results) if results else "  - (none detected)"


async def _scan_adjacent_keywords(keyword: str, config: dict) -> list[dict]:
    """Scan 3-4 adjacent keywords to find neighboring markets with competition."""
    try:
        from meta_ads_analyzer.classifier.keyword_expander import generate_related_keywords
        from meta_ads_analyzer.models import ProductType
        from meta_ads_analyzer.scanner import run_scan
        from meta_ads_analyzer.classifier.product_type import (
            get_dominant_product_type,
            filter_ads_by_product_type,
        )
        from meta_ads_analyzer.selector import aggregate_by_advertiser

        # Generate related keywords
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
    import json
    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "blue_ocean_report.json"
    with open(path, "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)
    logger.info(f"Blue ocean report saved: {path}")
