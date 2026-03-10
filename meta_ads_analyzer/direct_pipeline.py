"""Direct brand pipeline — analyze specific brands by page_id without keyword discovery.

Instead of running a keyword scan to discover brands, the user provides:
  - Brand name (label for report)
  - Meta Ads Library URL or raw page_id

The pipeline scrapes each brand directly via view_all_page_id, runs the full
download → transcribe → filter → analyze → pattern analysis → report flow,
saves brand_report_*.json + PDF for each brand, and returns a MarketResult
compatible with the compare pipeline.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from rich.console import Console

from meta_ads_analyzer.models import AdvertiserEntry, BrandReport, MarketResult
from meta_ads_analyzer.pipeline import Pipeline
from meta_ads_analyzer.reporter.output import ReportWriter
from meta_ads_analyzer.scraper.meta_library import MetaAdsScraper
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)
console = Console()


def extract_page_id(input_str: str) -> Optional[str]:
    """Extract a Facebook page_id from a Meta Ads Library URL or raw numeric string.

    Accepts:
      - Full URL with view_all_page_id param
      - Raw numeric string (page_id directly)

    Returns:
      The page_id string, or None if not found.
    """
    s = input_str.strip()
    if not s:
        return None

    # Raw numeric ID
    if re.fullmatch(r"\d+", s):
        return s

    # URL containing view_all_page_id=...
    if "view_all_page_id" in s:
        try:
            qs = parse_qs(urlparse(s).query)
            ids = qs.get("view_all_page_id", [])
            if ids:
                return ids[0]
        except Exception:
            pass

    # Try extracting any long number from the URL as fallback
    m = re.search(r"view_all_page_id=(\d+)", s)
    if m:
        return m.group(1)

    return None


def parse_brand_entries(raw_lines: list[str]) -> list[dict[str, str]]:
    """Parse a list of raw text lines into brand entries.

    Accepted formats (one per line):
      Brand Name: https://www.facebook.com/ads/library/?view_all_page_id=123
      Brand Name: 123456789
      https://www.facebook.com/ads/library/?view_all_page_id=123  (brand name inferred)
      123456789  (brand name = page_id)

    Returns:
      List of {"name": str, "page_id": str} dicts (only entries with valid page_ids).
    """
    entries = []
    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        brand_name = None
        url_part = line

        # Try splitting on first colon that isn't part of https://
        # Format: "Brand Name: URL_or_id"
        if ": " in line:
            colon_idx = line.index(": ")
            candidate_name = line[:colon_idx].strip()
            candidate_url = line[colon_idx + 2:].strip()
            # Only treat left side as brand name if it doesn't look like a URL
            if "http" not in candidate_name and len(candidate_name) > 0:
                brand_name = candidate_name
                url_part = candidate_url

        page_id = extract_page_id(url_part)
        if not page_id:
            logger.warning(f"Could not extract page_id from: {line!r}")
            continue

        if not brand_name:
            brand_name = f"Brand {page_id}"

        entries.append({"name": brand_name, "page_id": page_id})

    return entries


class DirectPipeline:
    """Analyze specific brands by direct page_id without keyword discovery."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.pipeline = Pipeline(config)
        self.reporter = ReportWriter(config)

    async def run(
        self,
        brand_entries: list[dict[str, str]],
        keyword: str = "",
        ads_per_brand: int = 50,
    ) -> MarketResult:
        """Run full analysis for a list of directly-specified brands.

        Args:
            brand_entries: List of {"name": brand_name, "page_id": page_id} dicts
            keyword: Research topic / report naming context (optional)
            ads_per_brand: Max ads to scrape per brand

        Returns:
            MarketResult with brand_reports list (same structure as market pipeline)
        """
        if not brand_entries:
            return MarketResult(
                keyword=keyword or "direct",
                brand_reports=[],
                total_advertisers=0,
                brands_analyzed=0,
                competition_level="blue_ocean",
            )

        # Set up market subdir (same naming convention as market pipeline)
        output_dir = Path(
            self.config.get("reporting", {}).get("output_dir", "output/reports")
        )
        keyword_slug = re.sub(r"[^a-z0-9]+", "_", (keyword or "direct").lower()).strip("_")[:40]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        market_subdir = output_dir / f"market_{keyword_slug}_{timestamp}"
        market_subdir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[bold]Direct Brand Analysis[/]")
        console.print(f"Brands: [cyan]{len(brand_entries)}[/]  |  Topic: [cyan]{keyword or 'direct'}[/]")
        console.print(f"Output: [dim]{market_subdir}[/]\n")

        brand_reports: list[BrandReport] = []

        for i, entry in enumerate(brand_entries, 1):
            brand_name = entry["name"]
            page_id = entry["page_id"]

            console.print(f"[bold]── Brand {i}/{len(brand_entries)}: {brand_name} (page_id={page_id}) ──[/]")

            try:
                report = await self._analyze_brand(
                    brand_name=brand_name,
                    page_id=page_id,
                    keyword=keyword or brand_name,
                    ads_per_brand=ads_per_brand,
                    market_subdir=market_subdir,
                )
                brand_reports.append(report)
                console.print(f"  [green]✓[/] {brand_name}: {report.pattern_report.total_ads_analyzed} ads analyzed")
            except Exception as e:
                logger.error(f"Failed to analyze {brand_name}: {e}")
                console.print(f"  [red]✗ {brand_name}: {e}[/]")

        console.print(f"\n[bold green]Direct analysis complete:[/] {len(brand_reports)}/{len(brand_entries)} brands")
        console.print(f"Reports in: [dim]{market_subdir}[/]")

        return MarketResult(
            keyword=keyword or "direct",
            brand_reports=brand_reports,
            total_advertisers=len(brand_entries),
            brands_analyzed=len(brand_reports),
            competition_level="normal" if len(brand_reports) >= 3 else "thin",
        )

    async def _analyze_brand(
        self,
        brand_name: str,
        page_id: str,
        keyword: str,
        ads_per_brand: int,
        market_subdir: Path,
    ) -> BrandReport:
        """Scrape a brand by page_id and run the full analysis pipeline."""
        import copy

        # Build scraper config with ads_per_brand override
        scrape_cfg = copy.deepcopy(self.config)
        scrape_cfg.setdefault("scraper", {})["max_ads"] = ads_per_brand

        scraper = MetaAdsScraper(scrape_cfg)

        console.print(f"  [cyan]Scraping {brand_name} (page_id={page_id})...[/]")
        scraped_ads = await scraper.scrape(query=brand_name, page_id=page_id)
        console.print(f"  [green]✓[/] Scraped {len(scraped_ads)} ads")

        if not scraped_ads:
            # Return empty report
            from meta_ads_analyzer.models import PatternReport
            return BrandReport(
                advertiser=AdvertiserEntry(
                    page_id=page_id,
                    page_name=brand_name,
                    ad_count=0,
                ),
                keyword=keyword,
                pattern_report=PatternReport(
                    search_query=keyword,
                    brand=brand_name,
                    executive_summary=f"No ads found for {brand_name} (page_id={page_id}).",
                ),
                generated_at=datetime.utcnow(),
            )

        # Run full pipeline (download, transcribe, filter, analyze, report)
        pattern_report = await self.pipeline.run_from_scraped_ads(
            scraped_ads=scraped_ads,
            query=keyword,
            brand=brand_name,
        )

        # Build AdvertiserEntry from scraped data
        advertiser = AdvertiserEntry(
            page_id=page_id,
            page_name=brand_name,
            ad_count=len(scraped_ads),
            active_ad_count=len(scraped_ads),
            all_page_names=[brand_name],
        )

        brand_report = BrandReport(
            advertiser=advertiser,
            keyword=keyword,
            pattern_report=pattern_report,
            generated_at=datetime.utcnow(),
        )

        # Save JSON + PDF
        await self.reporter.save_brand_report(brand_report, market_subdir)

        return brand_report
