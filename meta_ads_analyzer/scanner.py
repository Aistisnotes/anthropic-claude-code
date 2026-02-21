"""Scan orchestrator - metadata-only ad extraction."""

from __future__ import annotations

from typing import Any, Optional

from meta_ads_analyzer.classifier.product_type import classify_product_type_batch
from meta_ads_analyzer.models import ScanResult
from meta_ads_analyzer.scraper.meta_library import MetaAdsScraper
from meta_ads_analyzer.selector import aggregate_by_advertiser, rank_advertisers
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def run_scan(
    query: str,
    config: dict[str, Any],
    classify_products: bool = True,
    page_id: Optional[str] = None,
    expected_page_name: Optional[str] = None,
) -> ScanResult:
    """Run metadata-only scan of Meta Ads Library.

    Args:
        query: Search keyword or advertiser name
        config: Full config dict
        classify_products: Whether to classify product types (default True)
        page_id: Optional Facebook page ID; when set uses view_all_page_id URL
                 which returns ALL ads from that specific page directly.
        expected_page_name: When set, abort early if no ads match this page_name
                 after 3 scrolls (used in Stage B to skip other brands' pages fast).

    Returns:
        ScanResult with ads and ranked advertisers
    """
    if page_id:
        logger.info(f"Starting scan for page_id: {page_id} (brand: {query})")
    else:
        logger.info(f"Starting scan for: {query}")

    # Use existing MetaAdsScraper
    scraper = MetaAdsScraper(config)
    ads = await scraper.scrape(query, page_id=page_id, expected_page_name=expected_page_name)
    found_page_ids = list(scraper._found_page_ids)  # view_all_page_id from advertiser header

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
        found_page_ids=found_page_ids,
    )
