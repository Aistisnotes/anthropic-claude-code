"""Direct Brand URL pipeline.

Analyzes specific brands by searching Meta Ads Library using their domain URLs.
Captures ads from all pages (1st and 3rd party affiliates) sorted by impressions.
Runs full analysis + compare + PDF in a single pass.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from meta_ads_analyzer.models import (
    AdvertiserEntry,
    BrandReport,
    BrandSelection,
    ClassifiedAd,
    MarketResult,
    PatternReport,
    ScrapedAd,
    SelectionStats,
)
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


def _clean_domain(raw: str) -> str:
    """Strip protocol/www from a URL to get a bare domain for search."""
    raw = raw.strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^www\.", "", raw)
    raw = raw.split("/")[0]  # drop any path
    return raw


class DirectPipeline:
    """Analyze a list of brand domains directly via Meta Ads Library search."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.output_dir = Path(
            config.get("reporting", {}).get("output_dir", "output/reports")
        )

    async def run(
        self,
        domains: list[str],
        ads_per_brand: int = 30,
        focus_brand: Optional[str] = None,
        run_compare: bool = True,
    ) -> MarketResult:
        """Analyze brands by domain URL.

        Args:
            domains: List of brand domains (e.g. ['tryelar.com', 'sculptiquehealth.com'])
            ads_per_brand: Target number of ads to analyze per brand
            focus_brand: Optional focus brand name for compare gap analysis
            run_compare: Whether to run compare + loophole generation after analysis

        Returns:
            MarketResult with brand_reports and output_dir set
        """
        if not domains:
            raise ValueError("At least one domain is required")

        clean_domains = [_clean_domain(d) for d in domains if d.strip()]
        logger.info(f"Direct pipeline: {len(clean_domains)} domains, {ads_per_brand} ads each")

        # Create output directory
        market_subdir = self._create_market_dir(clean_domains)

        from meta_ads_analyzer.market_pipeline import MarketPipeline
        from meta_ads_analyzer.pipeline import Pipeline
        from meta_ads_analyzer.scraper.meta_library import MetaAdsScraper

        pipeline = Pipeline(self.config)
        market_pipeline = MarketPipeline(self.config)
        market_pipeline.market_subdir = market_subdir
        scraper = MetaAdsScraper(self._scraper_config(ads_per_brand * 2))

        brand_reports: list[BrandReport] = []

        for domain in clean_domains:
            logger.info(f"Scraping domain: {domain}")
            try:
                ads = await scraper.scrape(domain, sort_by_impressions=True)
                logger.info(f"  Scraped {len(ads)} ads for {domain}")

                if not ads:
                    logger.warning(f"  No ads found for {domain}, skipping")
                    continue

                # Sort by impressions descending (should already be sorted via URL,
                # but ensure it as a fallback)
                ads.sort(key=lambda a: a.impression_lower, reverse=True)

                # Cap at ads_per_brand for analysis
                analyze_ads = ads[:ads_per_brand]

                # Build a minimal AdvertiserEntry from scraped data
                brand_name = self._infer_brand_name(domain, analyze_ads)
                advertiser = AdvertiserEntry(
                    page_name=brand_name,
                    ad_count=len(ads),
                    active_ad_count=len(ads),
                    total_impression_lower=sum(a.impression_lower for a in analyze_ads),
                )

                # Run full analysis (download, transcribe, Claude)
                logger.info(f"  Analyzing {len(analyze_ads)} ads for {brand_name}")
                pattern_report = await pipeline.run_from_scraped_ads(
                    scraped_ads=analyze_ads,
                    query=domain,
                    brand=brand_name,
                )

                brand_report = BrandReport(
                    advertiser=advertiser,
                    keyword=domain,
                    pattern_report=pattern_report,
                    generated_at=datetime.utcnow(),
                )

                # Save brand report to disk
                pipeline.reporter.save_brand_report(brand_report, market_subdir)
                brand_reports.append(brand_report)
                logger.info(f"  Done: {brand_name} ({pattern_report.total_ads_analyzed} ads analyzed)")

            except Exception as e:
                logger.error(f"Failed to analyze domain {domain}: {e}")
                continue

        if not brand_reports:
            raise ValueError("No brand reports generated — all domains failed or had no ads")

        # Build MarketResult
        result = MarketResult(
            keyword=", ".join(clean_domains[:3]),
            country="US",
            total_advertisers=len(clean_domains),
            brands_analyzed=len(brand_reports),
            brand_reports=brand_reports,
            competition_level="normal" if len(brand_reports) >= 3 else "thin",
            output_dir=market_subdir,
        )

        # Run compare + PDF
        if run_compare and len(brand_reports) >= 2:
            logger.info("Running compare + loophole generation")
            try:
                await self._run_compare_and_pdf(
                    brand_reports=brand_reports,
                    domains=clean_domains,
                    focus_brand=focus_brand,
                    market_subdir=market_subdir,
                )
            except Exception as e:
                logger.error(f"Compare/PDF generation failed: {e}")

        return result

    def _scraper_config(self, max_ads: int) -> dict[str, Any]:
        """Build scraper config with overridden max_ads."""
        cfg = dict(self.config)
        cfg.setdefault("scraper", {})
        cfg["scraper"] = dict(cfg["scraper"])
        cfg["scraper"]["max_ads"] = max_ads
        return cfg

    def _infer_brand_name(self, domain: str, ads: list[ScrapedAd]) -> str:
        """Infer brand name from domain or first ad's page_name."""
        # Try to get page_name from the most-impression ad
        for ad in ads[:5]:
            if ad.page_name and len(ad.page_name) > 2:
                return ad.page_name
        # Fall back to domain without TLD
        stem = domain.split(".")[0]
        return stem.title()

    def _create_market_dir(self, domains: list[str]) -> Path:
        """Create output directory for this direct run."""
        # Use first domain as slug
        first = domains[0].split(".")[0][:20]
        slug = re.sub(r"[^a-z0-9]", "_", first.lower())
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        subdir = self.output_dir / f"market_direct_{slug}_{timestamp}"
        subdir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created market directory: {subdir}")
        return subdir

    async def _run_compare_and_pdf(
        self,
        brand_reports: list[BrandReport],
        domains: list[str],
        focus_brand: Optional[str],
        market_subdir: Path,
    ) -> None:
        """Run compare pipeline on the brand reports, save PDF."""
        from meta_ads_analyzer.compare_pipeline import ComparePipeline
        from meta_ads_analyzer.reporter.pdf_generator import generate_pdf_sync

        keyword = ", ".join(domains[:3])
        compare_pipeline = ComparePipeline(self.config)

        # Run compare using the market_subdir directly (avoids slug-search)
        compare_result = await compare_pipeline.run(
            keyword=keyword,
            focus_brand=focus_brand,
            from_reports=market_subdir,  # direct path — triggers name.startswith("market_") check
        )

        # Generate PDF
        compare_dirs = sorted(
            (self.output_dir).glob("compare_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if compare_dirs:
            latest_compare = compare_dirs[0]
            loophole_path = latest_compare / "strategic_loophole_doc.json"
            market_map_path = latest_compare / "strategic_market_map.json"

            if loophole_path.exists():
                pdf_out = Path(os.environ.get(
                    "PDF_OUTPUT_DIR",
                    str(Path.home() / "Desktop" / "reports")
                ))
                pdf_out.mkdir(parents=True, exist_ok=True)

                try:
                    pdf_path = generate_pdf_sync(
                        loophole_doc_path=loophole_path,
                        market_map_path=market_map_path,
                        output_dir=pdf_out,
                    )
                    logger.info(f"PDF saved: {pdf_path}")
                except Exception as e:
                    logger.error(f"PDF generation failed: {e}")
