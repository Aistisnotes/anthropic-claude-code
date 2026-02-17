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
from rich.table import Table

from meta_ads_analyzer.classifier.keyword_expander import (
    deduplicate_ads_across_keywords,
    generate_related_keywords,
)
from meta_ads_analyzer.classifier.product_type import (
    filter_ads_by_product_type,
    get_dominant_product_type,
)
from meta_ads_analyzer.models import BrandReport, BrandSelection, MarketResult, ProductType, ScanResult
from meta_ads_analyzer.pipeline import Pipeline
from meta_ads_analyzer.selector import aggregate_by_advertiser, rank_advertisers, select_ads_for_brand
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

        # 1a. Detect dominant product type and filter (BEFORE expansion check)
        dominant_type, distribution = get_dominant_product_type(scan_result.ads)

        # Show product type distribution
        self._show_product_type_distribution(distribution)

        # Filter to dominant product type (unless it's UNKNOWN)
        if dominant_type != ProductType.UNKNOWN:
            console.print(
                f"[cyan]Filtering to {dominant_type.value} ads only "
                f"(dominant product type)[/]"
            )
            filtered_ads = filter_ads_by_product_type(
                scan_result.ads, dominant_type, allow_unknown=True
            )
            logger.info(
                f"Filtered {len(scan_result.ads)} ads down to {len(filtered_ads)} "
                f"matching {dominant_type.value}"
            )
            # Update scan_result with filtered ads
            scan_result.ads = filtered_ads
            # Re-aggregate advertisers after filtering
            from meta_ads_analyzer.selector import aggregate_by_advertiser, rank_advertisers
            advertisers = aggregate_by_advertiser(filtered_ads)
            scan_result.advertisers = rank_advertisers(advertisers)
        else:
            console.print(
                "[yellow]Could not determine dominant product type, "
                "using all ads[/]"
            )

        # 1b. Keyword expansion if results are sparse (AFTER filtering)
        keyword_contributions = {keyword: len(scan_result.ads)}
        if not from_scan:  # Only expand if we did a fresh scan
            scan_result, keyword_contributions = await self._maybe_expand_keywords(
                keyword, scan_result
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

    async def _maybe_expand_keywords(
        self, primary_keyword: str, scan_result: ScanResult
    ) -> tuple[ScanResult, dict[str, int]]:
        """Expand keywords if primary returned sparse results.

        Args:
            primary_keyword: Original keyword
            scan_result: Initial scan result

        Returns:
            Tuple of (updated_scan_result, keyword_contributions)
        """
        # Check if expansion needed (ads are already filtered by product type)
        num_ads = len(scan_result.ads)
        num_brands = len(scan_result.advertisers)

        if num_ads >= 20 and num_brands >= 5:
            logger.info(
                f"Sufficient results ({num_ads} ads, {num_brands} brands), "
                "skipping keyword expansion"
            )
            return scan_result, {primary_keyword: num_ads}

        # Expansion needed
        console.print(
            f"[yellow]Sparse results ({num_ads} ads, {num_brands} brands). "
            "Expanding keywords...[/]"
        )

        # Determine product type for expansion
        dominant_type, _ = get_dominant_product_type(scan_result.ads)

        # Generate related keywords
        related = await generate_related_keywords(
            primary_keyword, dominant_type, self.config, count=4
        )

        if not related:
            logger.warning("No related keywords generated, using primary only")
            return scan_result, {primary_keyword: num_ads}

        console.print(f"[cyan]Scanning {len(related)} related keywords:[/] {', '.join(related)}")

        # Scan each related keyword
        all_ads_by_keyword = {primary_keyword: scan_result.ads}
        for kw in related:
            logger.info(f"Scanning related keyword: {kw}")
            try:
                related_scan = await self._run_scan_stage(kw, from_scan=None)
                all_ads_by_keyword[kw] = related_scan.ads
                console.print(f"  [dim]• {kw}: {len(related_scan.ads)} ads[/]")
            except Exception as e:
                logger.error(f"Failed to scan '{kw}': {e}")
                all_ads_by_keyword[kw] = []

        # Deduplicate across keywords
        deduplicated_ads, contributions = deduplicate_ads_across_keywords(
            all_ads_by_keyword
        )

        console.print(
            f"\n[green]Combined results: {len(deduplicated_ads)} unique ads "
            f"(from {sum(len(ads) for ads in all_ads_by_keyword.values())} total)[/]"
        )

        # Show keyword contributions
        self._show_keyword_contributions(contributions)

        # Re-aggregate and rank advertisers with combined ads
        advertisers = aggregate_by_advertiser(deduplicated_ads)
        ranked = rank_advertisers(advertisers)

        # Update scan result
        scan_result.ads = deduplicated_ads
        scan_result.advertisers = ranked
        scan_result.total_fetched = len(deduplicated_ads)

        return scan_result, contributions

    def _show_keyword_contributions(self, contributions: dict[str, int]) -> None:
        """Display keyword contribution table.

        Args:
            contributions: Dict mapping keyword to unique ad count
        """
        table = Table(title="Keyword Contributions")
        table.add_column("Keyword", style="cyan")
        table.add_column("Unique Ads", justify="right", style="green")
        table.add_column("%", justify="right", style="yellow")

        total = sum(contributions.values())
        sorted_items = sorted(
            contributions.items(), key=lambda x: x[1], reverse=True
        )

        for keyword, count in sorted_items:
            pct = (count / total * 100) if total > 0 else 0
            table.add_row(keyword, str(count), f"{pct:.1f}%")

        console.print(table)

    def _show_product_type_distribution(
        self, distribution: dict[ProductType, int]
    ) -> None:
        """Display product type distribution table.

        Args:
            distribution: Dict mapping ProductType to count
        """
        table = Table(title="Product Type Distribution")
        table.add_column("Product Type", style="cyan")
        table.add_column("Count", justify="right", style="green")
        table.add_column("%", justify="right", style="yellow")

        total = sum(distribution.values())
        sorted_items = sorted(
            distribution.items(), key=lambda x: x[1], reverse=True
        )

        for product_type, count in sorted_items:
            pct = (count / total * 100) if total > 0 else 0
            table.add_row(
                product_type.value, str(count), f"{pct:.1f}%"
            )

        console.print(table)

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
