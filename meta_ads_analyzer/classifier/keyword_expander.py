"""Keyword expansion for sparse market results."""

from __future__ import annotations

import json
from typing import Optional

import anthropic

from meta_ads_analyzer.models import ProductType
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def generate_related_keywords(
    primary_keyword: str,
    product_type: Optional[ProductType],
    config: dict,
    count: int = 4,
) -> list[str]:
    """Generate related keywords using Claude.

    Args:
        primary_keyword: Original keyword that returned sparse results
        product_type: Detected product type (if available)
        config: Config dict with API settings
        count: Number of related keywords to generate (default 4)

    Returns:
        List of related keyword strings
    """
    logger.info(
        f"Generating {count} related keywords for: {primary_keyword} "
        f"(product_type: {product_type.value if product_type else 'unknown'})"
    )

    product_context = ""
    if product_type and product_type != ProductType.UNKNOWN:
        product_context = f"\nProduct Type: {product_type.value}\nGenerate related keywords for the SAME product type."

    prompt = f"""Generate {count} related search keywords for: "{primary_keyword}"

{product_context}

Return search keywords that would find similar ads for the same market/problem.
Use synonyms, related problems, alternative phrasings, and adjacent solutions.

Examples:
- "weight loss supplement" → ["fat burner", "metabolism booster", "appetite suppressant", "weight management"]
- "lymphatic drainage massage" → ["lymphatic massage tool", "lymph drainage device", "lymphatic detox", "manual lymphatic drainage"]
- "anti aging serum" → ["wrinkle cream", "retinol serum", "youth serum", "age defying cream"]

Return ONLY a JSON array of {count} related keywords, no other text:
["keyword1", "keyword2", "keyword3", "keyword4"]"""

    try:
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514"),
            max_tokens=512,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()

        # Extract JSON array
        if "[" in text and "]" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            json_text = text[start:end]
            keywords = json.loads(json_text)

            # Validate and clean
            keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
            keywords = keywords[:count]  # Limit to requested count

            logger.info(f"Generated {len(keywords)} related keywords: {keywords}")
            return keywords
        else:
            logger.warning("Could not parse keyword expansion response, returning empty list")
            return []

    except Exception as e:
        logger.error(f"Failed to generate related keywords: {e}")
        return []


def deduplicate_ads_across_keywords(
    all_ads_by_keyword: dict[str, list],
) -> tuple[list, dict[str, int]]:
    """Deduplicate ads across multiple keyword scans.

    Args:
        all_ads_by_keyword: Dict mapping keyword to list of ScrapedAd objects

    Returns:
        Tuple of (deduplicated_ads, keyword_contribution_counts)
    """
    seen_ids = set()
    deduplicated = []
    contribution_counts = {kw: 0 for kw in all_ads_by_keyword.keys()}

    # Process in order of keywords (primary first)
    for keyword, ads in all_ads_by_keyword.items():
        for ad in ads:
            if ad.ad_id not in seen_ids:
                seen_ids.add(ad.ad_id)
                deduplicated.append(ad)
                contribution_counts[keyword] += 1

    return deduplicated, contribution_counts
