"""Strategic market map generator - DR-focused cross-brand comparison.

Analyzes 6 strategic dimensions across brands:
1. Root Causes
2. Mechanisms
3. Target Audiences
4. Pain Points
5. Symptoms
6. Mass Desires

For each dimension, identifies top 3 patterns with frequency, brands, and examples.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.table import Table

from meta_ads_analyzer.compare.strategic_dimensions import (
    DimensionComparison,
    MarketSophisticationLevel,
    StrategicMarketMap,
)
from meta_ads_analyzer.compare.strategic_extractor import extract_strategic_dimensions
from meta_ads_analyzer.models import BrandReport
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)
console = Console()


async def generate_strategic_market_map(
    brand_reports: list[BrandReport],
    meta: dict[str, Any],
    focus_brand: Optional[str],
    config: dict[str, Any],
) -> StrategicMarketMap:
    """Generate strategic market map with 6-dimension DR analysis.

    Args:
        brand_reports: List of brand reports
        meta: Metadata dict with keyword, scan_date
        focus_brand: Optional focus brand for loophole identification
        config: Config dict with API settings

    Returns:
        StrategicMarketMap with dimension comparisons and sophistication assessment
    """
    logger.info(
        f"Generating strategic market map for {len(brand_reports)} brands")

    # Extract strategic dimensions for each brand
    brand_dimensions = {}
    for report in brand_reports:
        dims = await extract_strategic_dimensions(report, config)
        brand_dimensions[report.advertiser.page_name] = dims

    # Assess market sophistication
    sophistication = await _assess_market_sophistication(
        brand_dimensions, brand_reports, config
    )

    # Build 6 dimension comparisons
    root_cause_comp = _compare_root_causes(brand_dimensions, focus_brand)
    mechanism_comp = _compare_mechanisms(brand_dimensions, focus_brand)
    audience_comp = _compare_audiences(brand_dimensions, focus_brand)
    pain_point_comp = _compare_pain_points(brand_dimensions, focus_brand)
    symptom_comp = _compare_symptoms(brand_dimensions, focus_brand)
    desire_comp = _compare_desires(brand_dimensions, focus_brand)

    # Build brand summaries
    brand_summaries = _build_brand_summaries(brand_reports, brand_dimensions)

    # Build Root Cause x Mechanism matrix
    rc_mech_matrix = _build_root_cause_mechanism_matrix(brand_reports, brand_dimensions)

    # Update meta
    meta["brands_compared"] = len(brand_reports)
    meta["generated_at"] = datetime.utcnow().isoformat()
    meta["focus_brand"] = focus_brand

    return StrategicMarketMap(
        meta=meta,
        sophistication_level=sophistication,
        root_cause_comparison=root_cause_comp,
        mechanism_comparison=mechanism_comp,
        audience_comparison=audience_comp,
        pain_point_comparison=pain_point_comp,
        symptom_comparison=symptom_comp,
        desire_comparison=desire_comp,
        brand_summaries=brand_summaries,
        root_cause_mechanism_matrix=rc_mech_matrix,
    )


def _compare_root_causes(
    brand_dimensions: dict, focus_brand: Optional[str]
) -> DimensionComparison:
    """Compare root cause patterns across brands."""
    # Aggregate all root causes across brands
    all_causes = []
    for brand_name, dims in brand_dimensions.items():
        for rc in dims.root_causes:
            all_causes.append(
                {
                    "text": rc.text,
                    "depth_level": rc.depth_level,
                    "upstream_gap": rc.upstream_gap,
                    "frequency": rc.frequency,
                    "brand": brand_name,
                    "example": rc.example_ad_copy,
                    "psychological_principle": rc.psychological_principle,
                }
            )

    # Group by similar text and count
    pattern_groups = defaultdict(list)
    for cause in all_causes:
        # Simple grouping by first 50 chars (could be improved with embedding similarity)
        key = cause["text"][:50].lower()
        pattern_groups[key].append(cause)

    # Rank by total frequency
    ranked_patterns = []
    for group in pattern_groups.values():
        total_freq = sum(c["frequency"] for c in group)
        brands_using = list(set(c["brand"] for c in group))
        representative = group[0]  # Use first as representative

        ranked_patterns.append(
            {
                "text": representative["text"],
                "depth_level": representative["depth_level"],
                "upstream_gap": representative["upstream_gap"],
                "frequency": total_freq,
                "brands_using": brands_using,
                "example": representative["example"],
                "psychological_principle": representative["psychological_principle"],
            }
        )

    # Sort by frequency descending
    ranked_patterns.sort(key=lambda p: p["frequency"], reverse=True)

    # Extract top 3
    pattern_1 = ranked_patterns[0] if len(ranked_patterns) > 0 else {}
    pattern_2 = ranked_patterns[1] if len(ranked_patterns) > 1 else {}
    pattern_3 = ranked_patterns[2] if len(ranked_patterns) > 2 else {}

    # Analyze differences
    differences = _analyze_root_cause_differences(ranked_patterns)

    # Identify loopholes
    loopholes = _identify_root_cause_loopholes(
        ranked_patterns, brand_dimensions, focus_brand
    )

    return DimensionComparison(
        dimension_type="root_causes",
        pattern_1=pattern_1,
        pattern_2=pattern_2,
        pattern_3=pattern_3,
        how_patterns_differ=differences,
        loopholes=loopholes,
    )


def _compare_mechanisms(
    brand_dimensions: dict, focus_brand: Optional[str]
) -> DimensionComparison:
    """Compare mechanism patterns across brands."""
    all_mechanisms = []
    for brand_name, dims in brand_dimensions.items():
        for mech in dims.mechanisms:
            all_mechanisms.append(
                {
                    "text": mech.text,
                    "mechanism_type": mech.mechanism_type,
                    "depth": mech.depth,
                    "frequency": mech.frequency,
                    "brand": brand_name,
                    "example": mech.example_ad_copy,
                    "believability_score": mech.believability_score,
                    "connects_to_root_cause": mech.connects_to_root_cause,
                }
            )

    # Group and rank
    pattern_groups = defaultdict(list)
    for mech in all_mechanisms:
        key = mech["text"][:50].lower()
        pattern_groups[key].append(mech)

    ranked_patterns = []
    for group in pattern_groups.values():
        total_freq = sum(m["frequency"] for m in group)
        brands_using = list(set(m["brand"] for m in group))
        representative = group[0]

        ranked_patterns.append(
            {
                "text": representative["text"],
                "mechanism_type": representative["mechanism_type"],
                "depth": representative["depth"],
                "frequency": total_freq,
                "brands_using": brands_using,
                "example": representative["example"],
                "believability_score": representative["believability_score"],
                "connects_to_root_cause": representative["connects_to_root_cause"],
            }
        )

    ranked_patterns.sort(key=lambda p: p["frequency"], reverse=True)

    pattern_1 = ranked_patterns[0] if ranked_patterns else {}
    pattern_2 = ranked_patterns[1] if len(ranked_patterns) > 1 else {}
    pattern_3 = ranked_patterns[2] if len(ranked_patterns) > 2 else {}

    differences = _analyze_mechanism_differences(ranked_patterns)
    loopholes = _identify_mechanism_loopholes(
        ranked_patterns, brand_dimensions, focus_brand
    )

    return DimensionComparison(
        dimension_type="mechanisms",
        pattern_1=pattern_1,
        pattern_2=pattern_2,
        pattern_3=pattern_3,
        how_patterns_differ=differences,
        loopholes=loopholes,
    )


def _compare_audiences(
    brand_dimensions: dict, focus_brand: Optional[str]
) -> DimensionComparison:
    """Compare target audience patterns across brands."""
    all_audiences = []
    for brand_name, dims in brand_dimensions.items():
        for aud in dims.target_audiences:
            all_audiences.append(
                {
                    "demographics": aud.demographics,
                    "psychographics": aud.psychographics,
                    "identity": aud.identity,
                    "frequency": aud.frequency,
                    "brand": brand_name,
                    "example": aud.example_ad_copy,
                }
            )

    # Group by identity (most distinctive element)
    pattern_groups = defaultdict(list)
    for aud in all_audiences:
        key = aud["identity"][:30].lower() if aud["identity"] else "generic"
        pattern_groups[key].append(aud)

    ranked_patterns = []
    for group in pattern_groups.values():
        total_freq = sum(a["frequency"] for a in group)
        brands_using = list(set(a["brand"] for a in group))
        representative = group[0]

        ranked_patterns.append(
            {
                "demographics": representative["demographics"],
                "psychographics": representative["psychographics"],
                "identity": representative["identity"],
                "frequency": total_freq,
                "brands_using": brands_using,
                "example": representative["example"],
            }
        )

    ranked_patterns.sort(key=lambda p: p["frequency"], reverse=True)

    pattern_1 = ranked_patterns[0] if ranked_patterns else {}
    pattern_2 = ranked_patterns[1] if len(ranked_patterns) > 1 else {}
    pattern_3 = ranked_patterns[2] if len(ranked_patterns) > 2 else {}

    differences = _analyze_audience_differences(ranked_patterns)
    loopholes = _identify_audience_loopholes(
        ranked_patterns, brand_dimensions, focus_brand
    )

    return DimensionComparison(
        dimension_type="target_audiences",
        pattern_1=pattern_1,
        pattern_2=pattern_2,
        pattern_3=pattern_3,
        how_patterns_differ=differences,
        loopholes=loopholes,
    )


def _compare_pain_points(
    brand_dimensions: dict, focus_brand: Optional[str]
) -> DimensionComparison:
    """Compare pain point patterns across brands."""
    all_pain_points = []
    for brand_name, dims in brand_dimensions.items():
        for pp in dims.pain_points:
            all_pain_points.append(
                {
                    "pain_point": pp.pain_point,
                    "intensity": pp.intensity,
                    "frequency": pp.frequency,
                    "brand": brand_name,
                    "example": pp.example_ad_copy,
                    "emotional_trigger": pp.emotional_trigger,
                }
            )

    # Group by pain point text
    pattern_groups = defaultdict(list)
    for pp in all_pain_points:
        key = pp["pain_point"][:40].lower()
        pattern_groups[key].append(pp)

    ranked_patterns = []
    for group in pattern_groups.values():
        total_freq = sum(p["frequency"] for p in group)
        brands_using = list(set(p["brand"] for p in group))
        representative = group[0]

        ranked_patterns.append(
            {
                "pain_point": representative["pain_point"],
                "intensity": representative["intensity"],
                "frequency": total_freq,
                "brands_using": brands_using,
                "example": representative["example"],
                "emotional_trigger": representative["emotional_trigger"],
            }
        )

    ranked_patterns.sort(key=lambda p: p["frequency"], reverse=True)

    pattern_1 = ranked_patterns[0] if ranked_patterns else {}
    pattern_2 = ranked_patterns[1] if len(ranked_patterns) > 1 else {}
    pattern_3 = ranked_patterns[2] if len(ranked_patterns) > 2 else {}

    differences = "Top pain points by frequency. Intensity and emotional triggers vary by brand positioning."
    loopholes = _identify_pain_point_loopholes(
        ranked_patterns, brand_dimensions, focus_brand
    )

    return DimensionComparison(
        dimension_type="pain_points",
        pattern_1=pattern_1,
        pattern_2=pattern_2,
        pattern_3=pattern_3,
        how_patterns_differ=differences,
        loopholes=loopholes,
    )


def _compare_symptoms(
    brand_dimensions: dict, focus_brand: Optional[str]
) -> DimensionComparison:
    """Compare symptom patterns across brands."""
    all_symptoms = []
    for brand_name, dims in brand_dimensions.items():
        for sym in dims.symptoms:
            all_symptoms.append(
                {
                    "symptom": sym.symptom,
                    "frequency": sym.frequency,
                    "brand": brand_name,
                    "example": sym.example_ad_copy,
                }
            )

    # Group by symptom text
    pattern_groups = defaultdict(list)
    for sym in all_symptoms:
        key = sym["symptom"][:40].lower()
        pattern_groups[key].append(sym)

    ranked_patterns = []
    for group in pattern_groups.values():
        total_freq = sum(s["frequency"] for s in group)
        brands_using = list(set(s["brand"] for s in group))
        representative = group[0]

        ranked_patterns.append(
            {
                "symptom": representative["symptom"],
                "frequency": total_freq,
                "brands_using": brands_using,
                "example": representative["example"],
            }
        )

    ranked_patterns.sort(key=lambda p: p["frequency"], reverse=True)

    pattern_1 = ranked_patterns[0] if ranked_patterns else {}
    pattern_2 = ranked_patterns[1] if len(ranked_patterns) > 1 else {}
    pattern_3 = ranked_patterns[2] if len(ranked_patterns) > 2 else {}

    differences = (
        "Symptoms ranked by frequency. More specific symptoms signal deeper understanding of lived experience."
    )
    loopholes = _identify_symptom_loopholes(
        ranked_patterns, brand_dimensions, focus_brand
    )

    return DimensionComparison(
        dimension_type="symptoms",
        pattern_1=pattern_1,
        pattern_2=pattern_2,
        pattern_3=pattern_3,
        how_patterns_differ=differences,
        loopholes=loopholes,
    )


def _compare_desires(
    brand_dimensions: dict, focus_brand: Optional[str]
) -> DimensionComparison:
    """Compare mass desire patterns across brands."""
    all_desires = []
    for brand_name, dims in brand_dimensions.items():
        for des in dims.mass_desires:
            all_desires.append(
                {
                    "desire": des.desire,
                    "timeframe": des.timeframe,
                    "specificity": des.specificity,
                    "frequency": des.frequency,
                    "brand": brand_name,
                    "example": des.example_ad_copy,
                }
            )

    # Group by desire text
    pattern_groups = defaultdict(list)
    for des in all_desires:
        key = des["desire"][:40].lower()
        pattern_groups[key].append(des)

    ranked_patterns = []
    for group in pattern_groups.values():
        total_freq = sum(d["frequency"] for d in group)
        brands_using = list(set(d["brand"] for d in group))
        representative = group[0]

        ranked_patterns.append(
            {
                "desire": representative["desire"],
                "timeframe": representative["timeframe"],
                "specificity": representative["specificity"],
                "frequency": total_freq,
                "brands_using": brands_using,
                "example": representative["example"],
            }
        )

    ranked_patterns.sort(key=lambda p: p["frequency"], reverse=True)

    pattern_1 = ranked_patterns[0] if ranked_patterns else {}
    pattern_2 = ranked_patterns[1] if len(ranked_patterns) > 1 else {}
    pattern_3 = ranked_patterns[2] if len(ranked_patterns) > 2 else {}

    differences = _analyze_desire_differences(ranked_patterns)
    loopholes = _identify_desire_loopholes(
        ranked_patterns, brand_dimensions, focus_brand
    )

    return DimensionComparison(
        dimension_type="mass_desires",
        pattern_1=pattern_1,
        pattern_2=pattern_2,
        pattern_3=pattern_3,
        how_patterns_differ=differences,
        loopholes=loopholes,
    )


def _analyze_root_cause_differences(patterns: list[dict]) -> str:
    """Analyze how root cause patterns differ across brands."""
    if not patterns:
        return "No root cause patterns found."

    depth_counter = Counter(p["depth_level"] for p in patterns)
    most_common_depth = depth_counter.most_common(1)[0][0] if depth_counter else "unknown"

    has_upstream = any(p.get("upstream_gap") for p in patterns)

    return (
        f"Most brands explain root causes at {most_common_depth} depth level. "
        f"{'Some brands identify upstream triggers, but gaps remain.' if has_upstream else 'No brands identify upstream triggers (major gap).'}"
    )


def _analyze_mechanism_differences(patterns: list[dict]) -> str:
    """Analyze how mechanism patterns differ across brands."""
    if not patterns:
        return "No mechanism patterns found."

    type_counter = Counter(p["mechanism_type"] for p in patterns)
    depth_counter = Counter(p["depth"] for p in patterns)

    return (
        f"Mechanism types: {dict(type_counter)}. "
        f"Depth distribution: {dict(depth_counter)}. "
        "Brands using molecular/cellular explanations have higher believability."
    )


def _analyze_audience_differences(patterns: list[dict]) -> str:
    """Analyze how audience patterns differ across brands."""
    if not patterns:
        return "No audience patterns found."

    has_identity = sum(1 for p in patterns if p.get("identity"))
    total = len(patterns)

    return (
        f"{has_identity}/{total} audience patterns have clear identity positioning. "
        f"{'Strong identity differentiation across brands.' if has_identity > total/2 else 'Weak identity positioning - opportunity for tribal branding.'}"
    )


def _analyze_desire_differences(patterns: list[dict]) -> str:
    """Analyze how desire patterns differ across brands."""
    if not patterns:
        return "No desire patterns found."

    specificity_counter = Counter(p["specificity"] for p in patterns)

    has_timeframe = sum(1 for p in patterns if p.get("timeframe"))

    return (
        f"Specificity distribution: {dict(specificity_counter)}. "
        f"{has_timeframe}/{len(patterns)} include timeframes. "
        "More specific, measurable promises with timeframes increase credibility."
    )


def _identify_root_cause_loopholes(
    patterns: list[dict], brand_dimensions: dict, focus_brand: Optional[str]
) -> list[str]:
    """Identify root cause loopholes for focus brand."""
    loopholes = []

    # Check for upstream gaps
    has_upstream = any(p.get("upstream_gap") for p in patterns)
    if not has_upstream:
        loopholes.append(
            "UPSTREAM GAP: No brand explains what CAUSES their stated root cause. Opportunity to go deeper."
        )

    # Check depth levels
    depth_levels = [p.get("depth_level", "surface") for p in patterns]
    if "molecular" not in depth_levels and "cellular" not in depth_levels:
        loopholes.append(
            "DEPTH GAP: No brand reaches cellular/molecular depth. Opportunity for scientific authority."
        )

    # Focus brand specific
    if focus_brand and focus_brand in brand_dimensions:
        focus_causes = brand_dimensions[focus_brand].root_causes
        if not focus_causes:
            loopholes.append(
                f"FOCUS BRAND GAP: {focus_brand} lacks clear root cause explanation entirely."
            )

    return loopholes


def _identify_mechanism_loopholes(
    patterns: list[dict], brand_dimensions: dict, focus_brand: Optional[str]
) -> list[str]:
    """Identify mechanism loopholes for focus brand."""
    loopholes = []

    # Check mechanism types
    types = [p.get("mechanism_type") for p in patterns]
    if "new_mechanism" not in types:
        loopholes.append(
            "NEW MECHANISM GAP: No brand introduces truly novel delivery/technology. Stage 3 opportunity."
        )

    # Check believability
    avg_believability = (
        sum(p.get("believability_score", 0) for p in patterns) / len(patterns)
        if patterns
        else 0
    )
    if avg_believability < 0.7:
        loopholes.append(
            f"CREDIBILITY GAP: Average believability score {avg_believability:.2f}. Mechanisms feel unproven."
        )

    return loopholes


def _identify_audience_loopholes(
    patterns: list[dict], brand_dimensions: dict, focus_brand: Optional[str]
) -> list[str]:
    """Identify audience loopholes for focus brand."""
    loopholes = []

    # Check identity strength
    has_identity = sum(1 for p in patterns if p.get("identity"))
    if has_identity < len(patterns) / 2:
        loopholes.append(
            "IDENTITY GAP: Weak tribal positioning. Opportunity for Stage 5 identity-driven branding."
        )

    return loopholes


def _identify_pain_point_loopholes(
    patterns: list[dict], brand_dimensions: dict, focus_brand: Optional[str]
) -> list[str]:
    """Identify pain point loopholes for focus brand."""
    loopholes = []

    # Check intensity distribution
    intensities = [p.get("intensity") for p in patterns]
    if "extreme" not in intensities:
        loopholes.append(
            "INTENSITY GAP: No brand agitates extreme-level pain. Opportunity for deeper emotional connection."
        )

    return loopholes


def _identify_symptom_loopholes(
    patterns: list[dict], brand_dimensions: dict, focus_brand: Optional[str]
) -> list[str]:
    """Identify symptom loopholes for focus brand."""
    loopholes = []

    if len(patterns) < 3:
        loopholes.append(
            "SYMPTOM GAP: Limited symptom vocabulary. Opportunity to reference more specific daily experiences."
        )

    return loopholes


def _identify_desire_loopholes(
    patterns: list[dict], brand_dimensions: dict, focus_brand: Optional[str]
) -> list[str]:
    """Identify desire loopholes for focus brand."""
    loopholes = []

    # Check specificity
    specificities = [p.get("specificity") for p in patterns]
    if "measurable" not in specificities:
        loopholes.append(
            "SPECIFICITY GAP: No brand makes measurable transformation promises. Opportunity for concrete outcomes."
        )

    # Check timeframes
    has_timeframe = sum(1 for p in patterns if p.get("timeframe"))
    if has_timeframe < len(patterns) / 2:
        loopholes.append(
            "TIMEFRAME GAP: Most brands avoid specific timeframes. Opportunity for bold timeline commitments."
        )

    return loopholes


async def _assess_market_sophistication(
    brand_dimensions: dict, brand_reports: list[BrandReport], config: dict
) -> MarketSophisticationLevel:
    """Assess market sophistication level using Eugene Schwartz framework."""
    # Count mechanism types
    mechanism_types = []
    for dims in brand_dimensions.values():
        for mech in dims.mechanisms:
            mechanism_types.append(mech.mechanism_type)

    type_counter = Counter(mechanism_types)

    # Heuristic: Determine stage based on mechanism distribution
    if not mechanism_types:
        stage = 1
        stage_name = "Stage 1 - First to Market"
        evidence = "No clear mechanisms detected - pioneering phase."
        strategic_response = "new_mechanism"
    elif type_counter.get("new_mechanism", 0) > len(mechanism_types) / 2:
        stage = 3
        stage_name = "Stage 3 - Market Saturation"
        evidence = "Multiple brands claim new mechanisms - introducing HOW products work differently."
        strategic_response = "new_mechanism"
    elif type_counter.get("new_information", 0) > len(mechanism_types) / 3:
        stage = 4
        stage_name = "Stage 4 - Mechanism Competition"
        evidence = "Brands compete through education and mechanism elaboration."
        strategic_response = "new_information"
    else:
        stage = 5
        stage_name = "Stage 5 - Complete Sophistication"
        evidence = (
            "Customers resist claims - only emotional connection and identity drive decisions."
        )
        strategic_response = "new_identity"

    response_rationale = (
        f"At {stage_name}, {strategic_response.replace('_', ' ')} is the most effective strategic response."
    )

    return MarketSophisticationLevel(
        stage=stage,
        stage_name=stage_name,
        evidence=evidence,
        strategic_response=strategic_response,
        response_rationale=response_rationale,
    )


def _build_brand_summaries(
    brand_reports: list[BrandReport], brand_dimensions: dict
) -> list[dict]:
    """Build compact brand summaries for market overview."""
    summaries = []

    for report in brand_reports:
        name = report.advertiser.page_name
        dims = brand_dimensions.get(name)

        if not dims:
            continue

        # Extract primary patterns
        primary_root_cause = dims.root_causes[0].text if dims.root_causes else "—"
        primary_mechanism = dims.mechanisms[0].text if dims.mechanisms else "—"
        primary_pain_point = dims.pain_points[0].pain_point if dims.pain_points else "—"
        primary_desire = dims.mass_desires[0].desire if dims.mass_desires else "—"

        summaries.append(
            {
                "brand": name,
                "ads_analyzed": report.pattern_report.total_ads_analyzed,
                "primary_root_cause": primary_root_cause[:60],
                "primary_mechanism": primary_mechanism[:60],
                "primary_pain_point": primary_pain_point[:40],
                "primary_desire": primary_desire[:50],
            }
        )

    return summaries


def _build_root_cause_mechanism_matrix(
    brand_reports: list[BrandReport], brand_dimensions: dict
) -> list[dict]:
    """Build market-wide Root Cause x Mechanism matrix.

    Shows which root cause + mechanism combinations are used by which brands.
    Makes it easy to spot saturated, underexploited, and missing combos.
    """
    from collections import defaultdict

    # Collect all root cause + mechanism pairs from all brands' ads
    matrix_data = defaultdict(lambda: {"brands": set(), "total_ads": 0})

    for report in brand_reports:
        brand_name = report.advertiser.page_name

        # Get root causes and mechanisms from the brand's pattern report
        pr = report.pattern_report

        # Extract from root_cause_patterns and mechanism_patterns
        root_causes = [
            rc.get("pattern", "none stated") for rc in pr.root_cause_patterns
        ]
        mechanisms = [m.get("pattern", "none stated") for m in pr.mechanism_patterns]

        # Create combinations
        if not root_causes:
            root_causes = ["none stated"]
        if not mechanisms:
            mechanisms = ["none stated"]

        for root in root_causes:
            for mech in mechanisms:
                # Clean and truncate
                root_clean = root[:60].strip()
                mech_clean = mech[:60].strip()

                key = (root_clean, mech_clean)
                matrix_data[key]["brands"].add(brand_name)
                matrix_data[key]["total_ads"] += 1
                matrix_data[key]["root_cause"] = root_clean
                matrix_data[key]["mechanism"] = mech_clean

    # Convert to list and calculate market share
    total_brands = len(brand_reports)
    total_ads = sum(r.pattern_report.total_ads_analyzed for r in brand_reports)

    matrix_rows = []
    for combo_data in matrix_data.values():
        brands_using = list(combo_data["brands"])
        num_brands = len(brands_using)
        market_share = round((num_brands / total_brands) * 100) if total_brands > 0 else 0

        # Classify as gap
        if market_share >= 60:
            gap = "SATURATED"
        elif market_share >= 30:
            gap = "MODERATE"
        elif market_share > 0:
            gap = "Underexploited"
        else:
            gap = "WIDE OPEN"

        matrix_rows.append(
            {
                "root_cause": combo_data["root_cause"],
                "mechanism": combo_data["mechanism"],
                "brands_using": brands_using,
                "num_brands": num_brands,
                "total_ads": combo_data["total_ads"],
                "market_share": market_share,
                "gap": gap,
            }
        )

    # Sort by market share descending (saturated first)
    matrix_rows.sort(key=lambda x: x["market_share"], reverse=True)

    return matrix_rows


def save_strategic_market_map(market_map: StrategicMarketMap, output_dir: Path) -> Path:
    """Save strategic market map to JSON file.

    Args:
        market_map: StrategicMarketMap to save
        output_dir: Output directory

    Returns:
        Path to saved file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "strategic_market_map.json"
    with open(json_path, "w") as f:
        json.dump(market_map.model_dump(mode="json"), f, indent=2, default=str)

    logger.info(f"Strategic market map saved: {json_path}")
    return json_path


