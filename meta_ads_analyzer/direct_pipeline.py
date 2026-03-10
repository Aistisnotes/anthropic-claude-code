"""Direct brand pipeline — analyze specific brands by domain search.

Instead of running a keyword scan to discover brands, the user provides:
  - Brand name (label for report)
  - Domain, e.g. elarebeauty.com

The pipeline searches Meta Ads Library using the domain as the query, which
surfaces ALL active ads linking to that domain — including ads run by 3rd party
affiliates, influencers, and media buyers — sorted by impressions.

This captures the full competitive picture for a brand, not just its own page ads.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from meta_ads_analyzer.models import AdvertiserEntry, BrandReport, MarketResult
from meta_ads_analyzer.pipeline import Pipeline
from meta_ads_analyzer.reporter.output import ReportWriter
from meta_ads_analyzer.scraper.meta_library import MetaAdsScraper
from meta_ads_analyzer.scraper.searchapi_scraper import SearchAPIScraper, is_searchapi_available
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)
console = Console()


def parse_domain(input_str: str) -> str:
    """Normalise a brand domain input to a bare domain string.

    Accepts any of:
      elarebeauty.com
      www.elarebeauty.com
      https://elarebeauty.com
      https://www.elarebeauty.com/products/...

    Returns the bare domain (e.g. "elarebeauty.com") stripped of www / https.
    """
    s = input_str.strip()
    # Strip scheme
    s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE)
    # Strip www.
    s = re.sub(r"^www\.", "", s, flags=re.IGNORECASE)
    # Strip path / query / fragment
    s = s.split("/")[0].split("?")[0].split("#")[0]
    return s.lower().strip()


def parse_brand_entries(raw_lines: list[str]) -> list[dict[str, str]]:
    """Parse a list of raw text lines into brand entries.

    Accepted formats (one per line):
      Brand Name: elarebeauty.com
      Brand Name: https://www.elarebeauty.com
      elarebeauty.com              (brand name inferred from domain)

    Returns list of {"name": str, "domain": str} dicts.
    Lines that can't be parsed or produce an empty domain are skipped.
    """
    entries = []
    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        brand_name = None
        domain_part = line

        # Split on ": " — left side is brand name, right side is domain/URL
        if ": " in line:
            colon_idx = line.index(": ")
            candidate_name = line[:colon_idx].strip()
            candidate_domain = line[colon_idx + 2:].strip()
            if candidate_name and "." not in candidate_name:
                brand_name = candidate_name
                domain_part = candidate_domain

        domain = parse_domain(domain_part)
        if not domain or "." not in domain:
            logger.warning(f"Could not parse domain from: {line!r}")
            continue

        if not brand_name:
            # Use the domain root as the brand name (e.g. "elarebeauty")
            brand_name = domain.split(".")[0].replace("-", " ").title()

        entries.append({"name": brand_name, "domain": domain})

    return entries


class DirectPipeline:
    """Analyze specific brands by domain search — captures all advertisers for that domain."""

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
            brand_entries: List of {"name": brand_name, "domain": domain} dicts
            keyword: Research topic / report naming context (optional)
            ads_per_brand: Max ads to scrape per brand (sorted by impressions)

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
        console.print(
            f"Brands: [cyan]{len(brand_entries)}[/]  |  "
            f"Topic: [cyan]{keyword or 'direct'}[/]  |  "
            f"Ads/brand: [cyan]{ads_per_brand}[/] (sorted by impressions)"
        )
        console.print(f"Output: [dim]{market_subdir}[/]\n")

        brand_reports: list[BrandReport] = []

        for i, entry in enumerate(brand_entries, 1):
            brand_name = entry["name"]
            domain = entry["domain"]

            console.print(
                f"[bold]── Brand {i}/{len(brand_entries)}: {brand_name} ({domain}) ──[/]"
            )

            try:
                report = await self._analyze_brand(
                    brand_name=brand_name,
                    domain=domain,
                    keyword=keyword or brand_name,
                    ads_per_brand=ads_per_brand,
                    market_subdir=market_subdir,
                )
                brand_reports.append(report)
                console.print(
                    f"  [green]✓[/] {brand_name}: "
                    f"{report.pattern_report.total_ads_analyzed} ads analyzed"
                )
            except Exception as e:
                logger.error(f"Failed to analyze {brand_name}: {e}")
                console.print(f"  [red]✗ {brand_name}: {e}[/]")

        console.print(
            f"\n[bold green]Direct analysis complete:[/] "
            f"{len(brand_reports)}/{len(brand_entries)} brands"
        )
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
        domain: str,
        keyword: str,
        ads_per_brand: int,
        market_subdir: Path,
    ) -> BrandReport:
        """Search by domain and run the full analysis pipeline."""
        import copy

        scrape_cfg = copy.deepcopy(self.config)
        # Over-fetch 2x to ensure we have enough quality ads after filtering
        scrape_cfg.setdefault("scraper", {})["max_ads"] = ads_per_brand * 2

        backend = scrape_cfg.get("scraper", {}).get("backend", "searchapi")
        if backend == "searchapi" and is_searchapi_available():
            scraper = SearchAPIScraper(scrape_cfg)
        else:
            scraper = MetaAdsScraper(scrape_cfg)

        console.print(f"  [cyan]Searching ads for domain: {domain}...[/]")
        scraped_ads = await scraper.scrape(
            query=domain,
            sort_by_impressions=True,
        )
        console.print(f"  [green]✓[/] Found {len(scraped_ads)} ads across all advertisers")

        if not scraped_ads:
            from meta_ads_analyzer.models import PatternReport
            return BrandReport(
                advertiser=AdvertiserEntry(
                    page_name=brand_name,
                    ad_count=0,
                ),
                keyword=keyword,
                pattern_report=PatternReport(
                    search_query=keyword,
                    brand=brand_name,
                    executive_summary=f"No active ads found for domain: {domain}",
                ),
                generated_at=datetime.utcnow(),
            )

        # Collect unique advertiser page names found
        page_names = list(dict.fromkeys(
            ad.page_name for ad in scraped_ads if ad.page_name
        ))

        pattern_report = await self.pipeline.run_from_scraped_ads(
            scraped_ads=scraped_ads,
            query=keyword,
            brand=brand_name,
            target_analyze=ads_per_brand,
        )

        advertiser = AdvertiserEntry(
            page_name=brand_name,
            ad_count=len(scraped_ads),
            active_ad_count=len(scraped_ads),
            all_page_names=page_names[:10],
        )

        brand_report = BrandReport(
            advertiser=advertiser,
            keyword=keyword,
            pattern_report=pattern_report,
            generated_at=datetime.utcnow(),
        )

        await self.reporter.save_brand_report(brand_report, market_subdir)

        return brand_report
