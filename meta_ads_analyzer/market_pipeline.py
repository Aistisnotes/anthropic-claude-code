"""Market research pipeline orchestrator.

Coordinates multi-brand competitive analysis:
1. Scan keyword for all ads
2. Rank advertisers by relevance
3. Select top N brands
4. For each brand: select best ads using P1-P4 priority
5. Run full Pipeline (download, transcribe, analyze) on selected ads
6. Generate per-brand reports
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from meta_ads_analyzer.models import BrandReport, BrandSelection, MarketResult, ScanResult
from meta_ads_analyzer.pipeline import Pipeline
from meta_ads_analyzer.selector import select_ads_for_brand
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)
console = Console()


class MarketPipeline:
    """Multi-brand competitive analysis pipeline."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.pipeline = Pipeline(config)
        self.market_subdir: Optional[Path] = None

    async def run(
        self,
        keyword: str,
        top_brands: int = 5,
        ads_per_brand: int = 10,
        from_scan: Optional[Path] = None,
    ) -> MarketResult:
        """Run market research pipeline.

        Args:
            keyword: Search keyword
            top_brands: Number of top brands to analyze
            ads_per_brand: Max ads per brand to analyze
            from_scan: Optional path to saved scan JSON

        Returns:
            MarketResult with all brand reports
        """
        logger.info(f"Starting market research for '{keyword}'")
        logger.info(f"Analyzing top {top_brands} brands, {ads_per_brand} ads each")

        # 1. Scan (or load from file)
        scan_result = await self._run_scan_stage(keyword, from_scan)
        console.print(
            f"\n[bold]Found {len(scan_result.advertisers)} advertisers "
            f"({scan_result.total_fetched} total ads)[/]"
        )

        # 2. Select top brands and their best ads
        brand_selections = await self._select_brands_and_ads(
            scan_result, top_brands, ads_per_brand
        )

        if not brand_selections:
            console.print("[yellow]No brands selected for analysis[/]")
            return MarketResult(
                keyword=keyword,
                country=scan_result.country,
                scan_date=scan_result.scan_date,
                total_advertisers=len(scan_result.advertisers),
                brands_analyzed=0,
                brand_reports=[],
            )

        console.print(f"[cyan]Selected {len(brand_selections)} brands for analysis[/]")

        # Create market subdirectory for reports
        keyword_slug = "".join(c if c.isalnum() else "_" for c in keyword)[:50]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.config.get("reporting", {}).get("output_dir", "output/reports"))
        self.market_subdir = output_dir / f"market_{keyword_slug}_{timestamp}"
        self.market_subdir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Market reports will be saved to: {self.market_subdir}")

        # 3. Analyze each brand
        brand_reports = []
        for i, selection in enumerate(brand_selections, 1):
            console.print(
                f"\n[bold cyan]═══ Analyzing brand {i}/{len(brand_selections)}: "
                f"{selection.advertiser.page_name} ═══[/]"
            )
            console.print(
                f"[dim]Selected {len(selection.selected_ads)} ads "
                f"({selection.selection_stats.total_selected} total)[/]"
            )

            try:
                brand_report = await self._analyze_brand(selection, keyword)
                brand_reports.append(brand_report)
                console.print(
                    f"[green]✓ Completed {selection.advertiser.page_name}[/]"
                )
            except Exception as e:
                logger.error(
                    f"Failed to analyze {selection.advertiser.page_name}: {e}",
                    exc_info=True,
                )
                console.print(
                    f"[red]✗ Failed: {selection.advertiser.page_name} - {str(e)}[/]"
                )
                # Continue with other brands

        # 4. Return result
        return MarketResult(
            keyword=keyword,
            country=scan_result.country,
            scan_date=scan_result.scan_date,
            total_advertisers=len(scan_result.advertisers),
            brands_analyzed=len(brand_reports),
            brand_reports=brand_reports,
        )

    async def _run_scan_stage(
        self, keyword: str, from_scan: Optional[Path]
    ) -> ScanResult:
        """Stage 1: Scan or load from file.

        Args:
            keyword: Search keyword
            from_scan: Optional path to saved scan JSON

        Returns:
            ScanResult with ads and ranked advertisers
        """
        if from_scan:
            logger.info(f"Loading scan from {from_scan}")
            console.print(f"[cyan]Loading scan from:[/] {from_scan}")
            with open(from_scan) as f:
                data = json.load(f)
            return ScanResult(**data)
        else:
            logger.info(f"Running fresh scan for '{keyword}'")
            console.print("[cyan]Scanning Meta Ads Library...[/]")
            from meta_ads_analyzer.scanner import run_scan

            return await run_scan(keyword, self.config)

    async def _select_brands_and_ads(
        self,
        scan_result: ScanResult,
        top_brands: int,
        ads_per_brand: int,
    ) -> list[BrandSelection]:
        """Stage 2: Select top brands and their best ads.

        Args:
            scan_result: Scan result with all ads and ranked advertisers
            top_brands: Number of top brands to select
            ads_per_brand: Max ads per brand

        Returns:
            List of BrandSelection objects
        """
        # Pick top N brands from ranked advertisers
        top_advertisers = scan_result.advertisers[:top_brands]
        logger.info(
            f"Selected top {len(top_advertisers)} advertisers "
            f"(requested {top_brands})"
        )

        # For each brand, select best ads using P1-P4 priority
        selections = []
        for advertiser in top_advertisers:
            selection_result = select_ads_for_brand(
                all_ads=scan_result.ads,
                brand_name=advertiser.page_name,
                limit=ads_per_brand,
                config=self.config,
            )

            if selection_result.selected:
                selections.append(
                    BrandSelection(
                        advertiser=advertiser,
                        selected_ads=selection_result.selected,
                        selection_stats=selection_result.stats,
                    )
                )
                logger.info(
                    f"{advertiser.page_name}: selected {len(selection_result.selected)} ads"
                )
            else:
                logger.warning(
                    f"{advertiser.page_name}: no ads passed selection (skipping)"
                )

        return selections

    async def _analyze_brand(
        self, selection: BrandSelection, keyword: str
    ) -> BrandReport:
        """Stage 3: Analyze a single brand's selected ads.

        Args:
            selection: Brand selection with ads to analyze
            keyword: Search keyword (for report context)

        Returns:
            BrandReport with full analysis
        """
        # Extract ScrapedAd objects from ClassifiedAd wrappers
        selected_ads = [ca.ad for ca in selection.selected_ads]

        logger.info(
            f"Analyzing {len(selected_ads)} ads for {selection.advertiser.page_name}"
        )

        # Run full pipeline (stages 2-8: download, transcribe, analyze, report)
        pattern_report = await self.pipeline.run_from_scraped_ads(
            scraped_ads=selected_ads,
            query=keyword,
            brand=selection.advertiser.page_name,
        )

        # Package as BrandReport
        brand_report = BrandReport(
            advertiser=selection.advertiser,
            keyword=keyword,
            selection_stats=selection.selection_stats,
            pattern_report=pattern_report,
            generated_at=datetime.utcnow(),
        )

        # Save brand report to market subdirectory
        if self.market_subdir:
            self.pipeline.reporter.save_brand_report(brand_report, self.market_subdir)

        return brand_report
