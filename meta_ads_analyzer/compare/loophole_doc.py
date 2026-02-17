"""Loophole document generator - competitive gap analysis and priority matrix."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from meta_ads_analyzer.models import (
    BrandGap,
    BrandReport,
    LoopholeDocument,
    MarketGap,
    MarketMap,
    PriorityEntry,
    UnderexploitedOpportunity,
)
from meta_ads_analyzer.compare.dimension_extractor import DimensionExtractor
from meta_ads_analyzer.compare.dimensions import DIMENSION_WEIGHTS
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)
console = Console()


def generate_loophole_doc(
    market_map: MarketMap,
    brand_reports: list[BrandReport],
    focus_brand: Optional[str] = None,
) -> LoopholeDocument:
    """Generate complete loophole document with gap analysis and priority matrix.

    Args:
        market_map: Market map with dimension matrices
        brand_reports: List of brand reports
        focus_brand: Optional focus brand name for brand-specific gap analysis

    Returns:
        LoopholeDocument with gaps, saturation, underexploited, priority matrix, brand gaps
    """
    logger.info(f"Generating loophole document for {len(brand_reports)} brands")

    # Find market-wide gaps (0% coverage)
    market_gaps = _find_market_gaps(market_map)

    # Find saturation zones (60%+ coverage)
    saturation_zones = _find_saturation_zones(market_map)

    # Find underexploited opportunities (1-2 brands, <30% coverage)
    underexploited = _find_underexploited(market_map)

    # Build priority matrix
    priority_matrix = _build_priority_matrix(market_map, underexploited)

    # Brand-specific gap analysis (if focus brand specified)
    brand_gaps = None
    if focus_brand:
        brand_gaps = _find_brand_specific_gaps(focus_brand, market_map, brand_reports)

    # Build metadata
    meta = {
        'keyword': market_map.meta.get('keyword', ''),
        'report_date': datetime.utcnow().isoformat(),
        'brands_compared': len(brand_reports),
        'focus_brand': focus_brand,
    }

    return LoopholeDocument(
        meta=meta,
        market_gaps=market_gaps,
        saturation_zones=saturation_zones,
        underexploited=underexploited,
        priority_matrix=priority_matrix,
        brand_gaps=brand_gaps,
    )


def _find_market_gaps(market_map: MarketMap) -> dict[str, list[MarketGap]]:
    """Find market-wide gaps (dimensions with 0% coverage).

    Args:
        market_map: Market map with matrices

    Returns:
        Dict mapping dimension type to list of MarketGap objects
    """
    gaps = {}

    for dim_type, coverages in market_map.matrices.items():
        dim_gaps = []
        for cov in coverages:
            if cov.coverage == 0:  # Nobody using this dimension
                dim_gaps.append(
                    MarketGap(
                        dimension=cov.dimension,
                        opportunity="wide_open",
                    )
                )
        if dim_gaps:
            gaps[dim_type] = dim_gaps

    return gaps


def _find_saturation_zones(market_map: MarketMap) -> dict[str, list[dict]]:
    """Find saturation zones (dimensions with 60%+ coverage).

    Args:
        market_map: Market map with saturation analysis

    Returns:
        Dict mapping dimension type to list of saturated dimension dicts
    """
    zones = {}

    for dim_type, saturation in market_map.saturation.items():
        if saturation.saturated:
            zones[dim_type] = [
                {
                    'dimension': cov.dimension,
                    'coverage_percent': cov.coverage_percent,
                    'brands_using': cov.coverage,
                    'total_ads': cov.total,
                    'recommendation': 'Avoid or differentiate - highly competitive zone',
                }
                for cov in saturation.saturated
            ]

    return zones


def _find_underexploited(market_map: MarketMap) -> list[UnderexploitedOpportunity]:
    """Find underexploited opportunities (1-2 brands using, <30% coverage).

    Args:
        market_map: Market map with matrices

    Returns:
        List of UnderexploitedOpportunity objects
    """
    opportunities = []

    for dim_type, coverages in market_map.matrices.items():
        for cov in coverages:
            # Underexploited: 1-2 brands using, <30% coverage
            if 1 <= cov.coverage <= 2 and cov.coverage_percent < 30:
                opportunities.append(
                    UnderexploitedOpportunity(
                        category=dim_type,
                        dimension=cov.dimension,
                        used_by=list(cov.brands.keys()),
                        coverage_percent=cov.coverage_percent,
                        total_ads=cov.total,
                    )
                )

    return opportunities


def _build_priority_matrix(
    market_map: MarketMap, underexploited: list[UnderexploitedOpportunity]
) -> list[PriorityEntry]:
    """Build priority matrix with P1/P2/P3/P4 scoring.

    Priority score formula:
        score = (gap_score + validation_bonus + low_comp_bonus) × (weight / 3)

    Where:
        gap_score = 100 - coverage_percent
        validation_bonus = 20 if total_ads > 0 (proven by someone)
        low_comp_bonus = 15 if exactly 1 brand uses it (validated but uncrowded)
        weight = dimension-specific (angles=4, hooks=3, emotions=3, formats=2, offers=2, ctas=1)

    Tier classification:
        P1_HIGH: score >= 80
        P2_MEDIUM: score >= 50
        P3_LOW: score >= 25
        P4_MONITOR: score < 25

    Args:
        market_map: Market map with coverage data
        underexploited: List of underexploited opportunities

    Returns:
        List of PriorityEntry objects sorted by priority_score descending
    """
    entries = []

    # Score all whitespace opportunities
    for dim_type, saturation in market_map.saturation.items():
        for cov in saturation.whitespace:
            priority_score, tier = _calculate_priority_score(cov, dim_type)

            entries.append(
                PriorityEntry(
                    category=dim_type,
                    dimension=cov.dimension,
                    gap_score=100 - cov.coverage_percent,
                    coverage_percent=cov.coverage_percent,
                    brands_using=cov.coverage,
                    priority_score=priority_score,
                    tier=tier,
                )
            )

    # Sort by priority score descending
    entries.sort(key=lambda e: e.priority_score, reverse=True)

    return entries


def _calculate_priority_score(cov, category: str) -> tuple[int, str]:
    """Calculate priority score and tier for a dimension.

    Args:
        cov: DimensionCoverage object
        category: Dimension category (hooks, angles, etc.)

    Returns:
        Tuple of (priority_score, tier)
    """
    gap_score = 100 - cov.coverage_percent

    # Validation bonus: 20 points if anyone has validated this
    validation_bonus = 20 if cov.total > 0 else 0

    # Low competition bonus: 15 points if exactly 1 brand uses it (2+ ads)
    low_comp_bonus = 15 if (cov.coverage == 1 and cov.total >= 2) else 0

    # Apply dimension weight
    weight = DIMENSION_WEIGHTS.get(category, 1)
    priority_score = round((gap_score + validation_bonus + low_comp_bonus) * (weight / 3))

    # Tier classification
    if priority_score >= 80:
        tier = "P1_HIGH"
    elif priority_score >= 50:
        tier = "P2_MEDIUM"
    elif priority_score >= 25:
        tier = "P3_LOW"
    else:
        tier = "P4_MONITOR"

    return priority_score, tier


def _find_brand_specific_gaps(
    focus_brand: str, market_map: MarketMap, brand_reports: list[BrandReport]
) -> list[BrandGap]:
    """Find dimensions competitors use but focus brand doesn't (blind spots).

    Args:
        focus_brand: Focus brand name
        market_map: Market map with coverage data
        brand_reports: List of all brand reports

    Returns:
        List of BrandGap objects sorted by competitor_count descending
    """
    # Find focus brand report
    focus_report = None
    for report in brand_reports:
        if report.advertiser.page_name == focus_brand:
            focus_report = report
            break

    if not focus_report:
        logger.warning(f"Focus brand '{focus_brand}' not found in reports")
        return []

    # Extract focus brand dimensions
    focus_dimensions = DimensionExtractor.extract_all_dimensions(
        focus_report.pattern_report
    )

    gaps = []

    # Check each dimension across all matrices
    for dim_type, coverages in market_map.matrices.items():
        for cov in coverages:
            # Check if focus brand uses this dimension
            focus_uses = focus_dimensions[dim_type].get(cov.dimension, 0) > 0

            # Check if competitors use it
            competitors_using = [
                brand for brand in cov.brands.keys() if brand != focus_brand
            ]

            # Gap: competitors use it, focus brand doesn't
            if not focus_uses and competitors_using:
                gaps.append(
                    BrandGap(
                        category=dim_type,
                        dimension=cov.dimension,
                        competitors_using=competitors_using,
                        competitor_count=len(competitors_using),
                    )
                )

    # Sort by competitor count descending (biggest blind spots first)
    gaps.sort(key=lambda g: g.competitor_count, reverse=True)

    return gaps


def format_loophole_doc_text(doc: LoopholeDocument) -> str:
    """Format loophole document as Rich-formatted text for console display.

    Args:
        doc: LoopholeDocument to format

    Returns:
        Formatted text string
    """
    lines = []

    lines.append(f"\n[bold cyan]═══ LOOPHOLE DOCUMENT: {doc.meta['keyword']} ═══[/bold cyan]\n")
    lines.append(f"Brands compared: {doc.meta['brands_compared']}")
    if doc.meta.get('focus_brand'):
        lines.append(f"Focus brand: [yellow]{doc.meta['focus_brand']}[/yellow]")
    lines.append("")

    # Market gaps
    if doc.market_gaps:
        lines.append("[bold red]Market-Wide Gaps (0% coverage - wide open!):[/bold red]")
        for dim_type, gaps in doc.market_gaps.items():
            lines.append(f"\n[cyan]{dim_type.upper()}:[/cyan]")
            for gap in gaps[:5]:  # Show top 5
                lines.append(f"  • {gap.dimension}")
        lines.append("")

    # Priority matrix (top 10)
    if doc.priority_matrix:
        lines.append("[bold green]Top Opportunities (Priority Matrix):[/bold green]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Tier", width=10)
        table.add_column("Dimension", width=20)
        table.add_column("Category", width=12)
        table.add_column("Coverage", justify="right", width=8)
        table.add_column("Score", justify="right", width=6)

        for entry in doc.priority_matrix[:10]:
            tier_color = {
                "P1_HIGH": "red",
                "P2_MEDIUM": "yellow",
                "P3_LOW": "blue",
                "P4_MONITOR": "dim",
            }.get(entry.tier, "white")

            table.add_row(
                f"[{tier_color}]{entry.tier}[/{tier_color}]",
                entry.dimension[:18],
                entry.category,
                f"{entry.coverage_percent}%",
                str(entry.priority_score),
            )

        console.print(table)
        lines.append("")

    # Brand-specific gaps
    if doc.brand_gaps:
        lines.append(
            f"[bold yellow]Blind Spots for {doc.meta['focus_brand']} ({len(doc.brand_gaps)} total):[/bold yellow]"
        )
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Category", width=12)
        table.add_column("Dimension", width=20)
        table.add_column("Competitors Using", justify="right", width=15)

        for gap in doc.brand_gaps[:10]:  # Show top 10
            table.add_row(
                gap.category,
                gap.dimension[:18],
                str(gap.competitor_count),
            )

        console.print(table)
        lines.append("")

    # Saturation zones warning
    if doc.saturation_zones:
        total_saturated = sum(len(zones) for zones in doc.saturation_zones.values())
        lines.append(
            f"[bold red]⚠ Saturation Warning:[/bold red] {total_saturated} dimensions are 60%+ saturated"
        )
        lines.append("  [dim](Avoid or differentiate - highly competitive zones)[/dim]")

    return "\n".join(lines)


def save_loophole_doc(doc: LoopholeDocument, output_dir: Path) -> Path:
    """Save loophole document to JSON file.

    Args:
        doc: LoopholeDocument to save
        output_dir: Output directory

    Returns:
        Path to saved file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "loophole_doc.json"
    with open(json_path, "w") as f:
        json.dump(doc.model_dump(mode="json"), f, indent=2, default=str)

    logger.info(f"Loophole document saved: {json_path}")
    return json_path
