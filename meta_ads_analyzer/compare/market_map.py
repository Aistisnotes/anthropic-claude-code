"""Market map generator - cross-brand comparison matrices and saturation analysis."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from meta_ads_analyzer.models import (
    BrandProfile,
    BrandReport,
    DimensionCoverage,
    MarketMap,
    SaturationZone,
)
from meta_ads_analyzer.compare.dimension_extractor import DimensionExtractor
from meta_ads_analyzer.compare.dimensions import (
    ALL_ANGLES,
    ALL_CTAS,
    ALL_EMOTIONS,
    ALL_FORMATS,
    ALL_HOOKS,
    ALL_OFFERS,
)
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)
console = Console()


def generate_market_map(
    brand_reports: list[BrandReport], meta: dict[str, Any]
) -> MarketMap:
    """Generate complete market map with dimension matrices and saturation analysis.

    Args:
        brand_reports: List of brand reports to compare
        meta: Metadata dict with keyword, scan_date, etc.

    Returns:
        MarketMap with matrices, saturation zones, and brand profiles
    """
    logger.info(f"Generating market map for {len(brand_reports)} brands")

    # Build matrices for all 6 dimensions
    matrices = {
        'hooks': _build_matrix(brand_reports, 'hooks', ALL_HOOKS),
        'angles': _build_matrix(brand_reports, 'angles', ALL_ANGLES),
        'emotions': _build_matrix(brand_reports, 'emotions', ALL_EMOTIONS),
        'formats': _build_matrix(brand_reports, 'formats', ALL_FORMATS),
        'offers': _build_matrix(brand_reports, 'offers', ALL_OFFERS),
        'ctas': _build_matrix(brand_reports, 'ctas', ALL_CTAS),
    }

    # Build saturation analysis
    saturation = _build_saturation_analysis(matrices, len(brand_reports))

    # Build brand profiles
    profiles = _build_brand_profiles(brand_reports)

    # Update meta with brand count
    meta['brands_compared'] = len(brand_reports)
    meta['generated_at'] = datetime.utcnow().isoformat()

    return MarketMap(
        meta=meta,
        matrices=matrices,
        saturation=saturation,
        profiles=profiles,
    )


def _build_matrix(
    brand_reports: list[BrandReport],
    dimension_name: str,
    all_values: list[str],
) -> list[DimensionCoverage]:
    """Build coverage matrix for one dimension.

    Args:
        brand_reports: List of brand reports
        dimension_name: Name of dimension (hooks, angles, etc.)
        all_values: List of all possible values for this dimension

    Returns:
        List of DimensionCoverage objects sorted by coverage_percent descending
    """
    coverages = []

    for value in all_values:
        brands = {}
        total = 0

        # Count usage across all brands
        for report in brand_reports:
            dimensions = DimensionExtractor.extract_all_dimensions(
                report.pattern_report
            )
            count = dimensions[dimension_name].get(value, 0)

            if count > 0:
                brands[report.advertiser.page_name] = count
                total += count

        # Calculate coverage
        coverage = len(brands)
        coverage_percent = round((coverage / len(brand_reports)) * 100)

        coverages.append(
            DimensionCoverage(
                dimension=value,
                brands=brands,
                coverage=coverage,
                coverage_percent=coverage_percent,
                total=total,
            )
        )

    # Sort by coverage descending
    return sorted(coverages, key=lambda c: c.coverage_percent, reverse=True)


def _build_saturation_analysis(
    matrices: dict[str, list[DimensionCoverage]], num_brands: int
) -> dict[str, SaturationZone]:
    """Build saturation zone classification for each dimension type.

    Args:
        matrices: Dict of dimension matrices
        num_brands: Total number of brands

    Returns:
        Dict mapping dimension type to SaturationZone
    """
    saturation = {}

    for dimension_type, coverages in matrices.items():
        saturated = []
        moderate = []
        whitespace = []

        for cov in coverages:
            if cov.coverage_percent >= 60:
                saturated.append(cov)
            elif cov.coverage_percent >= 30:
                moderate.append(cov)
            else:
                whitespace.append(cov)

        saturation[dimension_type] = SaturationZone(
            saturated=saturated,
            moderate=moderate,
            whitespace=whitespace,
        )

    return saturation


def _build_brand_profiles(brand_reports: list[BrandReport]) -> list[BrandProfile]:
    """Build compact brand profiles for market overview.

    Args:
        brand_reports: List of brand reports

    Returns:
        List of BrandProfile objects
    """
    profiles = []

    for report in brand_reports:
        pr = report.pattern_report
        dimensions = DimensionExtractor.extract_all_dimensions(pr)

        # Find primary (most frequent) for each dimension
        primary_hook = _get_primary(dimensions['hooks'])
        primary_angle = _get_primary(dimensions['angles'])
        primary_emotion = _get_primary(dimensions['emotions'])
        primary_format = _get_primary(dimensions['formats'])
        primary_cta = _get_primary(dimensions['ctas'])

        # Calculate diversity (number of unique values used)
        hook_diversity = len([v for v in dimensions['hooks'].values() if v > 0])
        angle_diversity = len([v for v in dimensions['angles'].values() if v > 0])

        # Determine activity level
        if report.advertiser.recent_ad_count >= 10:
            activity = "high"
        elif report.advertiser.recent_ad_count >= 5:
            activity = "medium"
        else:
            activity = "low"

        # Determine content depth
        avg_insights = len(pr.key_insights) / max(pr.total_ads_analyzed, 1)
        if avg_insights >= 5:
            content_depth = "deep"
        elif avg_insights >= 3:
            content_depth = "moderate"
        else:
            content_depth = "surface"

        profiles.append(
            BrandProfile(
                name=report.advertiser.page_name,
                activity=activity,
                primary_hook=primary_hook,
                primary_angle=primary_angle,
                primary_emotion=primary_emotion,
                primary_format=primary_format,
                primary_cta=primary_cta,
                content_depth=content_depth,
                hook_diversity=hook_diversity,
                angle_diversity=angle_diversity,
                ads_analyzed=pr.total_ads_analyzed,
            )
        )

    return profiles


def _get_primary(distribution: dict[str, int]) -> str:
    """Get primary (most frequent) value from distribution.

    Args:
        distribution: Dict mapping value to frequency

    Returns:
        Most frequent value or "—" if empty
    """
    if not distribution:
        return "—"

    max_value = max(distribution.items(), key=lambda x: x[1], default=(None, 0))
    return max_value[0] if max_value[0] else "—"


def format_market_map_text(market_map: MarketMap) -> str:
    """Format market map as Rich-formatted text for console display.

    Args:
        market_map: MarketMap to format

    Returns:
        Formatted text string
    """
    lines = []

    lines.append(f"\n[bold cyan]═══ MARKET MAP: {market_map.meta['keyword']} ═══[/bold cyan]\n")
    lines.append(f"Brands compared: {market_map.meta['brands_compared']}")
    lines.append(f"Generated: {market_map.meta['generated_at']}\n")

    # Brand profiles table
    lines.append("[bold]Brand Profiles:[/bold]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Brand", width=20)
    table.add_column("Activity", width=8)
    table.add_column("Primary Hook", width=15)
    table.add_column("Primary Angle", width=15)
    table.add_column("Hook Div", justify="right", width=8)
    table.add_column("Ads", justify="right", width=6)

    for profile in market_map.profiles:
        table.add_row(
            profile.name[:18],
            profile.activity,
            profile.primary_hook[:13],
            profile.primary_angle[:13],
            str(profile.hook_diversity),
            str(profile.ads_analyzed),
        )

    console.print(table)
    lines.append("")

    # Saturation zones summary
    lines.append("[bold]Saturation Zones:[/bold]")
    for dim_type, zone in market_map.saturation.items():
        lines.append(f"\n[cyan]{dim_type.upper()}:[/cyan]")
        lines.append(f"  Saturated (60%+): {len(zone.saturated)}")
        lines.append(f"  Moderate (30-59%): {len(zone.moderate)}")
        lines.append(f"  Whitespace (<30%): {len(zone.whitespace)}")

    return "\n".join(lines)


def save_market_map(market_map: MarketMap, output_dir: Path) -> Path:
    """Save market map to JSON file.

    Args:
        market_map: MarketMap to save
        output_dir: Output directory

    Returns:
        Path to saved file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "market_map.json"
    with open(json_path, "w") as f:
        json.dump(market_map.model_dump(mode="json"), f, indent=2, default=str)

    logger.info(f"Market map saved: {json_path}")
    return json_path
