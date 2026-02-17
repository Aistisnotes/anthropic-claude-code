"""Main pipeline orchestrator.

Connects all modules into a single flow:
1. Scrape ads from Meta Ads Library
2. Download media (video/images)
3. Transcribe video ads
4. Filter and classify ads
5. Analyze individual ads (Claude API)
6. Quality gates
7. Pattern analysis (Claude API)
8. Generate report
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from meta_ads_analyzer.analyzer.ad_analyzer import AdAnalyzer
from meta_ads_analyzer.analyzer.filter import AdFilter
from meta_ads_analyzer.analyzer.pattern_analyzer import PatternAnalyzer
from meta_ads_analyzer.db.store import AdStore
from meta_ads_analyzer.downloader.media import MediaDownloader
from meta_ads_analyzer.models import AdContent, AdStatus, PatternReport, ScrapedAd
from meta_ads_analyzer.quality.gates import QualityGates, CopyQualityChecker
from meta_ads_analyzer.reporter.output import ReportWriter
from meta_ads_analyzer.scraper.meta_library import MetaAdsScraper
from meta_ads_analyzer.transcriber.whisper import WhisperTranscriber
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)
console = Console()


class Pipeline:
    """Main pipeline orchestrating the full ad analysis flow."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.scraper = MetaAdsScraper(config)
        self.downloader = MediaDownloader(config)
        self.transcriber = WhisperTranscriber(config)
        self.ad_filter = AdFilter(config)
        self.analyzer = AdAnalyzer(config)
        self.pattern_analyzer = PatternAnalyzer(config)
        self.quality_gates = QualityGates(config)
        self.copy_checker = CopyQualityChecker()
        self.reporter = ReportWriter(config)
        self.store = AdStore()

        pipeline_cfg = config.get("pipeline", {})
        self.save_checkpoints = pipeline_cfg.get("save_checkpoints", True)
        self.checkpoint_dir = Path(pipeline_cfg.get("checkpoint_dir", "output/checkpoints"))

        # Enable debug screenshots if requested
        if config.get("scraper", {}).get("debug", False):
            self.scraper.debug_dir = Path("output/debug")

    async def run(
        self,
        query: str,
        brand: str | None = None,
    ) -> PatternReport:
        """Run the full pipeline for a single query/brand.

        Args:
            query: Search keyword or advertiser name.
            brand: Brand name (used in report). Defaults to query.

        Returns:
            PatternReport with full analysis results.
        """
        brand = brand or query
        run_id = f"{brand.replace(' ', '_')[:20]}_{uuid.uuid4().hex[:8]}"

        async with self.store:
            await self.store.create_run(run_id, query, brand, self.config)

            try:
                report = await self._execute_pipeline(run_id, query, brand)
                await self.store.complete_run(run_id, "completed")
                return report
            except Exception as e:
                await self.store.complete_run(run_id, f"failed: {e}")
                raise

    async def run_from_scraped_ads(
        self,
        scraped_ads: list[ScrapedAd],
        query: str,
        brand: str,
    ) -> PatternReport:
        """Run pipeline stages 2-8 on pre-scraped ads (bypass Stage 1).

        This is used by MarketPipeline to analyze pre-selected ads.

        Args:
            scraped_ads: Pre-selected ads to analyze
            query: Search keyword (for report context)
            brand: Brand name (for report)

        Returns:
            PatternReport with full analysis results
        """
        brand = brand or query
        run_id = f"{brand.replace(' ', '_')[:20]}_{uuid.uuid4().hex[:8]}"

        async with self.store:
            await self.store.create_run(run_id, query, brand, self.config)

            # Save scraped ads to DB
            for ad in scraped_ads:
                await self.store.save_scraped_ad(run_id, ad)

            try:
                report = await self._execute_stages_2_to_8(
                    run_id=run_id,
                    scraped_ads=scraped_ads,
                    query=query,
                    brand=brand
                )
                await self.store.complete_run(run_id, "completed")
                return report
            except Exception as e:
                await self.store.complete_run(run_id, f"failed: {e}")
                raise

    async def _execute_stages_2_to_8(
        self,
        run_id: str,
        scraped_ads: list[ScrapedAd],
        query: str,
        brand: str,
    ) -> PatternReport:
        """Execute stages 2-8 of the pipeline (download through report).

        This is the core analysis pipeline extracted for reuse by MarketPipeline.

        Args:
            run_id: Unique run identifier
            scraped_ads: Ads to analyze
            query: Search keyword
            brand: Brand name

        Returns:
            PatternReport with analysis results
        """
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:

            if not scraped_ads:
                console.print("[red]No ads provided. Aborting.[/]")
                return PatternReport(
                    search_query=query,
                    brand=brand,
                    executive_summary="No ads provided for analysis.",
                )

            # ── Stage 2: Download media ──
            task = progress.add_task(
                "[cyan]Downloading media...", total=len(scraped_ads)
            )
            downloads = await self.downloader.download_ads(scraped_ads, run_id)
            progress.update(task, completed=len(downloads), total=len(scraped_ads))
            dl_count = sum(1 for v in downloads.values() if v is not None)
            console.print(f"  [green]✓[/] Downloaded {dl_count}/{len(scraped_ads)} media files")

            # ── Stage 3: Transcribe videos ──
            video_downloads = [
                dl for dl in downloads.values()
                if dl and dl.mime_type and dl.mime_type.startswith("video/")
            ]
            transcripts = {}
            if video_downloads:
                task = progress.add_task(
                    "[cyan]Transcribing videos...", total=len(video_downloads)
                )
                transcripts = await self.transcriber.transcribe_batch(video_downloads)
                progress.update(
                    task, completed=len(transcripts), total=len(video_downloads)
                )
                t_count = sum(1 for v in transcripts.values() if v is not None)
                console.print(
                    f"  [green]✓[/] Transcribed {t_count}/{len(video_downloads)} videos"
                )

            # Run copy quality checks on transcripts
            for ad_id, transcript in transcripts.items():
                if transcript:
                    quality = self.copy_checker.check_transcript_quality(transcript.text)
                    if not quality["passed"]:
                        logger.warning(
                            f"Low quality transcript for {ad_id}: {quality['issues']}"
                        )

            # ── Stage 4: Filter and classify ──
            task = progress.add_task("[cyan]Filtering ads...", total=len(scraped_ads))
            all_content = self.ad_filter.process_ads(
                scraped_ads, downloads, transcripts, brand
            )
            progress.update(task, completed=len(all_content), total=len(scraped_ads))

            for content in all_content:
                await self.store.save_ad_content(run_id, content)

            # Get ads that passed filtering
            analyzable = [
                c for c in all_content
                if c.status != AdStatus.FILTERED_OUT
            ]
            filtered_count = len(all_content) - len(analyzable)
            console.print(
                f"  [green]✓[/] {len(analyzable)} ads ready for analysis "
                f"({filtered_count} filtered out)"
            )

            if not analyzable:
                console.print("[red]No ads passed filtering. Aborting analysis.[/]")
                return PatternReport(
                    search_query=query,
                    brand=brand,
                    executive_summary="All ads were filtered out. No analysis possible.",
                )

            # ── Stage 5: Analyze individual ads ──
            task = progress.add_task(
                "[cyan]Analyzing ads with Claude...", total=len(analyzable)
            )
            analysis_results = await self.analyzer.analyze_batch(analyzable)
            progress.update(
                task, completed=len(analysis_results), total=len(analyzable)
            )

            analyses = [a for a in analysis_results.values() if a is not None]
            for analysis in analyses:
                await self.store.save_analysis(run_id, analysis)

            console.print(
                f"  [green]✓[/] Analyzed {len(analyses)}/{len(analyzable)} ads"
            )

            # ── Stage 6: Quality gates ──
            task = progress.add_task("[cyan]Running quality checks...", total=1)
            quality_report = self.quality_gates.run_checks(all_content, analyses)
            progress.update(task, completed=1)

            status = "[green]PASSED" if quality_report.passed else "[yellow]WARNING"
            console.print(f"  {status}[/] Quality gate: {len(quality_report.issues)} issues")
            for issue in quality_report.issues:
                if issue.startswith("CRITICAL"):
                    console.print(f"    [red]✗ {issue}[/]")
                elif issue.startswith("WARNING"):
                    console.print(f"    [yellow]! {issue}[/]")
                else:
                    console.print(f"    [dim]ℹ {issue}[/]")

            # ── Stage 7: Pattern analysis ──
            if analyses:
                task = progress.add_task("[cyan]Running pattern analysis...", total=1)
                report = await self.pattern_analyzer.analyze_patterns(
                    analyses=analyses,
                    search_query=query,
                    brand=brand,
                    quality_report=quality_report,
                )
                progress.update(task, completed=1)
                console.print(f"  [green]✓[/] Pattern analysis complete")
            else:
                report = PatternReport(
                    search_query=query,
                    brand=brand,
                    quality_report=quality_report,
                    executive_summary="No ads were successfully analyzed.",
                )

            # ── Stage 8: Save report ──
            report_path = self.reporter.save_report(report, run_id)
            console.print(f"\n[bold green]Report saved:[/] {report_path}")

            # Print stats
            stats = await self.store.get_run_stats(run_id)
            console.print(f"\n[bold]Run summary ({run_id}):[/]")
            console.print(f"  Scraped: {stats['scraped_ads']}")
            console.print(f"  Downloaded: {stats.get('content_by_status', {})}")
            console.print(f"  Analyzed: {stats['ad_analyses']}")

            return report

    async def _execute_pipeline(
        self, run_id: str, query: str, brand: str
    ) -> PatternReport:
        """Execute all pipeline stages."""

        # ── Stage 1: Scrape ──
        console.print("[cyan]Scraping Meta Ads Library...[/]")
        scraped_ads = await self.scraper.scrape(query)
        console.print(f"  [green]✓[/] Scraped {len(scraped_ads)} ads")

        for ad in scraped_ads:
            await self.store.save_scraped_ad(run_id, ad)

        if not scraped_ads:
            console.print("[red]No ads found. Aborting.[/]")
            return PatternReport(
                search_query=query,
                brand=brand,
                executive_summary="No ads found for this search query.",
            )

        # ── Stages 2-8: Download, Transcribe, Filter, Analyze, Quality, Pattern, Report ──
        return await self._execute_stages_2_to_8(
            run_id=run_id,
            scraped_ads=scraped_ads,
            query=query,
            brand=brand
        )


