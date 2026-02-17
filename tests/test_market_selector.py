"""Tests for per-brand ad selection (market research)."""

from datetime import datetime, timezone

import pytest

from meta_ads_analyzer.models import Priority, ScrapedAd
from meta_ads_analyzer.selector import select_ads_for_brand


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
    page_name: str,
    days_ago: int,
    impressions: int,
    word_count: int = 100,
) -> ScrapedAd:
    """Helper to create test ads."""
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    from datetime import timedelta

    launch_date = (now - timedelta(days=days_ago)).isoformat()
    primary_text = " ".join(["word"] * word_count)

    return ScrapedAd(
        ad_id=ad_id,
        page_name=page_name,
        primary_text=primary_text,
        started_running=launch_date,
        impression_lower=impressions,
    )


def test_select_ads_for_single_brand(config, now):
    """Test selecting ads for a specific brand from mixed advertiser pool."""
    ads = [
        # BrandA ads
        make_ad("a1", "BrandA", days_ago=10, impressions=75000),  # P1
        make_ad("a2", "BrandA", days_ago=25, impressions=15000),  # P2
        make_ad("a3", "BrandA", days_ago=5, impressions=5000),  # P3
        # BrandB ads
        make_ad("b1", "BrandB", days_ago=10, impressions=80000),  # P1
        make_ad("b2", "BrandB", days_ago=50, impressions=60000),  # P4
        # BrandC ads
        make_ad("c1", "BrandC", days_ago=200, impressions=50000),  # Skip: legacy
    ]

    # Select only BrandA ads
    result = select_ads_for_brand(
        all_ads=ads,
        brand_name="BrandA",
        limit=10,
        config=config,
        now=now,
    )

    # Should only include BrandA ads
    assert len(result.selected) == 3
    assert all(ca.ad.page_name == "BrandA" for ca in result.selected)

    # Check priorities are correct
    assert result.selected[0].priority == Priority.P1_ACTIVE_WINNER
    assert result.selected[1].priority == Priority.P2_PROVEN_RECENT
    assert result.selected[2].priority == Priority.P3_STRATEGIC_DIRECTION


def test_select_ads_for_brand_with_limit(config, now):
    """Test that limit is respected."""
    ads = [
        make_ad("a1", "BrandA", days_ago=10, impressions=75000),
        make_ad("a2", "BrandA", days_ago=11, impressions=70000),
        make_ad("a3", "BrandA", days_ago=12, impressions=65000),
        make_ad("a4", "BrandA", days_ago=13, impressions=60000),
        make_ad("a5", "BrandA", days_ago=14, impressions=55000),
    ]

    result = select_ads_for_brand(
        all_ads=ads,
        brand_name="BrandA",
        limit=3,
        config=config,
        now=now,
    )

    # Should respect limit
    assert len(result.selected) == 3

    # Should be sorted by impressions (highest first)
    assert result.selected[0].ad.impression_lower == 75000
    assert result.selected[1].ad.impression_lower == 70000
    assert result.selected[2].ad.impression_lower == 65000


def test_select_ads_for_nonexistent_brand(config, now):
    """Test selecting ads for a brand that doesn't exist."""
    ads = [
        make_ad("a1", "BrandA", days_ago=10, impressions=75000),
        make_ad("b1", "BrandB", days_ago=10, impressions=80000),
    ]

    result = select_ads_for_brand(
        all_ads=ads,
        brand_name="BrandC",
        limit=10,
        config=config,
        now=now,
    )

    # Should return empty selection
    assert len(result.selected) == 0
    assert result.stats.total_scanned == 0


def test_select_ads_for_brand_with_skipped_ads(config, now):
    """Test that brand selection properly filters skipped ads."""
    ads = [
        make_ad("a1", "BrandA", days_ago=10, impressions=75000),  # P1
        make_ad("a2", "BrandA", days_ago=200, impressions=50000),  # Skip: legacy
        make_ad("a3", "BrandA", days_ago=40, impressions=500),  # Skip: failed test
        make_ad("a4", "BrandA", days_ago=25, impressions=15000),  # P2
    ]

    result = select_ads_for_brand(
        all_ads=ads,
        brand_name="BrandA",
        limit=10,
        config=config,
        now=now,
    )

    # Should only select valid ads
    assert len(result.selected) == 2
    assert result.stats.total_skipped == 2

    # Check skip reasons
    assert "legacy_autopilot" in result.stats.skip_reasons
    assert "failed_test" in result.stats.skip_reasons


def test_select_ads_for_brand_deduplication(config, now):
    """Test that deduplication works within brand selection."""
    ads = [
        make_ad("a1", "BrandA", days_ago=10, impressions=75000),
        make_ad("a2", "BrandA", days_ago=11, impressions=80000),  # Duplicate, higher impressions
    ]

    # Make ads have same text prefix (will be deduplicated)
    ads[0].primary_text = "This is a test ad copy " * 10
    ads[1].primary_text = "This is a test ad copy " * 10

    result = select_ads_for_brand(
        all_ads=ads,
        brand_name="BrandA",
        limit=10,
        config=config,
        now=now,
    )

    # Should keep only one ad (higher impressions)
    assert len(result.selected) == 1
    assert result.stats.duplicates_removed == 1
    assert result.selected[0].ad.ad_id == "a2"  # Higher impressions
