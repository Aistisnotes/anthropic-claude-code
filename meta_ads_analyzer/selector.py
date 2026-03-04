"""Ad selection and advertiser ranking engine.

Classifies ads by priority (P1-P4) based on recency and impressions.
Deduplicates ads by advertiser + primary text prefix.
Ranks advertisers by composite score (recent activity + impression volume).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

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
    impressions = ad.impression_lower

    # Try to parse launch date first (to have it available for skip reasons)
    days_since_launch = None
    has_date = False
    if ad.started_running:
        try:
            if ad.started_running.endswith("Z"):
                launch = datetime.fromisoformat(ad.started_running.replace("Z", "+00:00"))
            else:
                launch = datetime.fromisoformat(ad.started_running)
            if launch.tzinfo is None:
                launch = launch.replace(tzinfo=timezone.utc)
            days_since_launch = (now - launch).days
            has_date = True
        except (ValueError, AttributeError):
            logger.debug(f"Invalid launch date for ad {ad.ad_id}, using impression-based classification")
            has_date = False

    # Skip rule: thin text (<50 words) - applies regardless of date
    if ad.max_primary_text_words < selection_cfg.get("min_primary_text_words", 50):
        return None, "SKIP", SkipReason.THIN_TEXT, days_since_launch

    # If we have a valid date, apply date-based skip rules
    if has_date:
        # Skip rule: legacy autopilot (>=180 days old)
        if days_since_launch >= selection_cfg.get("skip_older_than_days", 180):
            return None, "SKIP", SkipReason.LEGACY_AUTOPILOT, days_since_launch

        # Skip rule: failed test (low impressions + old)
        if impressions > 0:
            failed_test_max_impressions = selection_cfg.get("failed_test_max_impressions", 1000)
            failed_test_min_days = selection_cfg.get("failed_test_min_days", 30)
            if impressions < failed_test_max_impressions and days_since_launch > failed_test_min_days:
                return None, "SKIP", SkipReason.FAILED_TEST, days_since_launch

    # Priority classification
    if has_date and impressions > 0:
        # Date-based classification (preferred when dates available)
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

    elif has_date and impressions == 0:
        # Fallback when date available but impressions hidden
        if days_since_launch <= selection_cfg.get("active_winner_max_days", 14):
            return Priority.P1_ACTIVE_WINNER, "ACTIVE_WINNER", None, days_since_launch

        if days_since_launch <= selection_cfg.get("proven_recent_max_days", 30):
            return Priority.P2_PROVEN_RECENT, "PROVEN_RECENT", None, days_since_launch

        if days_since_launch <= selection_cfg.get("recent_moderate_max_days", 60):
            return Priority.P4_RECENT_MODERATE, "RECENT_MODERATE", None, days_since_launch

    else:
        # No date available - use impression-based classification as fallback
        # This handles real-world Meta ads that don't expose launch dates
        if impressions >= selection_cfg.get("active_winner_min_impressions", 50000):
            # High impressions = likely active winner
            return Priority.P1_ACTIVE_WINNER, "ACTIVE_WINNER", None, None

        elif impressions >= selection_cfg.get("proven_recent_min_impressions", 10000):
            # Medium-high impressions = likely proven
            return Priority.P2_PROVEN_RECENT, "PROVEN_RECENT", None, None

        elif impressions > 0:
            # Some impressions = classify as P4 (moderate)
            return Priority.P4_RECENT_MODERATE, "RECENT_MODERATE", None, None

        else:
            # No impressions, no date = default to P4
            # Still include for analysis rather than skip
            return Priority.P4_RECENT_MODERATE, "RECENT_MODERATE", None, None

    # Below threshold (only for ads with dates that don't meet any criteria)
    return None, "SKIP", SkipReason.BELOW_THRESHOLD, days_since_launch


def deduplicate_ads(ads: list[ScrapedAd]) -> tuple[list[ScrapedAd], int]:
    """Deduplicate ads by advertiser + full primary text.

    Keeps ad with highest impressions per key.

    Args:
        ads: Ads to deduplicate

    Returns:
        (kept_ads, duplicates_removed_count)
    """
    seen: dict[str, ScrapedAd] = {}

    for ad in ads:
        # Dedup key: page_name :: full primary text
        # Use full text to avoid deduplicating ads with similar but different copy
        text = ad.primary_text or ""
        key = f"{ad.page_name}::{text}"

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

    # Deduplicate within each priority group to preserve ads with different priorities
    # This prevents deduplication of ads that happen to have same text but different strategic value
    total_dup_count = 0
    deduped_by_priority: dict[Priority, list[ClassifiedAd]] = {}

    # Group by priority
    for ca in selected:
        if ca.priority not in deduped_by_priority:
            deduped_by_priority[ca.priority] = []
        deduped_by_priority[ca.priority].append(ca)

    # Deduplicate within each priority group
    # Skip deduplication for large groups (4+ ads) as these are likely intentional campaign flights
    deduped_classified = []
    for priority, cas in deduped_by_priority.items():
        ads_in_group = [ca.ad for ca in cas]

        # Only deduplicate if group is small (2-3 ads)
        # Larger groups with same text are likely campaign flights, not duplicates
        if len(ads_in_group) <= 3:
            deduped_ads, dup_count = deduplicate_ads(ads_in_group)
            total_dup_count += dup_count

            # Keep only deduped ads
            deduped_ids = {ad.ad_id for ad in deduped_ads}
            for ca in cas:
                if ca.ad.ad_id in deduped_ids:
                    deduped_classified.append(ca)
        else:
            # Skip deduplication for large groups
            deduped_classified.extend(cas)

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
        duplicates_removed=total_dup_count,
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


_GENERIC_DOMAINS = frozenset({
    "facebook.com", "fb.com", "instagram.com", "youtube.com",
    "linktr.ee", "linkinbio.com", "bio.site", "beacons.ai",
    "shopify.com", "myshopify.com", "amazon.com", "amzn.to",
    "etsy.com", "ebay.com", "walmart.com", "target.com",
})


def extract_root_domain(url: str) -> Optional[str]:
    """Return the root domain from a URL (e.g. 'elare.store' from 'https://www.elare.store/p')."""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        parts = netloc.split(".")
        if len(parts) >= 2:
            root = ".".join(parts[-2:])
        else:
            root = netloc
        if root and root not in _GENERIC_DOMAINS and len(root) > 3:
            return root
    except Exception:
        pass
    return None


# Keep underscore alias for backward compatibility
_extract_root_domain = extract_root_domain


def _merge_by_domain(
    advertisers: list[AdvertiserEntry],
    ads: list[ScrapedAd],
) -> list[AdvertiserEntry]:
    """Merge AdvertiserEntry objects that share the same destination domain.

    A brand may run ads from multiple Facebook pages (e.g. "BrandPage",
    "BrandDr.Smith", "Brand Official") all linking to the same website.
    aggregate_by_advertiser() treats each page as a separate advertiser, so
    a brand with 30 ads spread across 3 pages appears as three advertisers
    each with 10 ads — all below BLUE_OCEAN_THRESHOLD.

    This function detects pages that share the same primary destination domain
    and merges them into a single AdvertiserEntry, summing their counts.
    The page_name with the most ads becomes canonical; all page names are
    stored in all_page_names for downstream filtering.
    """
    # Count how often each page links to each domain
    page_domain_freq: dict[str, dict[str, int]] = {}
    for ad in ads:
        if not ad.link_url or not ad.page_name:
            continue
        domain = extract_root_domain(ad.link_url)
        if domain:
            page_domain_freq.setdefault(ad.page_name, {})
            page_domain_freq[ad.page_name][domain] = (
                page_domain_freq[ad.page_name].get(domain, 0) + 1
            )

    # Primary domain for each page = most frequent domain
    page_primary_domain: dict[str, str] = {
        page: max(freq, key=freq.__getitem__)
        for page, freq in page_domain_freq.items()
        if freq
    }

    # Group advertiser entries by primary domain
    domain_groups: dict[str, list[AdvertiserEntry]] = {}
    no_domain: list[AdvertiserEntry] = []
    for entry in advertisers:
        domain = page_primary_domain.get(entry.page_name)
        if domain:
            domain_groups.setdefault(domain, []).append(entry)
        else:
            entry.all_page_names = [entry.page_name]
            no_domain.append(entry)

    merged: list[AdvertiserEntry] = []
    for domain, entries in domain_groups.items():
        if len(entries) == 1:
            entries[0].all_page_names = [entries[0].page_name]
            merged.append(entries[0])
            continue

        # Multiple pages share domain → merge into the one with most ads
        entries.sort(key=lambda e: e.ad_count, reverse=True)
        canonical = entries[0]
        for other in entries[1:]:
            canonical.ad_count += other.ad_count
            canonical.active_ad_count += other.active_ad_count
            canonical.recent_ad_count += other.recent_ad_count
            canonical.total_impression_lower += other.total_impression_lower
            if other.max_impression_upper:
                canonical.max_impression_upper = max(
                    canonical.max_impression_upper, other.max_impression_upper
                )
            if other.earliest_launch:
                if canonical.earliest_launch is None or other.earliest_launch < canonical.earliest_launch:
                    canonical.earliest_launch = other.earliest_launch
            if other.latest_launch:
                if canonical.latest_launch is None or other.latest_launch > canonical.latest_launch:
                    canonical.latest_launch = other.latest_launch
            for headline in other.headlines:
                if headline not in canonical.headlines:
                    canonical.headlines.append(headline)

        canonical.all_page_names = [e.page_name for e in entries]
        logger.info(
            f"Domain merge: {len(entries)} pages → '{canonical.page_name}' "
            f"(domain={domain}, total_ads={canonical.ad_count}): "
            f"{canonical.all_page_names}"
        )
        merged.append(canonical)

    return merged + no_domain


def aggregate_by_advertiser(
    ads: list[ScrapedAd], now: Optional[datetime] = None
) -> list[AdvertiserEntry]:
    """Aggregate ads by page_name into advertiser entries.

    Args:
        ads: All scraped ads
        now: Current datetime (for testing). If not provided, inferred from most recent ad.

    Returns:
        List of AdvertiserEntry objects (unsorted)
    """
    if now is None:
        # Infer "now" from the most recent ad launch date + 1 day
        # This makes aggregation deterministic and testable
        most_recent = None
        for ad in ads:
            if ad.started_running:
                try:
                    if ad.started_running.endswith("Z"):
                        launch = datetime.fromisoformat(ad.started_running.replace("Z", "+00:00"))
                    else:
                        launch = datetime.fromisoformat(ad.started_running)
                    if launch.tzinfo is None:
                        launch = launch.replace(tzinfo=timezone.utc)

                    if most_recent is None or launch > most_recent:
                        most_recent = launch
                except (ValueError, AttributeError):
                    pass

        # Use most recent ad date + 1 day, or current time if no valid dates found
        now = (most_recent + timedelta(days=1)) if most_recent else datetime.now(timezone.utc)

    advertisers: dict[str, AdvertiserEntry] = {}
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

    result = list(advertisers.values())
    # Merge pages that share the same destination domain so brands running
    # multiple Facebook pages don't fall below the qualifying-ads threshold.
    result = _merge_by_domain(result, ads)
    return result


def rank_advertisers(advertisers: list[AdvertiserEntry]) -> list[AdvertiserEntry]:
    """Rank advertisers by relevance score.

    Score = recentScore + impressionScore + activeBonus
    - recentScore: based on % of ads launched in last 30 days (lighter weight)
    - impressionScore: log10(total impressions) * 30 (heavier weight for massive reach)
    - activeBonus: min(active_ad_count * 2, 20)

    Args:
        advertisers: Unranked advertiser entries

    Returns:
        List sorted by relevance_score (descending)
    """
    for entry in advertisers:
        # Recent score (reduced weight to let impressions dominate)
        recent_ratio = entry.recent_ad_count / entry.ad_count if entry.ad_count > 0 else 0
        recent_score = (recent_ratio * 20) + min(entry.recent_ad_count * 2, 20)

        # Impression score (increased weight for high-impression advertisers)
        total_impressions = entry.total_impression_lower
        if total_impressions > 0:
            impression_score = min(math.log10(total_impressions) * 30, 200)
        else:
            impression_score = 0

        # Active bonus (reduced weight)
        active_bonus = min(entry.active_ad_count * 2, 20)

        # Total score
        entry.relevance_score = int(recent_score + impression_score + active_bonus)

    # Sort by score descending
    advertisers.sort(key=lambda e: e.relevance_score, reverse=True)

    logger.info(f"Ranked {len(advertisers)} advertisers")

    return advertisers


def select_ads_for_brand(
    all_ads: list[ScrapedAd],
    brand_name: str,
    limit: int,
    config: dict,
    now: Optional[datetime] = None,
    all_page_names: Optional[list[str]] = None,
) -> SelectionResult:
    """Select best ads for a specific brand.

    Filters all_ads to only this brand, then runs selection pipeline.

    Args:
        all_ads: All ads from scan
        brand_name: Brand/advertiser name to filter by
        limit: Max ads to select for this brand
        config: Config dict with [selection] section
        now: Current datetime (for testing)
        all_page_names: All Facebook page names for this brand (when a brand runs
            ads from multiple pages). If provided, ads matching any of these page
            names are included. Falls back to brand_name if not provided.

    Returns:
        SelectionResult with selected/skipped ads for this brand only
    """
    # Filter to only this brand's ads (across all known page names)
    names = set(all_page_names) if all_page_names else {brand_name}
    brand_ads = [ad for ad in all_ads if ad.page_name in names]

    logger.info(
        f"Selecting ads for brand '{brand_name}': {len(brand_ads)} total ads"
        + (f" (across {len(names)} pages)" if len(names) > 1 else "")
    )

    # Run standard selection pipeline on brand's ads
    return select_ads(brand_ads, config, limit, now)
