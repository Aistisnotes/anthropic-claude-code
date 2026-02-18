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
from meta_ads_analyzer.models import BrandReport, BrandSelection, MarketResult, ProductType, ScanResult, ScrapedAd
from meta_ads_analyzer.pipeline import Pipeline
from meta_ads_analyzer.selector import aggregate_by_advertiser, rank_advertisers, select_ads_for_brand
from meta_ads_analyzer.utils.logging import get_logger

# Minimum qualifying ads a brand must have to be included in competitive analysis
BLUE_OCEAN_THRESHOLD = 50

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
        focus_brand: Optional[str] = None,
    ) -> MarketResult:
        """Run market research pipeline.

        Args:
            keyword: Search keyword
            top_brands: Number of top brands to analyze
            ads_per_brand: Max ads per brand to analyze
            from_scan: Optional path to saved scan JSON
            focus_brand: Optional focus brand name to check for product match

        Returns:
            MarketResult with all brand reports
        """
        logger.info(f"Starting market research for '{keyword}'")
        logger.info(f"Analyzing top {top_brands} brands, {ads_per_brand} ads each")
        if focus_brand:
            logger.info(f"Focus brand: {focus_brand} (will check for product match)")

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

        # 1b. Product matcher: check if focus brand matches market results
        keyword_contributions = {keyword: len(scan_result.ads)}
        if focus_brand and not from_scan:
            scan_result, keyword_contributions = await self._maybe_expand_for_focus_brand(
                focus_brand, keyword, scan_result, keyword_contributions
            )

        # 1c. Keyword expansion if results are sparse (AFTER filtering and product match check)
        if not from_scan:  # Only expand if we did a fresh scan
            scan_result, keyword_contributions = await self._maybe_expand_keywords(
                keyword, scan_result
            )

        # 1d. Detect page networks (optional - for future network analysis)
        from meta_ads_analyzer.network.page_network_detector import detect_page_networks

        logger.info("Detecting page networks...")
        page_to_network = await detect_page_networks(scan_result.ads, self.config)

        if page_to_network:
            # Count unique networks by network_name (PageNetwork isn't hashable)
            unique_network_names = set(network.network_name for network in page_to_network.values())
            unique_networks = len(unique_network_names)
            logger.info(f"Detected {unique_networks} brand networks across {len(page_to_network)} pages")
            # TODO: Update advertiser aggregation to use networks in future version
        else:
            logger.info("No multi-page brand networks detected")

        # 2. Deep brand search + competition check
        top_advertisers = scan_result.advertisers[:top_brands]
        console.print(f"\n[cyan]Deep brand search for top {len(top_advertisers)} brands...[/]")

        brand_deep_ads: dict[str, list[ScrapedAd]] = {}
        brand_ad_counts: dict[str, int] = {}

        for advertiser in top_advertisers:
            brand_name = advertiser.page_name

            # Keyword scan ads for this brand
            keyword_ads = [ad for ad in scan_result.ads if ad.page_name == brand_name]

            # Deep brand-specific search (tries multiple query variations)
            deep_ads = await self._deep_search_brand(brand_name, dominant_type, keyword_ads)

            # Combine keyword ads + deep ads, deduplicate by ad_id
            # deep_ads already filtered to page_name==brand_name, so no cross-brand contamination
            seen_ids: set[str] = set()
            combined: list[ScrapedAd] = []
            for ad in keyword_ads + deep_ads:
                if ad.ad_id not in seen_ids:
                    seen_ids.add(ad.ad_id)
                    combined.append(ad)

            # Apply product type filter to combined set
            if dominant_type != ProductType.UNKNOWN:
                filtered = filter_ads_by_product_type(combined, dominant_type, allow_unknown=True)
            else:
                filtered = combined

            brand_deep_ads[brand_name] = filtered
            brand_ad_counts[brand_name] = len(filtered)

            console.print(
                f"  [dim]{brand_name[:35]:35s}  "
                f"keyword={len(keyword_ads):3d}  deep={len(deep_ads):3d}  "
                f"qualifying={len(filtered):3d}[/]"
            )

        # Determine competition level
        competition_level, qualifying_brands = self._check_competition_level(brand_ad_counts)

        if competition_level == "blue_ocean":
            return await self._handle_blue_ocean(
                keyword, scan_result, brand_ad_counts, focus_brand, dominant_type
            )

        if competition_level == "thin":
            console.print(
                f"\n[yellow]⚠ THIN COMPETITION: Only {len(qualifying_brands)} brand(s) "
                f"have 50+ qualifying ads. Results may have low statistical confidence.[/]"
            )
        else:
            console.print(
                f"\n[green]✓ {len(qualifying_brands)} brands with 50+ qualifying ads — "
                "proceeding with full analysis[/]"
            )

        # 3. Build brand selections from deep ads (skip brands below threshold)
        brand_selections = await self._select_brands_from_deep_ads(
            top_advertisers, brand_deep_ads, brand_ad_counts, ads_per_brand
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
                competition_level=competition_level,
            )

        console.print(f"[cyan]Selected {len(brand_selections)} brands for analysis[/]")

        # Create market subdirectory for reports
        keyword_slug = "".join(c if c.isalnum() else "_" for c in keyword)[:50]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.config.get("reporting", {}).get("output_dir", "output/reports"))
        self.market_subdir = output_dir / f"market_{keyword_slug}_{timestamp}"
        self.market_subdir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Market reports will be saved to: {self.market_subdir}")

        # 4. Analyze each brand
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

        # 5. Return result
        return MarketResult(
            keyword=keyword,
            country=scan_result.country,
            scan_date=scan_result.scan_date,
            total_advertisers=len(scan_result.advertisers),
            brands_analyzed=len(brand_reports),
            brand_reports=brand_reports,
            competition_level=competition_level,
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

    async def _deep_search_brand(
        self,
        brand_name: str,
        dominant_type: ProductType,
        keyword_ads: list[ScrapedAd] | None = None,
    ) -> list[ScrapedAd]:
        """Search multiple query variations to get a brand's full ad library.

        Tries the page name, common-prefix-stripped variants, and domain stems
        extracted from the brand's own ad link_urls. Filters every result to
        only ads whose page_name matches this brand so cross-brand contamination
        is impossible. Uses a higher max_ads cap (300) to surface large ad libraries.

        Args:
            brand_name: Meta page name (e.g. "TryElare")
            dominant_type: Market-dominant product type for filtering
            keyword_ads: Ads already collected for this brand from the keyword scan
                         (used to extract domain/brand_name variations)

        Returns:
            Deduplicated list of this brand's ads (product-type filtered if applicable)
        """
        queries = self._generate_brand_queries(brand_name, keyword_ads or [])

        # Deep searches use higher limits than the keyword scan:
        # - max_ads=500: handles brands with 300+ active ads
        # - max_scroll_attempts=100: allows thorough scrolling for large libraries
        deep_config = {
            **self.config,
            "scraper": {
                **self.config.get("scraper", {}),
                "max_ads": 500,
                "max_scroll_attempts": 100,
            },
        }

        all_brand_ads: dict[str, ScrapedAd] = {}  # ad_id → ScrapedAd, cross-query deduped
        seen_page_ids: set[str] = set()

        from meta_ads_analyzer.scanner import run_scan as _run_scan

        # Stage A: keyword query variations.
        # Runs first so we can collect view_all_page_id values discovered in the
        # advertiser header sections of each search results page.
        for query in queries:
            try:
                logger.info(f"Deep brand search: '{brand_name}' via query '{query}'")
                scan = await _run_scan(query, deep_config)
                # Only keep ads that belong to THIS brand (page_name exact match)
                brand_ads = [ad for ad in scan.ads if ad.page_name == brand_name]
                new_count = sum(1 for ad in brand_ads if ad.ad_id not in all_brand_ads)
                for ad in brand_ads:
                    all_brand_ads[ad.ad_id] = ad
                logger.info(
                    f"  '{query}': {len(scan.ads)} total ads → "
                    f"{len(brand_ads)} for '{brand_name}' ({new_count} new)"
                )
                # Collect page_ids surfaced in advertiser header sections
                for pid in scan.found_page_ids:
                    if pid not in seen_page_ids:
                        seen_page_ids.add(pid)
                        logger.info(f"  Discovered page_id from '{query}' results: {pid}")
            except Exception as e:
                logger.warning(f"Deep brand search failed for query '{query}': {e}")

        # Stage B: page_id-based search (view_all_page_id returns ALL ads from the page).
        # Only runs if keyword searches discovered a page_id — this is the most
        # complete way to enumerate a brand's full ad library.
        for page_id in seen_page_ids:
            try:
                logger.info(f"Deep brand search: '{brand_name}' via page_id '{page_id}'")
                scan = await _run_scan(brand_name, deep_config, page_id=page_id)
                # Only keep ads whose page_name matches the target brand.
                # When the page_id came from a co-advertiser page in search results
                # (not the brand's own page), page_name won't match — skip those.
                brand_ads = [ad for ad in scan.ads if ad.page_name == brand_name]
                if not brand_ads:
                    logger.info(
                        f"  page_id={page_id}: 0 ads match page_name='{brand_name}' "
                        "(likely another advertiser's page) — skipping"
                    )
                    continue
                new_count = sum(1 for ad in brand_ads if ad.ad_id not in all_brand_ads)
                for ad in brand_ads:
                    all_brand_ads[ad.ad_id] = ad
                logger.info(
                    f"  page_id={page_id}: {len(scan.ads)} total ads → "
                    f"{len(brand_ads)} for '{brand_name}' ({new_count} new)"
                )
            except Exception as e:
                logger.warning(f"Deep brand search (page_id={page_id}) failed: {e}")

        combined = list(all_brand_ads.values())
        if dominant_type != ProductType.UNKNOWN:
            return filter_ads_by_product_type(combined, dominant_type, allow_unknown=True)
        return combined

    def _generate_brand_queries(
        self, page_name: str, keyword_ads: list[ScrapedAd]
    ) -> list[str]:
        """Generate ordered list of unique search query variations for a brand.

        Strategy (in priority order):
        1. Original page name  (e.g. "TryElare")
        2. Page name with marketing prefix stripped  (e.g. "Elare")
        3. Domain stem from ad link_urls  (e.g. "elare" from "elare.store")
        4. brand_name field from ad copy if present and different

        Deduplication is case-insensitive so "Elare" and "elare" aren't both sent.
        """
        from urllib.parse import urlparse

        MARKETING_PREFIXES = [
            "try", "get", "buy", "shop", "use", "the", "official",
            "my", "best", "order", "visit", "grab", "discover",
        ]

        queries: list[str] = []
        seen: set[str] = set()  # Case-sensitive: Meta search IS case-sensitive

        def add(q: str) -> None:
            q = q.strip()
            if q and q not in seen:
                seen.add(q)
                queries.append(q)

        # 1. Original page name
        add(page_name)

        # 2. Strip one marketing prefix — add BOTH original case and lowercase.
        # Meta search is case-sensitive and lowercase often returns more results
        # (e.g. "elare" returns 88 TryElare ads vs "Elare" returning only 25).
        lower = page_name.lower()
        for prefix in MARKETING_PREFIXES:
            if lower.startswith(prefix) and len(page_name) > len(prefix) + 2:
                stripped = page_name[len(prefix):]
                add(stripped)            # e.g. "Elare"
                add(stripped.lower())    # e.g. "elare" — often returns more results
                break

        # 3. Domain stems from link_urls in keyword ads
        for ad in keyword_ads:
            if not ad.link_url:
                continue
            try:
                netloc = urlparse(ad.link_url).netloc  # e.g. "www.elare.store"
                if netloc.startswith("www."):
                    netloc = netloc[4:]  # "elare.store"
                stem = netloc.split(".")[0]  # "elare"
                add(stem)
                add(netloc)  # full domain e.g. "elare.store"
            except Exception:
                pass

        # 4. brand_name field from ad copy (if populated and different)
        for ad in keyword_ads:
            if ad.brand_name:
                add(ad.brand_name)

        return queries

    def _check_competition_level(
        self, brand_ad_counts: dict[str, int]
    ) -> tuple[str, list[str]]:
        """Determine competition level based on qualifying ad counts.

        Returns:
            (level, qualifying_brand_names) where level is "normal", "thin", or "blue_ocean"
        """
        qualifying = [
            brand for brand, count in brand_ad_counts.items()
            if count >= BLUE_OCEAN_THRESHOLD
        ]
        if len(qualifying) == 0:
            return "blue_ocean", []
        elif len(qualifying) <= 2:
            return "thin", qualifying
        else:
            return "normal", qualifying

    async def _select_brands_from_deep_ads(
        self,
        top_advertisers: list,
        brand_deep_ads: dict[str, list[ScrapedAd]],
        brand_ad_counts: dict[str, int],
        ads_per_brand: int,
    ) -> list[BrandSelection]:
        """Select best ads per brand from the deep-search combined ad pool.

        Only includes brands meeting the BLUE_OCEAN_THRESHOLD.
        """
        selections = []
        for advertiser in top_advertisers:
            brand_name = advertiser.page_name
            qualifying_count = brand_ad_counts.get(brand_name, 0)

            if qualifying_count < BLUE_OCEAN_THRESHOLD:
                logger.info(
                    f"Skipping {brand_name}: {qualifying_count} qualifying ads "
                    f"(below {BLUE_OCEAN_THRESHOLD} threshold)"
                )
                continue

            deep_ads = brand_deep_ads.get(brand_name, [])
            selection_result = select_ads_for_brand(
                all_ads=deep_ads,
                brand_name=brand_name,
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
                logger.info(f"{brand_name}: selected {len(selection_result.selected)} ads from {qualifying_count} qualifying")
            else:
                logger.warning(f"{brand_name}: no ads passed P1-P4 selection (skipping)")

        return selections

    async def _handle_blue_ocean(
        self,
        keyword: str,
        scan_result: ScanResult,
        brand_ad_counts: dict[str, int],
        focus_brand: Optional[str],
        dominant_type: ProductType,
    ) -> MarketResult:
        """Handle blue ocean case: no brands have 50+ qualifying ads.

        Runs focus brand analysis (if provided) and generates blue ocean report.
        """
        from meta_ads_analyzer.compare.blue_ocean_doc import generate_blue_ocean_doc, save_blue_ocean_doc
        from meta_ads_analyzer.reporter.pdf_generator import generate_blue_ocean_pdf

        console.print("\n[bold yellow]🌊  BLUE OCEAN DETECTED[/]")
        console.print(
            f"[yellow]No brand has {BLUE_OCEAN_THRESHOLD}+ qualifying ads "
            f"in '{keyword}' on Meta.[/]"
        )
        console.print(
            "[yellow]This is a first-mover opportunity — "
            "you can own this category.[/]\n"
        )

        # Show brand counts table
        self._show_brand_ad_counts_table(brand_ad_counts)

        # Run full pipeline on focus brand if specified
        focus_pattern_report = None
        if focus_brand:
            console.print(f"\n[cyan]Running deep brand analysis: {focus_brand}[/]")
            try:
                focus_pattern_report = await self.pipeline.run(
                    query=focus_brand,
                    brand=focus_brand,
                )
                console.print(
                    f"[green]✓ Focus brand analysis complete "
                    f"({focus_pattern_report.total_ads_analyzed} ads)[/]"
                )
            except Exception as e:
                logger.error(f"Focus brand analysis failed: {e}")
                console.print(f"[yellow]⚠ Focus brand analysis failed: {e}[/]")

        # Generate blue ocean document
        console.print("\n[cyan]Generating blue ocean strategy...[/]")
        blue_ocean_doc = await generate_blue_ocean_doc(
            keyword=keyword,
            focus_brand=focus_brand,
            brand_ad_counts=brand_ad_counts,
            focus_brand_pattern_report=focus_pattern_report,
            config=self.config,
        )

        # Create output directory and save
        keyword_slug = "".join(c if c.isalnum() else "_" for c in keyword)[:50]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.config.get("reporting", {}).get("output_dir", "output/reports"))
        self.market_subdir = output_dir / f"market_{keyword_slug}_{timestamp}"
        self.market_subdir.mkdir(parents=True, exist_ok=True)

        save_blue_ocean_doc(blue_ocean_doc, self.market_subdir)
        console.print(f"[green]✓ Blue ocean report saved: {self.market_subdir}[/]")

        # Generate PDF
        pdf_out_dir = Path.home() / "Desktop" / "reports"
        try:
            pdf_path = await generate_blue_ocean_pdf(
                blue_ocean_doc=blue_ocean_doc,
                output_dir=pdf_out_dir,
            )
            console.print(f"[bold green]✓ PDF saved: {pdf_path}[/]")
        except Exception as e:
            logger.error(f"Blue ocean PDF generation failed: {e}")
            console.print(f"[yellow]⚠ PDF generation failed: {e}[/]")

        return MarketResult(
            keyword=keyword,
            country=scan_result.country,
            scan_date=scan_result.scan_date,
            total_advertisers=len(scan_result.advertisers),
            brands_analyzed=0,
            brand_reports=[],
            competition_level="blue_ocean",
            blue_ocean_result=blue_ocean_doc.model_dump(mode="json"),
        )

    def _show_brand_ad_counts_table(self, brand_ad_counts: dict[str, int]) -> None:
        """Display a table of brand ad counts."""
        table = Table(title=f"Brand Ad Counts (threshold: {BLUE_OCEAN_THRESHOLD})")
        table.add_column("Brand", style="cyan")
        table.add_column("Qualifying Ads", justify="right", style="yellow")
        table.add_column("Status", style="red")

        sorted_counts = sorted(brand_ad_counts.items(), key=lambda x: x[1], reverse=True)
        for brand, count in sorted_counts:
            status = "✓ Qualifies" if count >= BLUE_OCEAN_THRESHOLD else f"✗ Below {BLUE_OCEAN_THRESHOLD}"
            status_style = "green" if count >= BLUE_OCEAN_THRESHOLD else "red"
            table.add_row(brand[:40], str(count), f"[{status_style}]{status}[/{status_style}]")

        console.print(table)

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

    async def _maybe_expand_for_focus_brand(
        self,
        focus_brand: str,
        primary_keyword: str,
        scan_result: ScanResult,
        keyword_contributions: dict[str, int],
    ) -> tuple[ScanResult, dict[str, int]]:
        """Check if market results match focus brand's product, expand if needed.

        Args:
            focus_brand: Name of focus brand to match against
            primary_keyword: Original keyword used for scan
            scan_result: Initial scan result
            keyword_contributions: Initial keyword contributions

        Returns:
            Tuple of (updated_scan_result, updated_keyword_contributions)
        """
        from meta_ads_analyzer.matching.product_matcher import ProductMatcher

        logger.info(f"Checking if market results match focus brand '{focus_brand}' product type")

        # Step 1: Try to load focus brand report
        focus_brand_report = await self._load_focus_brand_report(focus_brand)
        if not focus_brand_report:
            console.print(
                f"[yellow]⚠ Could not find brand report for '{focus_brand}'. "
                "Run 'meta-ads run' for this brand first.[/]"
            )
            return scan_result, keyword_contributions

        # Step 2: Extract product attributes from focus brand
        matcher = ProductMatcher(self.config)
        try:
            focus_attrs = await matcher.extract_product_attributes(focus_brand_report)
            console.print(
                f"[cyan]Focus brand product:[/] {focus_attrs['product_type']} "
                f"({focus_attrs['category']})"
            )
        except Exception as e:
            logger.error(f"Failed to extract product attributes: {e}")
            return scan_result, keyword_contributions

        # Step 3: Build temporary brand reports from market scan for mismatch detection
        # We don't have full analysis yet, but we can use advertiser info
        temp_market_reports = []
        for advertiser in scan_result.advertisers[:5]:  # Check top 5 brands
            # Create minimal BrandReport for mismatch detection
            from meta_ads_analyzer.models import PatternReport
            temp_report = BrandReport(
                advertiser=advertiser,
                keyword=primary_keyword,
                pattern_report=PatternReport(
                    total_ads_analyzed=advertiser.ad_count,
                    patterns=[],
                    summary="",
                ),
                generated_at=scan_result.scan_date,
            )
            temp_market_reports.append(temp_report)

        # Step 4: Detect mismatch
        is_mismatch, mismatch_details = matcher.detect_mismatch(
            focus_attrs, temp_market_reports
        )

        if not is_mismatch:
            console.print(
                f"[green]✓ Market results match focus brand product type "
                f"({focus_attrs['product_type']})[/]"
            )
            return scan_result, keyword_contributions

        # Step 5: Mismatch detected - show user and expand keywords
        console.print(f"\n[yellow]⚠ PRODUCT MISMATCH DETECTED[/]")
        console.print(f"[dim]{mismatch_details['reason']}[/]")
        console.print(f"\n[cyan]Expanding keywords to find actual competitors...[/]")

        # Generate expansion keywords based on focus brand's actual product
        try:
            expansion_keywords = await matcher.generate_expansion_keywords(
                focus_attrs, primary_keyword
            )
        except Exception as e:
            logger.error(f"Failed to generate expansion keywords: {e}")
            return scan_result, keyword_contributions

        console.print(
            f"[cyan]Generated {len(expansion_keywords)} product-specific keywords:[/] "
            f"{', '.join(expansion_keywords)}"
        )

        # Step 6: Scan each expansion keyword
        all_ads_by_keyword = {primary_keyword: scan_result.ads}
        for kw in expansion_keywords:
            logger.info(f"Scanning expansion keyword: {kw}")
            try:
                expanded_scan = await self._run_scan_stage(kw, from_scan=None)

                # Filter to same product type as focus brand
                dominant_type, _ = get_dominant_product_type(expanded_scan.ads)
                if dominant_type != ProductType.UNKNOWN:
                    expanded_scan.ads = filter_ads_by_product_type(
                        expanded_scan.ads, dominant_type, allow_unknown=True
                    )

                all_ads_by_keyword[kw] = expanded_scan.ads
                console.print(f"  [dim]• {kw}: {len(expanded_scan.ads)} ads[/]")
            except Exception as e:
                logger.error(f"Failed to scan '{kw}': {e}")
                all_ads_by_keyword[kw] = []

        # Step 7: Deduplicate and combine
        deduplicated_ads, contributions = deduplicate_ads_across_keywords(
            all_ads_by_keyword
        )

        console.print(
            f"\n[green]✓ Combined results: {len(deduplicated_ads)} unique ads "
            f"(from {sum(len(ads) for ads in all_ads_by_keyword.values())} total)[/]"
        )

        # Show keyword contributions
        self._show_keyword_contributions(contributions)

        # Check if we found better matches
        new_brands = len(aggregate_by_advertiser(deduplicated_ads))
        old_brands = len(scan_result.advertisers)

        if new_brands > old_brands:
            console.print(
                f"[green]✓ Found {new_brands} brands (up from {old_brands})[/]"
            )
        else:
            console.print(
                f"[yellow]⚠ Still only {new_brands} brands found. "
                "Market may be sparse for this product.[/]"
            )

        # Re-aggregate and rank advertisers with combined ads
        advertisers = aggregate_by_advertiser(deduplicated_ads)
        ranked = rank_advertisers(advertisers)

        # Update scan result
        scan_result.ads = deduplicated_ads
        scan_result.advertisers = ranked
        scan_result.total_fetched = len(deduplicated_ads)

        return scan_result, contributions

    async def _load_focus_brand_report(self, focus_brand: str) -> Optional[BrandReport]:
        """Try to load focus brand's report from most recent run.

        Args:
            focus_brand: Brand name to search for

        Returns:
            BrandReport if found, None otherwise
        """
        output_dir = Path(self.config.get("reporting", {}).get("output_dir", "output/reports"))

        # Look in all brand_report JSON files (case-insensitive search)
        focus_brand_lower = focus_brand.lower()

        for report_file in output_dir.glob("*/brand_report_*.json"):
            try:
                with open(report_file) as f:
                    data = json.load(f)
                report = BrandReport(**data)

                # Verify it's the right brand (case insensitive)
                if report.advertiser.page_name.lower() == focus_brand_lower:
                    logger.info(f"Loaded focus brand report from: {report_file}")
                    return report
            except Exception as e:
                logger.warning(f"Failed to load {report_file}: {e}")
                continue

        logger.warning(f"No brand report found for '{focus_brand}'")
        return None

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
