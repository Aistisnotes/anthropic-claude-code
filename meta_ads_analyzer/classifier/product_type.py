"""Product type classification for market filtering."""

from __future__ import annotations

import anthropic

from meta_ads_analyzer.models import ProductType, ScrapedAd
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def classify_product_type_batch(ads: list[ScrapedAd], config: dict) -> dict[str, ProductType]:
    """Classify product types for a batch of ads using Claude.

    Args:
        ads: List of scraped ads to classify
        config: Config dict with API settings

    Returns:
        Dict mapping ad_id to ProductType
    """
    if not ads:
        return {}

    logger.info(f"Classifying product types for {len(ads)} ads")

    # Build batch classification prompt
    ad_samples = []
    for i, ad in enumerate(ads[:50], 1):  # Limit to 50 ads per batch
        text = ad.primary_text or ""
        headline = ad.headline or ""
        ad_samples.append(f"{i}. [{ad.page_name}] {headline} | {text[:200]}")

    prompt = f"""Classify the product/service type for each ad below. Return ONLY a JSON array with one ProductType per ad.

Product Types:
- supplement: Oral supplements, vitamins, herbs, pills, capsules
- device: Physical devices, tools, machines, gadgets (massage tools, red light therapy, etc.)
- service: Services, coaching, consulting, subscriptions to human services
- skincare: Topical skincare products, creams, serums, lotions
- tool: Physical tools or equipment (not devices)
- apparel: Clothing, accessories, wearables
- software: Apps, software, digital tools
- info_product: Courses, ebooks, training programs, memberships
- food_beverage: Food, drinks, meal plans
- other: Anything else
- unknown: Cannot determine

Ads to classify:
{chr(10).join(ad_samples)}

Return JSON array (one per ad): ["supplement", "device", "supplement", ...]

ONLY return the JSON array, no other text."""

    try:
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514"),
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        import json

        text = response.content[0].text.strip()

        # Extract JSON array from response
        if "[" in text and "]" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            json_text = text[start:end]
            classifications = json.loads(json_text)
        else:
            logger.warning("Could not parse product type classifications, defaulting to unknown")
            return {ad.ad_id: ProductType.UNKNOWN for ad in ads}

        # Map back to ad IDs
        result = {}
        for i, ad in enumerate(ads[:len(classifications)]):
            try:
                product_type = ProductType(classifications[i].lower())
                result[ad.ad_id] = product_type
            except (ValueError, IndexError):
                result[ad.ad_id] = ProductType.UNKNOWN

        # Fill in any missing with UNKNOWN
        for ad in ads:
            if ad.ad_id not in result:
                result[ad.ad_id] = ProductType.UNKNOWN

        logger.info(f"Classified {len(result)} product types")
        return result

    except Exception as e:
        logger.error(f"Failed to classify product types: {e}")
        return {ad.ad_id: ProductType.UNKNOWN for ad in ads}


def get_dominant_product_type(ads: list[ScrapedAd]) -> tuple[ProductType, dict[ProductType, int]]:
    """Get dominant product type from a list of ads.

    Args:
        ads: List of ads

    Returns:
        Tuple of (dominant_type, distribution_dict)
    """
    distribution: dict[ProductType, int] = {}
    for ad in ads:
        distribution[ad.product_type] = distribution.get(ad.product_type, 0) + 1

    # Remove UNKNOWN from consideration
    candidates = {pt: count for pt, count in distribution.items() if pt != ProductType.UNKNOWN}

    if not candidates:
        return ProductType.UNKNOWN, distribution

    dominant = max(candidates.items(), key=lambda x: x[1])[0]
    return dominant, distribution


def filter_ads_by_product_type(
    ads: list[ScrapedAd], target_product_type: ProductType, allow_unknown: bool = True
) -> list[ScrapedAd]:
    """Filter ads to only include matching product type.

    Args:
        ads: All ads
        target_product_type: Target product type to keep
        allow_unknown: Whether to keep ads with UNKNOWN product type

    Returns:
        Filtered list of ads
    """
    filtered = []
    for ad in ads:
        if ad.product_type == target_product_type:
            filtered.append(ad)
        elif allow_unknown and ad.product_type == ProductType.UNKNOWN:
            filtered.append(ad)

    return filtered
