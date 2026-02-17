"""Ad selection and advertiser ranking engine.

Classifies ads by priority (P1-P4) based on recency and impressions.
Deduplicates ads by advertiser + primary text prefix.
Ranks advertisers by composite score (recent activity + impression volume).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from meta_ads_analyzer.models import (
    AdvertiserEntry,
    ClassifiedAd,
    Priority,
    ScrapedAd,
    SelectionResult,
    SelectionStats,
    SkipReason,
)
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


def classify_ad(
    ad: ScrapedAd,
    config: dict,
    now: Optional[datetime] = None,
) -> tuple[Optional[Priority], str, Optional[SkipReason], Optional[int]]:
    """Classify a single ad by priority level.

    Args:
        ad: Ad to classify
        config: Config dict with [selection] section
        now: Current datetime (for testing)

    Returns:
        (priority, label, skip_reason, days_since_launch)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    selection_cfg = config.get("selection", {})

    # Check skip rules first
    if not ad.started_running:
        return None, "SKIP", SkipReason.NO_LAUNCH_DATE, None

    # Parse launch date
    try:
        if ad.started_running.endswith("Z"):
            launch = datetime.fromisoformat(ad.started_running.replace("Z", "+00:00"))
        else:
            launch = datetime.fromisoformat(ad.started_running)
        if launch.tzinfo is None:
            launch = launch.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        logger.warning(f"Invalid launch date for ad {ad.ad_id}: {ad.started_running}")
        return None, "SKIP", SkipReason.NO_LAUNCH_DATE, None

    days_since_launch = (now - launch).days

    # Skip rule: legacy autopilot (>=180 days old)
    if days_since_launch >= selection_cfg.get("skip_older_than_days", 180):
        return None, "SKIP", SkipReason.LEGACY_AUTOPILOT, days_since_launch

    # Skip rule: thin text (<50 words)
    if ad.max_primary_text_words < selection_cfg.get("min_primary_text_words", 50):
        return None, "SKIP", SkipReason.THIN_TEXT, days_since_launch

    # Skip rule: failed test (low impressions + old)
    impressions = ad.impression_lower
    if impressions > 0:
        failed_test_max_impressions = selection_cfg.get("failed_test_max_impressions", 1000)
        failed_test_min_days = selection_cfg.get("failed_test_min_days", 30)
        if impressions < failed_test_max_impressions and days_since_launch > failed_test_min_days:
            return None, "SKIP", SkipReason.FAILED_TEST, days_since_launch

    # Priority classification (when impressions available)
    if impressions > 0:
        # P1: Active winner (<=14 days + >=50K impressions)
        if (
            days_since_launch <= selection_cfg.get("active_winner_max_days", 14)
            and impressions >= selection_cfg.get("active_winner_min_impressions", 50000)
        ):
            return Priority.P1_ACTIVE_WINNER, "ACTIVE_WINNER", None, days_since_launch

        # P2: Proven recent (<=30 days + >=10K impressions)
        if (
            days_since_launch <= selection_cfg.get("proven_recent_max_days", 30)
            and impressions >= selection_cfg.get("proven_recent_min_impressions", 10000)
        ):
            return Priority.P2_PROVEN_RECENT, "PROVEN_RECENT", None, days_since_launch

        # P3: Strategic direction (<=7 days, any impressions)
        if days_since_launch <= selection_cfg.get("strategic_direction_max_days", 7):
            return (
                Priority.P3_STRATEGIC_DIRECTION,
                "STRATEGIC_DIRECTION",
                None,
                days_since_launch,
            )

        # P4: Recent moderate (<=60 days + >=50K impressions)
        if (
            days_since_launch <= selection_cfg.get("recent_moderate_max_days", 60)
            and impressions >= selection_cfg.get("recent_moderate_min_impressions", 50000)
        ):
            return Priority.P4_RECENT_MODERATE, "RECENT_MODERATE", None, days_since_launch

    else:
        # Fallback classification when impressions = 0 (Meta removed public impression data)
        if days_since_launch <= selection_cfg.get("active_winner_max_days", 14):
            return Priority.P1_ACTIVE_WINNER, "ACTIVE_WINNER", None, days_since_launch

        if days_since_launch <= selection_cfg.get("proven_recent_max_days", 30):
            return Priority.P2_PROVEN_RECENT, "PROVEN_RECENT", None, days_since_launch

        if days_since_launch <= selection_cfg.get("recent_moderate_max_days", 60):
            return Priority.P4_RECENT_MODERATE, "RECENT_MODERATE", None, days_since_launch

    # Below threshold
    return None, "SKIP", SkipReason.BELOW_THRESHOLD, days_since_launch


def deduplicate_ads(ads: list[ScrapedAd]) -> tuple[list[ScrapedAd], int]:
    """Deduplicate ads by advertiser + first 60 chars of primary text.

    Keeps ad with highest impressions per key.

    Args:
        ads: Ads to deduplicate

    Returns:
        (kept_ads, duplicates_removed_count)
    """
    seen: dict[str, ScrapedAd] = {}

    for ad in ads:
        # Dedup key: page_name :: first 60 chars of primary text
        text_prefix = (ad.primary_text or "")[:60]
        key = f"{ad.page_name}::{text_prefix}"

        if key not in seen:
            seen[key] = ad
        else:
            # Keep ad with higher impressions
            if ad.impression_lower > seen[key].impression_lower:
                seen[key] = ad

    kept = list(seen.values())
    duplicates_removed = len(ads) - len(kept)

    if duplicates_removed > 0:
        logger.info(f"Removed {duplicates_removed} duplicate ads")

    return kept, duplicates_removed