class BatchPipeline:
    """Run pipeline across multiple brands/queries."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        pipeline_cfg = config.get("pipeline", {})
        self.max_brands = pipeline_cfg.get("max_brands_per_batch", 15)
        self.brand_pause = pipeline_cfg.get("brand_pause", 10)

    async def run_batch(
        self,
        queries: list[dict[str, str]],
    ) -> list[PatternReport]:
        """Run pipeline for multiple brands sequentially.

        Args:
            queries: List of {"query": "...", "brand": "..."} dicts.

        Returns:
            List of PatternReport objects.
        """
        if len(queries) > self.max_brands:
            console.print(
                f"[yellow]Warning: {len(queries)} brands exceeds max "
                f"({self.max_brands}). Processing first {self.max_brands}.[/]"
            )
            queries = queries[: self.max_brands]

        reports: list[PatternReport] = []
        pipeline = Pipeline(self.config)

        for i, q in enumerate(queries):
            query = q["query"]
            brand = q.get("brand", query)

            console.print(
                f"\n[bold]═══ Brand {i + 1}/{len(queries)}: {brand} ═══[/]"
            )

            try:
                report = await pipeline.run(query=query, brand=brand)
                reports.append(report)
            except Exception as e:
                logger.error(f"Pipeline failed for {brand}: {e}")
                console.print(f"[red]Failed: {e}[/]")
                reports.append(
                    PatternReport(
                        search_query=query,
                        brand=brand,
                        executive_summary=f"Pipeline failed: {e}",
                    )
                )

            # Pause between brands to avoid rate limits
            if i < len(queries) - 1:
                console.print(
                    f"[dim]Pausing {self.brand_pause}s before next brand...[/]"
                )
                await asyncio.sleep(self.brand_pause)

            # Reset filter state between brands
            pipeline.ad_filter.reset()

        console.print(f"\n[bold green]Batch complete: {len(reports)} brands processed[/]")
        return reports
