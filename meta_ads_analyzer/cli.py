"""CLI interface for the Meta Ads Analyzer.

Usage:
    meta-ads run "keyword or brand"           # Analyze a single brand/keyword
    meta-ads batch brands.json                # Analyze multiple brands from file
    meta-ads run "keyword" --brand "BrandX"   # Custom brand name for report
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from meta_ads_analyzer.utils.config import load_config
from meta_ads_analyzer.utils.logging import setup_logging

app = typer.Typer(
    name="meta-ads",
    help="Extract, transcribe, and analyze Meta Ads Library ads at scale.",
    add_completion=False,
)
console = Console()


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
