"""Strategic compare pipeline - orchestrates DR-focused market analysis.

Transformation: Replaced ad craft analysis (hooks, angles, formats) with DR strategy (root causes, mechanisms, avatars).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from meta_ads_analyzer.models import BrandReport
from meta_ads_analyzer.compare.strategic_market_map import (
    generate_strategic_market_map,
    save_strategic_market_map,
    format_strategic_market_map_text,
)
from meta_ads_analyzer.compare.strategic_loophole_doc import (
    generate_strategic_loophole_doc,
    save_strategic_loophole_doc,
    format_strategic_loophole_doc_text,
)
from meta_ads_analyzer.compare.strategic_dimensions import StrategicCompareResult
from meta_ads_analyzer.utils.logging import get_logger
from rich.console import Console

logger = get_logger(__name__)
console = Console()


class ComparePipeline:
    """Strategic competitive comparison pipeline.

    Orchestrates:
    1. Load brand reports (from disk or fresh market analysis)
    2. Extract strategic dimensions for each brand (6 dimensions: root causes, mechanisms, audiences, pain points, symptoms, desires)
    3. Generate strategic market map (compare patterns across brands)
    4. Generate loophole document (5-7 execution-ready arbitrage opportunities)
    5. Save results and display summary
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
        enhance: bool = True,  # Changed default to True - strategic analysis always uses Claude
        top_brands: int = 5,
        ads_per_brand: int = 10,
    ) -> StrategicCompareResult:
        """Run strategic comparison analysis.

        Two modes:
        1. Load existing brand reports (default or from_reports)
        2. Run fresh market analysis from scan (from_scan)

        Args:
            keyword: Search keyword
            focus_brand: Optional focus brand for brand-specific loophole identification
            from_reports: Optional custom reports directory
            from_scan: Optional saved scan file for fresh analysis
            enhance: Whether to generate loopholes (default True - always strategic)
            top_brands: Number of brands for fresh analysis
            ads_per_brand: Max ads per brand for fresh analysis

        Returns:
            StrategicCompareResult with strategic market map and loophole document
        """
        logger.info(f"Starting STRATEGIC compare pipeline for keyword: {keyword}")

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

        logger.info(f"Comparing {len(brand_reports)} brands using DR strategy framework")

        # Stage 2: Generate strategic market map (6-dimension analysis)
        logger.info("Generating strategic market map (root causes, mechanisms, audiences, pain points, symptoms, desires)")
        market_map = await generate_strategic_market_map(
            brand_reports,
            meta={'keyword': keyword, 'scan_date': datetime.utcnow()},
            focus_brand=focus_brand,
            config=self.config,
        )

        # Display market map summary
        console.print(format_strategic_market_map_text(market_map))

        # Stage 3: Generate strategic loophole document (5-7 execution-ready opportunities)
        loophole_doc = None
        if enhance:
            logger.info("Generating strategic loophole document (arbitrage opportunities)")
            try:
                loophole_doc = await generate_strategic_loophole_doc(
                    market_map, brand_reports, focus_brand, self.config
                )

                # Display loophole summary
                console.print(format_strategic_loophole_doc_text(loophole_doc))

            except Exception as e:
                logger.error(f"Failed to generate strategic loopholes: {e}")
                logger.warning("Continuing with market map only")

        # Stage 4: Save results
        output_subdir = self._create_output_dir(keyword)
        save_strategic_market_map(market_map, output_subdir)

        if loophole_doc:
            save_strategic_loophole_doc(loophole_doc, output_subdir)

        logger.info(f"Strategic compare complete, results saved to: {output_subdir}")

        return StrategicCompareResult(
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

        # Filter out brands with 0 ads analyzed
        original_count = len(brand_reports)
        brand_reports = [
            r for r in brand_reports
            if r.pattern_report.total_ads_analyzed > 0
        ]
        if len(brand_reports) < original_count:
            logger.info(f"Filtered to {len(brand_reports)} brands with ads analyzed (removed {original_count - len(brand_reports)} brands with 0 ads)")

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
