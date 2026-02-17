"""Product type classification for market filtering."""

from __future__ import annotations

from urllib.parse import urlparse

import anthropic

from meta_ads_analyzer.models import ProductType, ScrapedAd
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def detect_supplement_signals(ad: ScrapedAd) -> bool:
    """Pre-filter for obvious supplements before Claude classification.

    Args:
        ad: Scraped ad to check

    Returns:
        True if ad contains clear supplement signals
    """
    text = (ad.primary_text or "") + " " + (ad.headline or "") + " " + (ad.description or "")
    text_lower = text.lower()

    supplement_terms = [
        'capsule', 'pill', 'tablet', 'drop', 'softgel', 'formula', 'ingredient',
        'dosage', 'serving', 'supplement', 'vitamin', 'mineral', 'herb', 'extract',
        'mg', 'mcg', 'iu', 'daily', 'bottle', 'dose', 'proprietary blend'
    ]

    return any(term in text_lower for term in supplement_terms)


async def classify_product_type_batch(ads: list[ScrapedAd], config: dict) -> dict[str, ProductType]:
    """Classify product types for a batch of ads using two-pass classification.

    Pass 1: Fast pattern matching for obvious supplements
    Pass 2: Claude classification for remaining ads with enhanced signals

    Args:
        ads: List of scraped ads to classify
        config: Config dict with API settings

    Returns:
        Dict mapping ad_id to ProductType
    """
    if not ads:
        return {}

    logger.info(f"Classifying product types for {len(ads)} ads")

    # Pass 1: Fast pattern matching for obvious supplements
    pre_classified = {}
    remaining_ads = []

    for ad in ads:
        if detect_supplement_signals(ad):
            pre_classified[ad.ad_id] = ProductType.SUPPLEMENT
        else:
            remaining_ads.append(ad)

    if pre_classified:
        logger.info(f"Pre-classified {len(pre_classified)} ads as supplements via pattern matching")

    # Pass 2: Claude classification for remaining ads
    if remaining_ads:
        claude_results = await _classify_with_claude(remaining_ads, config)
        pre_classified.update(claude_results)

    # Fill in any missing with UNKNOWN
    for ad in ads:
        if ad.ad_id not in pre_classified:
            pre_classified[ad.ad_id] = ProductType.UNKNOWN

    logger.info(f"Classified {len(pre_classified)} product types")
    return pre_classified


async def _classify_with_claude(ads: list[ScrapedAd], config: dict) -> dict[str, ProductType]:
    """Classify product types using Claude with enhanced signals.

    Args:
        ads: List of ads to classify
        config: Config dict with API settings

    Returns:
        Dict mapping ad_id to ProductType
    """
    # Build batch classification prompt with ENHANCED SIGNALS
    ad_samples = []
    for i, ad in enumerate(ads[:50], 1):  # Limit to 50 ads per batch
        text = ad.primary_text or ""
        headline = ad.headline or ""
        cta = ad.cta_text or ""
        description = ad.description or ""
        domain = extract_domain(ad.link_url) if ad.link_url else ""

        # Include ALL signals in classification
        ad_samples.append(
            f"{i}. [{ad.page_name}] {headline} | CTA: {cta} | {text[:150]} | Domain: {domain}"
        )

    prompt = f"""Classify product type for each ad. Be AGGRESSIVE - only use "unknown" if genuinely no signal.

Classification Rules:
- If mentions capsules, pills, drops, formula, ingredients, dosage, servings → supplement
- If mentions cream, serum, lotion, skincare ingredients → skincare
- If mentions device features, tool specs, machine → device
- If mentions coaching, consultation, service, membership → service
- Check CTA domain for clues (e.g., shopify store → product, .com/services → service)

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

CRITICAL: Default to best guess rather than "unknown". Unknown should be <10% of results.

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
