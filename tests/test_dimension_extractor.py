"""Tests for dimension extractor."""

from meta_ads_analyzer.models import PatternReport
from meta_ads_analyzer.compare.dimension_extractor import DimensionExtractor


def test_extract_all_dimensions():
    """Test extracting all 6 dimensions from PatternReport."""
    # Create sample pattern report
    report = PatternReport(
        search_query="test",
        brand="TestBrand",
        hook_patterns=[
            {"hook_type": "question", "frequency": 5},
            {"hook_type": "statistic", "frequency": 3},
        ],
        emotional_trigger_patterns=[
            {"emotion": "security", "frequency": 6},
            {"emotion": "achievement", "frequency": 4},
        ],
        angle_distribution={
            "mechanism": 8,
            "social_proof": 4,
        },
        format_distribution={
            "long_form": 5,
            "testimonial": 3,
        },
        offer_distribution={
            "free_trial": 7,
            "discount": 2,
        },
        cta_distribution={
            "learn_more": 6,
            "shop_now": 3,
        },
    )

    # Extract dimensions
    dimensions = DimensionExtractor.extract_all_dimensions(report)

    # Verify all 6 dimensions extracted
    assert len(dimensions) == 6
    assert 'hooks' in dimensions
    assert 'angles' in dimensions
    assert 'emotions' in dimensions
    assert 'formats' in dimensions
    assert 'offers' in dimensions
    assert 'ctas' in dimensions

    # Verify hooks extracted from patterns
    assert dimensions['hooks']['question'] == 5
    assert dimensions['hooks']['statistic'] == 3

    # Verify emotions extracted from patterns
    assert dimensions['emotions']['security'] == 6
    assert dimensions['emotions']['achievement'] == 4

    # Verify angles extracted from distribution
    assert dimensions['angles']['mechanism'] == 8
    assert dimensions['angles']['social_proof'] == 4

    # Verify formats extracted from distribution
    assert dimensions['formats']['long_form'] == 5
    assert dimensions['formats']['testimonial'] == 3

    # Verify offers extracted from distribution
    assert dimensions['offers']['free_trial'] == 7
    assert dimensions['offers']['discount'] == 2

    # Verify CTAs extracted from distribution
    assert dimensions['ctas']['learn_more'] == 6
    assert dimensions['ctas']['shop_now'] == 3


def test_extract_from_patterns_with_missing_data():
    """Test extraction gracefully handles missing data."""
    report = PatternReport(
        search_query="test",
        brand="TestBrand",
        hook_patterns=[],  # Empty
        emotional_trigger_patterns=[],  # Empty
    )

    dimensions = DimensionExtractor.extract_all_dimensions(report)

    # Should return empty dicts, not fail
    assert dimensions['hooks'] == {}
    assert dimensions['emotions'] == {}


def test_extract_from_patterns_filters_invalid_values():
    """Test extraction filters out invalid dimension values."""
    report = PatternReport(
        search_query="test",
        brand="TestBrand",
        hook_patterns=[
            {"hook_type": "question", "frequency": 5},
            {"hook_type": "invalid_hook", "frequency": 3},  # Invalid
        ],
    )

    dimensions = DimensionExtractor.extract_all_dimensions(report)

    # Should only include valid hook types
    assert 'question' in dimensions['hooks']
    assert 'invalid_hook' not in dimensions['hooks']
