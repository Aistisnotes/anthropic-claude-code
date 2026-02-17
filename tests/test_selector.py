"""Tests for ad selection engine."""

from datetime import datetime, timedelta, timezone

import pytest

from meta_ads_analyzer.models import Priority, ScrapedAd, SkipReason
from meta_ads_analyzer.selector import (
    aggregate_by_advertiser,
    classify_ad,
    deduplicate_ads,
    rank_advertisers,
    select_ads,
)


@pytest.fixture
def config():
    """Standard selection config."""
    return {
        "selection": {
            "active_winner_max_days": 14,
            "active_winner_min_impressions": 50000,
            "proven_recent_max_days": 30,
            "proven_recent_min_impressions": 10000,
            "strategic_direction_max_days": 7,
            "recent_moderate_max_days": 60,
            "recent_moderate_min_impressions": 50000,
            "skip_older_than_days": 180,
            "min_primary_text_words": 50,
            "failed_test_max_impressions": 1000,
            "failed_test_min_days": 30,
        }
    }


@pytest.fixture
def now():
    """Fixed datetime for testing."""
    return datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_ad(
    ad_id: str,
    page_name: str = "TestBrand",
    days_ago: int = 0,
    impressions: int = 0,
    word_count: int = 100,
    now: datetime = None,
) -> ScrapedAd:
    """Helper to create test ads."""
    if now is None:
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    launch_date = (now - timedelta(days=days_ago)).isoformat()
    primary_text = " ".join(["word"] * word_count)

    return ScrapedAd(
        ad_id=ad_id,
        page_name=page_name,
        primary_text=primary_text,
        started_running=launch_date,
        impression_lower=impressions,
    )