def format_strategic_market_map_text(market_map: StrategicMarketMap) -> str:
    """Format strategic market map for console display.

    Args:
        market_map: StrategicMarketMap to format

    Returns:
        Formatted text string
    """
    lines = []

    lines.append(
        f"\n[bold cyan]═══ STRATEGIC MARKET MAP: {market_map.meta['keyword']} ═══[/bold cyan]\n"
    )
    lines.append(f"Brands compared: {market_map.meta['brands_compared']}")
    lines.append(f"Generated: {market_map.meta['generated_at']}\n")

    # Sophistication assessment
    soph = market_map.sophistication_level
    lines.append(f"[bold yellow]Market Sophistication: {soph.stage_name}[/bold yellow]")
    lines.append(f"Evidence: {soph.evidence}")
    lines.append(f"Strategic Response: [green]{soph.strategic_response}[/green]")
    lines.append(f"{soph.response_rationale}\n")

    # Brand summaries table
    if market_map.brand_summaries:
        lines.append("[bold]Brand Summaries:[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Brand", width=20)
        table.add_column("Ads", justify="right", width=5)
        table.add_column("Primary Root Cause", width=30)
        table.add_column("Primary Mechanism", width=30)

        for summary in market_map.brand_summaries:
            table.add_row(
                summary["brand"][:18],
                str(summary["ads_analyzed"]),
                summary["primary_root_cause"][:28],
                summary["primary_mechanism"][:28],
            )

        console.print(table)
        lines.append("")

    # Root Cause x Mechanism Matrix
    if market_map.root_cause_mechanism_matrix:
        lines.append("[bold]Root Cause × Mechanism Matrix:[/bold]")
        lines.append("(Shows which combos are saturated, underexploited, or wide open)")
        lines.append("")

        matrix_table = Table(show_header=True, header_style="bold magenta")
        matrix_table.add_column("Root Cause", width=28)
        matrix_table.add_column("Mechanism", width=28)
        matrix_table.add_column("Brands", justify="center", width=8)
        matrix_table.add_column("Share", justify="right", width=7)
        matrix_table.add_column("Status", width=15)

        # Show top 10 rows
        for row in market_map.root_cause_mechanism_matrix[:10]:
            status_color = {
                "SATURATED": "red",
                "MODERATE": "yellow",
                "Underexploited": "green",
                "WIDE OPEN": "cyan",
            }.get(row["gap"], "white")

            matrix_table.add_row(
                row["root_cause"][:26],
                row["mechanism"][:26],
                f"{row['num_brands']}/{len(market_map.brand_summaries)}",
                f"{row['market_share']}%",
                f"[{status_color}]{row['gap']}[/{status_color}]",
            )

        console.print(matrix_table)
        lines.append("")

    return "\n".join(lines)