def select_ads(
    ads: list[ScrapedAd],
    config: dict,
    limit: int = 0,
    now: Optional[datetime] = None,
) -> SelectionResult:
    """Full selection pipeline: classify → deduplicate → sort.

    Args:
        ads: All ads from scan
        config: Config dict with [selection] section
        limit: Max ads to return (0 = no limit)
        now: Current datetime (for testing)

    Returns:
        SelectionResult with selected/skipped ads and stats
    """
    logger.info(f"Selecting ads from {len(ads)} total ads")

    # Classify all ads
    classified_ads: list[ClassifiedAd] = []
    for ad in ads:
        priority, label, skip_reason, days = classify_ad(ad, config, now)
        classified_ads.append(
            ClassifiedAd(
                ad=ad,
                priority=priority,
                priority_label=label,
                skip_reason=skip_reason,
                days_since_launch=days,
            )
        )

    # Separate selected from skipped
    selected = [ca for ca in classified_ads if ca.priority is not None]
    skipped = [ca for ca in classified_ads if ca.priority is None]

    logger.info(f"Classified: {len(selected)} selected, {len(skipped)} skipped")

    # Deduplicate selected ads
    selected_ads = [ca.ad for ca in selected]
    deduped_ads, dup_count = deduplicate_ads(selected_ads)

    # Rebuild ClassifiedAd list after dedup
    deduped_classified = []
    deduped_ids = {ad.ad_id for ad in deduped_ads}
    for ca in selected:
        if ca.ad.ad_id in deduped_ids:
            deduped_classified.append(ca)

    selected = deduped_classified

    # Sort by priority (P1 first), then by impressions (highest first)
    selected.sort(
        key=lambda ca: (
            ca.priority.value if ca.priority else "z",
            -ca.ad.impression_lower,
        )
    )

    # Apply limit
    if limit > 0:
        selected = selected[:limit]

    # Build stats
    stats = SelectionStats(
        total_scanned=len(ads),
        total_selected=len(selected),
        total_skipped=len(skipped),
        duplicates_removed=dup_count,
    )

    # Count by priority
    for ca in selected:
        if ca.priority:
            label = ca.priority_label
            stats.by_priority[label] = stats.by_priority.get(label, 0) + 1

    # Count skip reasons
    for ca in skipped:
        if ca.skip_reason:
            reason = ca.skip_reason.value
            stats.skip_reasons[reason] = stats.skip_reasons.get(reason, 0) + 1

    logger.info(
        f"Selection complete: {stats.total_selected} selected, "
        f"{stats.total_skipped} skipped, {stats.duplicates_removed} duplicates removed"
    )

    return SelectionResult(selected=selected, skipped=skipped, stats=stats)


def aggregate_by_advertiser(ads: list[ScrapedAd]) -> list[AdvertiserEntry]:
    """Aggregate ads by page_name into advertiser entries.

    Args:
        ads: All scraped ads

    Returns:
        List of AdvertiserEntry objects (unsorted)
    """
    advertisers: dict[str, AdvertiserEntry] = {}

    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    for ad in ads:
        page_name = ad.page_name
        if page_name not in advertisers:
            advertisers[page_name] = AdvertiserEntry(
                page_id=ad.page_id,
                page_name=page_name,
                headlines=[],
            )

        entry = advertisers[page_name]
        entry.ad_count += 1

        # Active count (no stop date, or stop date in future)
        if ad.started_running:
            entry.active_ad_count += 1

        # Recent count (launched in last 30 days)
        if ad.started_running:
            try:
                if ad.started_running.endswith("Z"):
                    launch = datetime.fromisoformat(ad.started_running.replace("Z", "+00:00"))
                else:
                    launch = datetime.fromisoformat(ad.started_running)
                if launch.tzinfo is None:
                    launch = launch.replace(tzinfo=timezone.utc)

                if launch >= thirty_days_ago:
                    entry.recent_ad_count += 1

                # Track earliest/latest launch
                if entry.earliest_launch is None or launch < entry.earliest_launch:
                    entry.earliest_launch = launch
                if entry.latest_launch is None or launch > entry.latest_launch:
                    entry.latest_launch = launch
            except (ValueError, AttributeError):
                pass

        # Impression totals
        entry.total_impression_lower += ad.impression_lower
        if ad.impression_upper:
            entry.max_impression_upper = max(entry.max_impression_upper, ad.impression_upper)

        # Collect headlines
        if ad.headline and ad.headline not in entry.headlines:
            entry.headlines.append(ad.headline)

    return list(advertisers.values())


def rank_advertisers(advertisers: list[AdvertiserEntry]) -> list[AdvertiserEntry]:
    """Rank advertisers by relevance score.

    Score = recentScore + impressionScore + activeBonus
    - recentScore: based on % of ads launched in last 30 days
    - impressionScore: log10(total impressions) * 15
    - activeBonus: min(active_ad_count * 3, 30)

    Args:
        advertisers: Unranked advertiser entries

    Returns:
        List sorted by relevance_score (descending)
    """
    for entry in advertisers:
        # Recent score
        recent_ratio = entry.recent_ad_count / entry.ad_count if entry.ad_count > 0 else 0
        recent_score = (recent_ratio * 50) + min(entry.recent_ad_count * 5, 50)

        # Impression score
        total_impressions = entry.total_impression_lower
        if total_impressions > 0:
            impression_score = min(math.log10(total_impressions) * 15, 100)
        else:
            impression_score = 0

        # Active bonus
        active_bonus = min(entry.active_ad_count * 3, 30)

        # Total score
        entry.relevance_score = int(recent_score + impression_score + active_bonus)

    # Sort by score descending
    advertisers.sort(key=lambda e: e.relevance_score, reverse=True)

    logger.info(f"Ranked {len(advertisers)} advertisers")

    return advertisers
