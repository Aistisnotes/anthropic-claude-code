"""Creative Feedback Loop pipeline — orchestrates the full analysis.

Flow:
1. Load & aggregate CSV (FIX 1)
2. Optionally filter by date range within CSV (FIX 4)
3. Classify winners/losers with separate thresholds (FIX 2, FIX 3)
4. Match to ClickUp tasks
5. Build Top 50 section (FIX 5)
6. Run pattern analysis with novelty filter (FIX 6)
7. Log aggregation stats (FIX 7)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from creative_feedback_loop.csv_aggregator import AggregatedAd, load_and_aggregate_csv
from creative_feedback_loop.classifier import ClassifiedAd, ThresholdConfig, classify_ads
from creative_feedback_loop.clickup_matcher import (
    ClickUpTask,
    MatchedAd,
    match_ads_to_clickup,
)
from creative_feedback_loop.top50 import Top50Ad, build_top50
from creative_feedback_loop.novelty_filter import NoveltyResult, compute_novelty

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Full result of the creative feedback loop pipeline."""
    # Aggregation stats (FIX 7)
    raw_rows: int = 0
    unique_ads: int = 0
    total_csv_spend: float = 0.0

    # Classification counts
    winner_count: int = 0
    loser_count: int = 0
    untested_count: int = 0
    above_spend_threshold: int = 0

    # Results
    classified_ads: list[ClassifiedAd] = field(default_factory=list)
    matched_ads: list[MatchedAd] = field(default_factory=list)
    top50: list[Top50Ad] = field(default_factory=list)

    # Pattern analysis
    winner_patterns: dict[str, int] = field(default_factory=dict)
    loser_patterns: dict[str, int] = field(default_factory=dict)
    novelty: NoveltyResult | None = None

    # Thresholds used
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)

    # All aggregated ads
    all_ads: list[AggregatedAd] = field(default_factory=list)

    # CSV stats
    csv_stats: dict[str, Any] = field(default_factory=dict)


def run_pipeline(
    csv_path: str,
    clickup_tasks: list[ClickUpTask] | None = None,
    thresholds: ThresholdConfig | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
) -> PipelineResult:
    """Run the full creative feedback loop pipeline.

    Args:
        csv_path: Path to the Meta Ads Manager CSV export.
        clickup_tasks: Optional list of ClickUp tasks to match against.
        thresholds: Winner/loser threshold config (defaults to FIX 2 values).
        date_start: Optional CSV date filter start.
        date_end: Optional CSV date filter end.

    Returns:
        PipelineResult with all analysis.
    """
    if thresholds is None:
        thresholds = ThresholdConfig()

    result = PipelineResult(thresholds=thresholds)

    # ── Step 1: Load & Aggregate CSV (FIX 1 — ROOT CAUSE FIX) ──
    logger.info("=" * 60)
    logger.info("STEP 1: Loading and aggregating CSV")
    logger.info("=" * 60)

    all_ads, csv_stats = load_and_aggregate_csv(
        csv_path, date_start=date_start, date_end=date_end
    )
    result.all_ads = all_ads
    result.csv_stats = csv_stats
    result.raw_rows = csv_stats["raw_rows"]
    result.unique_ads = csv_stats["unique_ads"]
    result.total_csv_spend = csv_stats["total_spend"]

    # FIX 7: Log aggregation stats
    logger.info(f"Aggregated {result.raw_rows} CSV rows into {result.unique_ads} unique ads")
    logger.info(f"Total spend in CSV: ${result.total_csv_spend:,.2f}")

    # ── Step 2: Classify winners/losers (FIX 2 + FIX 3) ──
    logger.info("=" * 60)
    logger.info("STEP 2: Classifying winners and losers")
    logger.info("=" * 60)

    classified, counts = classify_ads(all_ads, thresholds)
    result.classified_ads = classified
    result.winner_count = counts["winner"]
    result.loser_count = counts["loser"]
    result.untested_count = counts["untested"]
    result.above_spend_threshold = counts["winner"] + counts["loser"]

    # FIX 7: Log classification stats
    logger.info(
        f"{result.above_spend_threshold} ads above spend threshold, "
        f"{result.winner_count} ads with ROAS >= {thresholds.winner_roas_min} (winners), "
        f"{result.loser_count} ads with ROAS < {thresholds.loser_roas_max} (losers)"
    )

    # ── Step 3: Match to ClickUp ──
    if clickup_tasks:
        logger.info("=" * 60)
        logger.info("STEP 3: Matching to ClickUp tasks")
        logger.info("=" * 60)
        result.matched_ads = match_ads_to_clickup(classified, clickup_tasks)
    else:
        logger.info("STEP 3: No ClickUp tasks provided — skipping matching")
        result.matched_ads = [
            MatchedAd(classified_ad=c) for c in classified
        ]

    # ── Step 4: Build Top 50 (FIX 5) ──
    logger.info("=" * 60)
    logger.info("STEP 4: Building Top 50 by spend")
    logger.info("=" * 60)
    result.top50 = build_top50(all_ads, clickup_tasks)

    # ── Step 5: Extract patterns and compute novelty (FIX 6) ──
    logger.info("=" * 60)
    logger.info("STEP 5: Computing pattern novelty")
    logger.info("=" * 60)

    winners = [c for c in classified if c.classification == "winner"]
    losers = [c for c in classified if c.classification == "loser"]

    # Extract simple patterns from ad names (hooks, formats, etc.)
    winner_pats = _extract_name_patterns(winners)
    loser_pats = _extract_name_patterns(losers)
    result.winner_patterns = winner_pats
    result.loser_patterns = loser_pats

    if winners or losers:
        result.novelty = compute_novelty(
            winner_pats, loser_pats,
            total_winners=len(winners),
            total_losers=len(losers),
        )

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)

    return result


def _extract_name_patterns(ads: list[ClassifiedAd]) -> dict[str, int]:
    """Extract simple patterns from ad names for novelty analysis.

    Looks for common naming convention patterns like format indicators,
    hook types, version numbers, etc.
    """
    import re
    patterns: dict[str, int] = {}

    format_keywords = [
        "ugc", "static", "video", "carousel", "story", "reel",
        "testimonial", "review", "before after", "demo", "unboxing",
        "founder", "talking head", "slideshow", "gif",
    ]
    hook_keywords = [
        "hook", "problem", "solution", "question", "stat",
        "shocking", "mistake", "secret", "hack", "tip",
        "vs", "comparison", "transformation",
    ]

    for c_ad in ads:
        name_lower = c_ad.ad.ad_name.lower()

        for kw in format_keywords:
            if kw in name_lower:
                key = f"format:{kw}"
                patterns[key] = patterns.get(key, 0) + 1

        for kw in hook_keywords:
            if kw in name_lower:
                key = f"hook:{kw}"
                patterns[key] = patterns.get(key, 0) + 1

        # Detect version patterns (v1, v2, etc.)
        if re.search(r"v\d+", name_lower):
            patterns["has_version"] = patterns.get("has_version", 0) + 1

        # Detect emoji usage
        if any(ord(c) > 127 for c in c_ad.ad.ad_name):
            patterns["has_emoji_or_unicode"] = patterns.get("has_emoji_or_unicode", 0) + 1

    return patterns