def test_classify_active_winner(config, now):
    """Test P1 classification: <14 days + >=50K impressions."""
    ad = make_ad("1", days_ago=10, impressions=75000, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority == Priority.P1_ACTIVE_WINNER
    assert label == "ACTIVE_WINNER"
    assert skip_reason is None
    assert days == 10


def test_classify_proven_recent(config, now):
    """Test P2 classification: <30 days + >=10K impressions."""
    ad = make_ad("2", days_ago=25, impressions=15000, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority == Priority.P2_PROVEN_RECENT
    assert label == "PROVEN_RECENT"
    assert skip_reason is None
    assert days == 25


def test_classify_strategic_direction(config, now):
    """Test P3 classification: <=7 days, any impressions."""
    ad = make_ad("3", days_ago=5, impressions=5000, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority == Priority.P3_STRATEGIC_DIRECTION
    assert label == "STRATEGIC_DIRECTION"
    assert skip_reason is None
    assert days == 5


def test_classify_recent_moderate(config, now):
    """Test P4 classification: <=60 days + >=50K impressions."""
    ad = make_ad("4", days_ago=50, impressions=60000, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority == Priority.P4_RECENT_MODERATE
    assert label == "RECENT_MODERATE"
    assert skip_reason is None
    assert days == 50


def test_skip_no_launch_date(config, now):
    """Test skip rule: no launch date."""
    ad = ScrapedAd(
        ad_id="5",
        page_name="TestBrand",
        primary_text="word " * 100,
        started_running=None,
        impression_lower=50000,
    )

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority is None
    assert label == "SKIP"
    assert skip_reason == SkipReason.NO_LAUNCH_DATE
    assert days is None


def test_skip_legacy_ad(config, now):
    """Test skip rule: >=180 days old."""
    ad = make_ad("6", days_ago=200, impressions=50000, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority is None
    assert label == "SKIP"
    assert skip_reason == SkipReason.LEGACY_AUTOPILOT
    assert days == 200


def test_skip_thin_text(config, now):
    """Test skip rule: <50 words."""
    ad = make_ad("7", days_ago=10, impressions=50000, word_count=30, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority is None
    assert label == "SKIP"
    assert skip_reason == SkipReason.THIN_TEXT
    assert days == 10


def test_skip_failed_test(config, now):
    """Test skip rule: low impressions + old."""
    ad = make_ad("8", days_ago=40, impressions=500, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority is None
    assert label == "SKIP"
    assert skip_reason == SkipReason.FAILED_TEST
    assert days == 40


def test_skip_below_threshold(config, now):
    """Test skip rule: doesn't meet any priority criteria."""
    ad = make_ad("9", days_ago=70, impressions=5000, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority is None
    assert label == "SKIP"
    assert skip_reason == SkipReason.BELOW_THRESHOLD
    assert days == 70


def test_fallback_classification_when_no_impressions(config, now):
    """Test fallback when impressions = 0 (Meta removed public data)."""
    # Should classify by days alone
    ad = make_ad("10", days_ago=10, impressions=0, now=now)

    priority, label, skip_reason, days = classify_ad(ad, config, now)

    assert priority == Priority.P1_ACTIVE_WINNER
    assert label == "ACTIVE_WINNER"
    assert days == 10


def test_deduplication():
    """Test duplicate removal by advertiser + text prefix."""
    ads = [
        make_ad("1", "BrandA", impressions=10000, word_count=100),
        make_ad("2", "BrandA", impressions=20000, word_count=100),  # Duplicate, higher impressions
        make_ad("3", "BrandB", impressions=5000, word_count=100),
        make_ad("4", "BrandB", impressions=3000, word_count=80),  # Different text, not duplicate
    ]

    # Make first two ads have same text prefix
    ads[0].primary_text = "This is a test ad copy " * 10
    ads[1].primary_text = "This is a test ad copy " * 10

    kept, dup_count = deduplicate_ads(ads)

    assert len(kept) == 3
    assert dup_count == 1

    # Should keep ad 2 (higher impressions)
    kept_ids = {ad.ad_id for ad in kept}
    assert "2" in kept_ids
    assert "1" not in kept_ids


def test_full_selection_pipeline(config, now):
    """Test end-to-end selection with mixed ads."""
    ads = [
        make_ad("p1", days_ago=10, impressions=75000, now=now),  # P1
        make_ad("p2", days_ago=25, impressions=15000, now=now),  # P2
        make_ad("p3", days_ago=5, impressions=5000, now=now),  # P3
        make_ad("p4", days_ago=50, impressions=60000, now=now),  # P4
        make_ad("skip1", days_ago=200, impressions=50000, now=now),  # Legacy
        make_ad("skip2", days_ago=40, impressions=500, now=now),  # Failed test
        make_ad("skip3", days_ago=10, impressions=50000, word_count=30, now=now),  # Thin text
    ]

    result = select_ads(ads, config, now=now)

    assert result.stats.total_scanned == 7
    assert result.stats.total_selected == 4
    assert result.stats.total_skipped == 3

    # Check priority distribution
    assert result.stats.by_priority["ACTIVE_WINNER"] == 1
    assert result.stats.by_priority["PROVEN_RECENT"] == 1
    assert result.stats.by_priority["STRATEGIC_DIRECTION"] == 1
    assert result.stats.by_priority["RECENT_MODERATE"] == 1

    # Check skip reasons
    assert result.stats.skip_reasons["legacy_autopilot"] == 1
    assert result.stats.skip_reasons["failed_test"] == 1
    assert result.stats.skip_reasons["thin_text"] == 1

    # Check sorting (P1 should be first)
    assert result.selected[0].ad.ad_id == "p1"
    assert result.selected[0].priority == Priority.P1_ACTIVE_WINNER


def test_advertiser_aggregation(now):
    """Test advertiser aggregation."""
    ads = [
        make_ad("1", "BrandA", days_ago=10, impressions=10000, now=now),
        make_ad("2", "BrandA", days_ago=5, impressions=20000, now=now),
        make_ad("3", "BrandB", days_ago=100, impressions=5000, now=now),
    ]

    # Add headlines
    ads[0].headline = "Headline 1"
    ads[1].headline = "Headline 2"
    ads[2].headline = "Headline 3"

    advertisers = aggregate_by_advertiser(ads)

    assert len(advertisers) == 2

    # Find BrandA
    brand_a = [a for a in advertisers if a.page_name == "BrandA"][0]
    assert brand_a.ad_count == 2
    assert brand_a.active_ad_count == 2
    assert brand_a.recent_ad_count == 2  # Both launched in last 30 days
    assert brand_a.total_impression_lower == 30000

    # Find BrandB
    brand_b = [a for a in advertisers if a.page_name == "BrandB"][0]
    assert brand_b.ad_count == 1
    assert brand_b.recent_ad_count == 0  # 100 days ago


def test_advertiser_ranking():
    """Test advertiser ranking score calculation."""
    from meta_ads_analyzer.models import AdvertiserEntry

    advertisers = [
        AdvertiserEntry(
            page_name="HighRecent",
            ad_count=20,
            active_ad_count=10,
            recent_ad_count=15,
            total_impression_lower=100000,
        ),
        AdvertiserEntry(
            page_name="HighImpressions",
            ad_count=50,
            active_ad_count=30,
            recent_ad_count=5,
            total_impression_lower=10000000,
        ),
        AdvertiserEntry(
            page_name="LowEverything",
            ad_count=5,
            active_ad_count=2,
            recent_ad_count=1,
            total_impression_lower=1000,
        ),
    ]

    ranked = rank_advertisers(advertisers)

    # Check scores were assigned
    assert all(a.relevance_score > 0 for a in ranked)

    # Check sorted descending
    assert ranked[0].relevance_score >= ranked[1].relevance_score
    assert ranked[1].relevance_score >= ranked[2].relevance_score

    # HighImpressions should rank highest due to massive impressions
    assert ranked[0].page_name == "HighImpressions"
