"""CLI interface for the Meta Ads Analyzer.

Usage:
    meta-ads run "keyword or brand"           # Analyze a single brand/keyword
    meta-ads batch brands.json                # Analyze multiple brands from file
    meta-ads run "keyword" --brand "BrandX"   # Custom brand name for report
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from meta_ads_analyzer.models import MarketResult, ScanResult, SelectionResult
from meta_ads_analyzer.utils.config import load_config
from meta_ads_analyzer.utils.logging import setup_logging

app = typer.Typer(
    name="meta-ads",
    help="Extract, transcribe, and analyze Meta Ads Library ads at scale.",
    add_completion=False,
)
console = Console()


def _display_advertiser_table(advertisers: list, top: int = 25) -> None:
    """Display top N advertisers in a Rich table."""
    table = Table(title=f"Top {min(top, len(advertisers))} Advertisers")
    table.add_column("Rank", style="cyan", width=6)
    table.add_column("Advertiser", style="green")
    table.add_column("Total Ads", justify="right", style="yellow")
    table.add_column("Active", justify="right", style="blue")
    table.add_column("Recent (30d)", justify="right", style="magenta")
    table.add_column("Impressions", justify="right", style="red")
    table.add_column("Score", justify="right", style="bright_white")

    for i, adv in enumerate(advertisers[:top], 1):
        impressions_text = (
            f"{adv.total_impression_lower:,}"
            if adv.total_impression_lower > 0
            else "—"
        )
        table.add_row(
            str(i),
            adv.page_name[:40],
            str(adv.ad_count),
            str(adv.active_ad_count),
            str(adv.recent_ad_count),
            impressions_text,
            str(adv.relevance_score),
        )

    console.print(table)


def _display_selection_stats(selection: SelectionResult) -> None:
    """Display selection statistics."""
    console.print("\n[bold]═══ Selection Results ═══[/]")
    console.print(f"Total scanned: [cyan]{selection.stats.total_scanned}[/]")
    console.print(f"Selected: [green]{selection.stats.total_selected}[/]")
    console.print(f"Skipped: [red]{selection.stats.total_skipped}[/]")
    console.print(f"Duplicates removed: [yellow]{selection.stats.duplicates_removed}[/]")

    if selection.stats.by_priority:
        console.print("\n[bold]By Priority:[/]")
        for priority, count in sorted(selection.stats.by_priority.items()):
            console.print(f"  {priority}: {count}")

    if selection.stats.skip_reasons:
        console.print("\n[bold]Skip Reasons:[/]")
        for reason, count in sorted(
            selection.stats.skip_reasons.items(), key=lambda x: x[1], reverse=True
        ):
            console.print(f"  {reason}: {count}")


def _save_scan_results(
    scan_result: ScanResult, output_path: Optional[Path], query: str
) -> Path:
    """Save scan results to JSON file."""
    if output_path:
        save_path = output_path
    else:
        # Auto-generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = "".join(c if c.isalnum() else "_" for c in query)[:50]
        filename = f"scan_{safe_query}_{timestamp}.json"
        save_path = Path("output/scans") / filename

    # Ensure directory exists
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # Save JSON
    with open(save_path, "w") as f:
        json.dump(scan_result.model_dump(mode="json"), f, indent=2, default=str)

    return save_path


@app.command()
def run(
    query: str = typer.Argument(..., help="Search keyword or advertiser name"),
    brand: Optional[str] = typer.Option(None, "--brand", "-b", help="Brand name for report"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config TOML file"
    ),
    max_ads: Optional[int] = typer.Option(
        None, "--max-ads", "-n", help="Override max ads to scrape"
    ),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser headless"),
    report_format: Optional[str] = typer.Option(
        None, "--format", "-f", help="Report format: markdown, json, html"
    ),
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Log level"),
    debug: bool = typer.Option(False, "--debug", help="Save debug screenshots to output/debug/"),
):
    """Analyze ads for a single brand/keyword."""
    setup_logging(log_level)
    config = load_config(config_path)

    # Apply CLI overrides
    if max_ads is not None:
        config.setdefault("scraper", {})["max_ads"] = max_ads
    config.setdefault("scraper", {})["headless"] = headless
    if report_format:
        config.setdefault("reporting", {})["format"] = report_format
    if debug:
        config.setdefault("scraper", {})["debug"] = True

    console.print(f"\n[bold]Meta Ads Analyzer[/]")
    console.print(f"Query: [cyan]{query}[/]")
    console.print(f"Brand: [cyan]{brand or query}[/]")
    console.print(f"Max ads: [cyan]{config.get('scraper', {}).get('max_ads', 100)}[/]")
    console.print()

    from meta_ads_analyzer.pipeline import Pipeline

    pipeline = Pipeline(config)
    report = asyncio.run(pipeline.run(query=query, brand=brand))

    if report.executive_summary:
        console.print("\n[bold]Executive Summary:[/]")
        console.print(report.executive_summary)

    if report.key_insights:
        console.print("\n[bold]Key Insights:[/]")
        for i, insight in enumerate(report.key_insights, 1):
            console.print(f"  {i}. {insight}")


@app.command()
def batch(
    brands_file: Path = typer.Argument(
        ..., help="JSON file with brands list [{query, brand}, ...]"
    ),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config TOML file"
    ),
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Log level"),
):
    """Analyze multiple brands from a JSON file.

    The JSON file should contain a list of objects:
    [
        {"query": "keyword or URL", "brand": "Brand Name"},
        {"query": "another keyword", "brand": "Brand 2"},
        ...
    ]
    """
    setup_logging(log_level)
    config = load_config(config_path)

    if not brands_file.exists():
        console.print(f"[red]File not found: {brands_file}[/]")
        raise typer.Exit(1)

    with open(brands_file) as f:
        queries = json.load(f)

    if not isinstance(queries, list):
        console.print("[red]JSON file must contain a list of {query, brand} objects[/]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Meta Ads Analyzer - Batch Mode[/]")
    console.print(f"Brands: [cyan]{len(queries)}[/]")
    console.print()

    from meta_ads_analyzer.pipeline import BatchPipeline

    batch_pipeline = BatchPipeline(config)
    reports = asyncio.run(batch_pipeline.run_batch(queries))

    # Summary
    console.print("\n[bold]═══ Batch Summary ═══[/]")
    for i, (q, r) in enumerate(zip(queries, reports)):
        status = "[green]✓" if r.total_ads_analyzed > 0 else "[red]✗"
        console.print(
            f"  {status}[/] {q.get('brand', q['query'])}: "
            f"{r.total_ads_analyzed} ads analyzed"
        )


@app.command()
def scan(
    query: str = typer.Argument(..., help="Search keyword or advertiser name"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config TOML file"
    ),
    max_ads: Optional[int] = typer.Option(
        None, "--max-ads", "-n", help="Override max ads to scrape"
    ),
    country: str = typer.Option("US", "--country", help="ISO country code"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser headless"),
    select: bool = typer.Option(False, "--select", help="Run ad selection and show priority breakdown"),
    top: int = typer.Option(25, "--top", help="Show top N advertisers in table"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Save scan results to JSON file"),
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Log level"),
):
    """Scan Meta Ads Library for metadata only (no downloads or analysis)."""
    setup_logging(log_level)
    config = load_config(config_path)

    # Apply CLI overrides
    if max_ads is not None:
        config.setdefault("scraper", {})["max_ads"] = max_ads
    config.setdefault("scraper", {})["headless"] = headless
    config.setdefault("scraper", {}).setdefault("filters", {})["country"] = country

    console.print(f"\n[bold]Meta Ads Library Scan[/]")
    console.print(f"Query: [cyan]{query}[/]")
    console.print(f"Country: [cyan]{country}[/]")
    console.print()

    # Run scan
    from meta_ads_analyzer.scanner import run_scan

    scan_result = asyncio.run(run_scan(query, config))

    # Display advertiser table
    if scan_result.advertisers:
        _display_advertiser_table(scan_result.advertisers, top)
    else:
        console.print("[yellow]No advertisers found[/]")

    # Optional: run selection
    if select and scan_result.ads:
        from meta_ads_analyzer.selector import select_ads

        selection_result = select_ads(scan_result.ads, config)
        scan_result.selection = selection_result
        _display_selection_stats(selection_result)

    # Save results
    output_path = _save_scan_results(scan_result, output, query)
    console.print(f"\n[bold green]✓[/] Scan saved: {output_path}")

    # Summary
    console.print(f"\n[bold]Summary:[/]")
    console.print(f"  Total ads: {scan_result.total_fetched}")
    console.print(f"  Advertisers: {len(scan_result.advertisers)}")
    if scan_result.selection:
        console.print(
            f"  Selected for analysis: {scan_result.selection.stats.total_selected}"
        )


@app.command()
def market(
    query: str = typer.Argument(..., help="Search keyword"),
    top_brands: int = typer.Option(5, "--top-brands", help="Top N brands to analyze"),
    ads_per_brand: int = typer.Option(10, "--ads-per-brand", help="Max ads per brand"),
    from_scan: Optional[Path] = typer.Option(None, "--from-scan", help="Load from saved scan JSON"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
    country: str = typer.Option("US", "--country"),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
    log_level: str = typer.Option("INFO", "--log-level", "-l"),
):
    """Competitive market research - analyze multiple brands for a keyword."""
    setup_logging(log_level)
    config = load_config(config_path)

    # Apply overrides
    config.setdefault("scraper", {})["headless"] = headless
    config.setdefault("scraper", {}).setdefault("filters", {})["country"] = country
    if output:
        config.setdefault("reporting", {})["output_dir"] = str(output)

    console.print(f"\n[bold]Market Research: {query}[/]")
    console.print(
        f"Top brands: [cyan]{top_brands}[/]  |  Ads per brand: [cyan]{ads_per_brand}[/]"
    )

    from meta_ads_analyzer.market_pipeline import MarketPipeline

    market_pipeline = MarketPipeline(config)
    result = asyncio.run(
        market_pipeline.run(
            keyword=query,
            top_brands=top_brands,
            ads_per_brand=ads_per_brand,
            from_scan=from_scan,
        )
    )

    # Display cross-brand summary
    _display_market_summary(result)


def _display_market_summary(result: MarketResult):
    """Display cross-brand comparison table."""
    console.print(f"\n[bold green]✓[/] Market research complete")
    console.print(
        f"Analyzed {result.brands_analyzed} of {result.total_advertisers} advertisers"
    )

    if not result.brand_reports:
        console.print("[yellow]No brands analyzed[/]")
        return

    table = Table(title=f"Market Overview: {result.keyword}")
    table.add_column("Brand", style="green", width=25)
    table.add_column("Ads", justify="right", style="cyan")
    table.add_column("Top Hook", style="yellow", width=20)
    table.add_column("Top Angle", style="magenta", width=20)
    table.add_column("Primary Format", style="blue")

    for br in result.brand_reports:
        pr = br.pattern_report

        # Extract primary patterns (safely handle empty lists)
        top_hook = "—"
        if pr.hook_patterns and len(pr.hook_patterns) > 0:
            top_hook = pr.hook_patterns[0].get("pattern", "—")[:18]

        top_angle = "—"
        if pr.common_pain_points and len(pr.common_pain_points) > 0:
            top_angle = pr.common_pain_points[0].get("pain_point", "—")[:18]

        # Determine primary format (video vs static)
        video_count = sum(
            1 for insight in pr.key_insights if "video" in insight.lower()
        )
        primary_format = "Video" if video_count > pr.total_ads_analyzed // 2 else "Static"

        table.add_row(
            br.advertiser.page_name[:23],
            str(pr.total_ads_analyzed),
            top_hook,
            top_angle,
            primary_format,
        )

    console.print(table)

    # Show output directory
    keyword_slug = result.keyword.replace(" ", "_")
    console.print(
        f"\n[dim]Reports saved to: output/reports/market_{keyword_slug}_*/[/]"
    )


@app.command()
def compare(
    query: str = typer.Argument(..., help="Search keyword"),
    brand: Optional[str] = typer.Option(None, "--brand", "-b", help="Focus brand for gap analysis"),
    from_reports: Optional[Path] = typer.Option(None, "--from-reports", help="Load from custom reports directory"),
    from_scan: Optional[Path] = typer.Option(None, "--from-scan", help="Run fresh analysis from saved scan"),
    top_brands: int = typer.Option(5, "--top-brands", help="Top brands (when using --from-scan)"),
    ads_per_brand: int = typer.Option(10, "--ads-per-brand", help="Ads per brand (when using --from-scan)"),
    enhance: bool = typer.Option(False, "--enhance", help="Add Claude strategic layer"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON to stdout"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
    log_level: str = typer.Option("INFO", "--log-level", "-l"),
):
    """Compare brands - generate Market Map and Loophole Document."""
    setup_logging(log_level)
    config = load_config(config_path)

    if output:
        config.setdefault("reporting", {})["output_dir"] = str(output)

    console.print(f"\n[bold]Market Comparison: {query}[/]")
    if brand:
        console.print(f"Focus brand: [cyan]{brand}[/]")

    from meta_ads_analyzer.compare_pipeline import ComparePipeline

    pipeline = ComparePipeline(config)
    result = asyncio.run(
        pipeline.run(
            keyword=query,
            focus_brand=brand,
            from_reports=from_reports,
            from_scan=from_scan,
            enhance=enhance,
            top_brands=top_brands,
            ads_per_brand=ads_per_brand,
        )
    )

    # Display results
    if json_output:
        console.print_json(data=result.model_dump(mode="json"))
    else:
        from meta_ads_analyzer.compare.strategic_market_map import format_strategic_market_map_text
        from meta_ads_analyzer.compare.strategic_loophole_doc import format_strategic_loophole_doc_text

        console.print("\n" + format_strategic_market_map_text(result.market_map))
        if result.loophole_doc:
            console.print("\n" + format_strategic_loophole_doc_text(result.loophole_doc))

        # Summary
        if result.loophole_doc:
            high_priority = sum(
                1 for loop in result.loophole_doc.loopholes if loop.priority_score >= 80
            )
            medium_priority = sum(
                1 for loop in result.loophole_doc.loopholes if 50 <= loop.priority_score < 80
            )
            total_loopholes = len(result.loophole_doc.loopholes)

            console.print(f"\n[bold green]✓[/] Strategic comparison complete")
            console.print(f"Generated {total_loopholes} execution-ready loopholes")
            console.print(f"High priority (80+): {high_priority}, Medium priority (50-79): {medium_priority}")
        else:
            console.print(f"\n[bold green]✓[/] Strategic market map complete")


@app.command()
def install_browser():
    """Install Playwright browsers (required first-time setup)."""
    import subprocess

    console.print("[cyan]Installing Playwright Chromium browser...[/]")
    result = subprocess.run(
        ["python", "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("[green]Browser installed successfully![/]")
    else:
        console.print(f"[red]Installation failed:[/]\n{result.stderr}")


if __name__ == "__main__":
    app()
