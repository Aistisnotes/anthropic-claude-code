"""Compare pipeline - orchestrates market map and loophole document generation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from meta_ads_analyzer.models import BrandReport, CompareResult
from meta_ads_analyzer.compare.market_map import generate_market_map, save_market_map
from meta_ads_analyzer.compare.loophole_doc import generate_loophole_doc, save_loophole_doc
from meta_ads_analyzer.compare.claude_enhancements import (
    generate_strategic_recommendations,
)
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class ComparePipeline:
    """Competitive comparison analysis pipeline.

    Orchestrates:
    1. Load brand reports (from disk or fresh market analysis)
    2. Generate market map (dimension matrices, saturation zones)
    3. Generate loophole document (gaps, priority matrix, brand gaps)
    4. Optional Claude enhancement (strategic recommendations)
    5. Save results to subdirectory
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.output_dir = Path(
            config.get("reporting", {}).get("output_dir", "output/reports")
        )

    async def run(
        self,
        keyword: str,
        focus_brand: Optional[str] = None,
        from_reports: Optional[Path] = None,
        from_scan: Optional[Path] = None,
        enhance: bool = False,
        top_brands: int = 5,
        ads_per_brand: int = 10,
    ) -> CompareResult:
        """Run comparison analysis.

        Two modes:
        1. Load existing brand reports (default or from_reports)
        2. Run fresh market analysis from scan (from_scan)

        Args:
            keyword: Search keyword
            focus_brand: Optional focus brand for brand-specific gap analysis
            from_reports: Optional custom reports directory
            from_scan: Optional saved scan file for fresh analysis
            enhance: Whether to add Claude strategic layer
            top_brands: Number of brands for fresh analysis
            ads_per_brand: Max ads per brand for fresh analysis

        Returns:
            CompareResult with market map and loophole document
        """
        logger.info(f"Starting compare pipeline for keyword: {keyword}")

        # Stage 1: Get brand reports
        if from_scan:
            logger.info("Running fresh market analysis from scan")
            brand_reports = await self._run_fresh_analysis(
                keyword, from_scan, top_brands, ads_per_brand
            )
        else:
            logger.info("Loading existing brand reports")
            brand_reports = self._load_brand_reports(keyword, from_reports)

        if len(brand_reports) < 2:
            raise ValueError(
                f"Need at least 2 brand reports for comparison, found {len(brand_reports)}"
            )

        logger.info(f"Comparing {len(brand_reports)} brands")

        # Stage 2: Generate market map
        logger.info("Generating market map")
        market_map = generate_market_map(
            brand_reports, meta={'keyword': keyword, 'scan_date': datetime.utcnow()}
        )

        # Stage 3: Generate loophole document
        logger.info("Generating loophole document")
        loophole_doc = generate_loophole_doc(market_map, brand_reports, focus_brand)

        # Stage 4: Optional Claude enhancement
        if enhance:
            logger.info("Generating Claude strategic recommendations")
            try:
                recommendations = await generate_strategic_recommendations(
                    market_map, brand_reports, focus_brand, self.config
                )
                loophole_doc.strategic_recommendations = recommendations
            except Exception as e:
                logger.error(f"Failed to generate strategic recommendations: {e}")
                logger.warning("Continuing without Claude enhancement")

        # Stage 5: Save results
        output_subdir = self._create_output_dir(keyword)
        save_market_map(market_map, output_subdir)
        save_loophole_doc(loophole_doc, output_subdir)

        logger.info(f"Compare pipeline complete, results saved to: {output_subdir}")

        return CompareResult(
            keyword=keyword,
            market_map=market_map,
            loophole_doc=loophole_doc,
        )

    def _load_brand_reports(
        self, keyword: str, reports_dir: Optional[Path]
    ) -> list[BrandReport]:
        """Load brand reports from disk by keyword slug.

        Args:
            keyword: Search keyword
            reports_dir: Optional custom reports directory

        Returns:
            List of BrandReport objects

        Raises:
            ValueError: If no reports found for keyword
        """
        if reports_dir is None:
            reports_dir = self.output_dir

        # Find matching market directories
        keyword_slug = "".join(c if c.isalnum() else "_" for c in keyword)[:50]
        matching_dirs = list(reports_dir.glob(f"market_{keyword_slug}_*"))

        if not matching_dirs:
            raise ValueError(
                f"No market reports found for keyword: {keyword}\n"
                f"Searched in: {reports_dir}/market_{keyword_slug}_*"
            )

        # Use most recent directory
        latest_dir = max(matching_dirs, key=lambda p: p.stat().st_mtime)
        logger.info(f"Loading reports from: {latest_dir}")

        # Load all brand reports from directory
        brand_reports = []
        for json_file in latest_dir.glob("brand_report_*.json"):
            with open(json_file) as f:
                data = json.load(f)
            brand_reports.append(BrandReport(**data))

        logger.info(f"Loaded {len(brand_reports)} brand reports")
        return brand_reports

    async def _run_fresh_analysis(
        self, keyword: str, scan_path: Path, top_brands: int, ads_per_brand: int
    ) -> list[BrandReport]:
        """Run market pipeline from saved scan to generate fresh brand reports.

        Args:
            keyword: Search keyword
            scan_path: Path to saved scan JSON
            top_brands: Number of brands to analyze
            ads_per_brand: Max ads per brand

        Returns:
            List of BrandReport objects
        """
        from meta_ads_analyzer.market_pipeline import MarketPipeline

        logger.info(f"Running market pipeline from scan: {scan_path}")

        pipeline = MarketPipeline(self.config)
        result = await pipeline.run(
            keyword=keyword,
            top_brands=top_brands,
            ads_per_brand=ads_per_brand,
            from_scan=scan_path,
        )

        return result.brand_reports

    def _create_output_dir(self, keyword: str) -> Path:
        """Create output subdirectory for compare results.

        Args:
            keyword: Search keyword

        Returns:
            Path to output subdirectory
        """
        keyword_slug = "".join(c if c.isalnum() else "_" for c in keyword)[:50]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        subdir = self.output_dir / f"compare_{keyword_slug}_{timestamp}"
        subdir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Created output directory: {subdir}")
        return subdir
