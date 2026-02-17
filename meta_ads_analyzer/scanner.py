"""Scan orchestrator - metadata-only ad extraction."""

from __future__ import annotations

from typing import Any

from meta_ads_analyzer.classifier.product_type import classify_product_type_batch
from meta_ads_analyzer.models import ScanResult
from meta_ads_analyzer.scraper.meta_library import MetaAdsScraper
from meta_ads_analyzer.selector import aggregate_by_advertiser, rank_advertisers
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def run_scan(
    query: str, config: dict[str, Any], classify_products: bool = True
) -> ScanResult:
    """Run metadata-only scan of Meta Ads Library.

    Args:
        query: Search keyword or advertiser name
        config: Full config dict
        classify_products: Whether to classify product types (default True)

    Returns:
        ScanResult with ads and ranked advertisers
    """
    logger.info(f"Starting scan for: {query}")

    # Use existing MetaAdsScraper
    scraper = MetaAdsScraper(config)
    ads = await scraper.scrape(query)

    logger.info(f"Scraped {len(ads)} ads")

    # Classify product types
    if classify_products and ads:
        classifications = await classify_product_type_batch(ads, config)
        for ad in ads:
            if ad.ad_id in classifications:
                ad.product_type = classifications[ad.ad_id]

    # Aggregate by advertiser
    advertisers = aggregate_by_advertiser(ads)

    # Rank advertisers
    ranked = rank_advertisers(advertisers)

    logger.info(f"Found {len(ranked)} unique advertisers")

    return ScanResult(
        keyword=query,
        country=config.get("scraper", {}).get("filters", {}).get("country", "US"),
        ads=ads,
        advertisers=ranked,
        total_fetched=len(ads),
        pages_scanned=1,  # MetaAdsScraper scrolls single page
    )
