"""Smoke tests - validate imports, config, models, filtering logic, and quality gates.

Run with: python -m pytest tests/test_smoke.py -v
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

# ── Import tests ──


def test_models_import():
    from meta_ads_analyzer.models import (
        AdAnalysis,
        AdContent,
        AdStatus,
        AdType,
        FilterReason,
        PatternReport,
        QualityReport,
        ScrapedAd,
        Transcript,
    )


def test_config_import_and_load():
    from meta_ads_analyzer.utils.config import load_config

    config = load_config()
    assert "scraper" in config
    assert "analyzer" in config
    assert "quality" in config
    assert config["scraper"]["max_ads"] == 100
    assert config["filter"]["min_static_copy_words"] == 500
    assert config["quality"]["min_ads_for_pattern"] == 10


def test_all_modules_import():
    """Verify every module can be imported without errors."""
    from meta_ads_analyzer.analyzer.filter import AdFilter
    from meta_ads_analyzer.quality.gates import CopyQualityChecker, QualityGates
    from meta_ads_analyzer.reporter.output import ReportWriter
    from meta_ads_analyzer.db.store import AdStore
    from meta_ads_analyzer.utils.logging import setup_logging, get_logger


# ── Model tests ──


def test_scraped_ad_creation():
    from meta_ads_analyzer.models import AdType, ScrapedAd

    ad = ScrapedAd(
        ad_id="test_123",
        page_name="Test Brand",
        ad_type=AdType.VIDEO,
        primary_text="This is a test ad with some copy.",
        media_url="https://example.com/video.mp4",
        platforms=["facebook", "instagram"],
    )
    assert ad.ad_id == "test_123"
    assert ad.ad_type == AdType.VIDEO
    assert len(ad.platforms) == 2


def test_ad_content_creation():
    from meta_ads_analyzer.models import AdContent, AdStatus, AdType

    content = AdContent(
        ad_id="test_456",
        brand="TestBrand",
        ad_type=AdType.VIDEO,
        transcript="This is a test transcript for a video ad.",
        transcript_confidence=0.92,
        word_count=9,
        status=AdStatus.TRANSCRIBED,
    )
    assert content.status == AdStatus.TRANSCRIBED
    assert content.transcript_confidence == 0.92


def test_ad_analysis_serialization():
    from meta_ads_analyzer.models import AdAnalysis

    analysis = AdAnalysis(
        ad_id="test_789",
        brand="TestBrand",
        pain_points=["Can't sleep", "Chronic fatigue"],
        root_cause="Cortisol dysregulation from blue light exposure",
        mechanism="Proprietary light-blocking technology",
        mass_desire="Effortless deep sleep every night",
        big_idea="Your bedroom light is the #1 reason you can't sleep",
        analysis_confidence=0.85,
        copy_quality_score=0.72,
    )

    # Test serialization round-trip
    json_str = analysis.model_dump_json()
    restored = AdAnalysis.model_validate_json(json_str)
    assert restored.ad_id == "test_789"
    assert restored.pain_points == ["Can't sleep", "Chronic fatigue"]
    assert restored.analysis_confidence == 0.85


# ── Filter tests ──


def test_filter_static_ad_under_500_words():
    """Static ads with < 500 words primary copy should be filtered out."""
    from meta_ads_analyzer.analyzer.filter import AdFilter
    from meta_ads_analyzer.models import AdStatus, AdType, FilterReason, ScrapedAd

    config = {"filter": {"min_static_copy_words": 500, "skip_duplicates": False}}
    filt = AdFilter(config)

    ad = ScrapedAd(
        ad_id="static_short",
        page_name="Brand",
        ad_type=AdType.STATIC,
        primary_text="Short copy that is only a few words.",
    )

    results = filt.process_ads([ad], {}, {}, "TestBrand")
    assert len(results) == 1
    assert results[0].status == AdStatus.FILTERED_OUT
    assert results[0].filter_reason == FilterReason.SHORT_COPY


def test_filter_static_ad_over_500_words():
    """Static ads with >= 500 words should pass."""
    from meta_ads_analyzer.analyzer.filter import AdFilter
    from meta_ads_analyzer.models import AdStatus, AdType, ScrapedAd

    config = {"filter": {"min_static_copy_words": 500, "skip_duplicates": False}}
    filt = AdFilter(config)

    long_text = " ".join(["word"] * 550)
    ad = ScrapedAd(
        ad_id="static_long",
        page_name="Brand",
        ad_type=AdType.STATIC,
        primary_text=long_text,
    )

    results = filt.process_ads([ad], {}, {}, "TestBrand")
    assert len(results) == 1
    assert results[0].status == AdStatus.DOWNLOADED  # Passed filtering


def test_filter_video_without_download():
    """Video ads with no download should be filtered."""
    from meta_ads_analyzer.analyzer.filter import AdFilter
    from meta_ads_analyzer.models import AdStatus, AdType, FilterReason, ScrapedAd

    config = {"filter": {"skip_duplicates": False}}
    filt = AdFilter(config)

    ad = ScrapedAd(
        ad_id="video_no_dl",
        page_name="Brand",
        ad_type=AdType.VIDEO,
        media_url="https://example.com/video.mp4",
    )

    results = filt.process_ads([ad], {}, {}, "TestBrand")
    assert results[0].status == AdStatus.FILTERED_OUT
    assert results[0].filter_reason == FilterReason.DOWNLOAD_FAILED


def test_filter_video_with_good_transcript():
    """Video ads with good transcript should pass."""
    from meta_ads_analyzer.analyzer.filter import AdFilter
    from meta_ads_analyzer.models import (
        AdStatus,
        AdType,
        DownloadedMedia,
        ScrapedAd,
        Transcript,
    )

    config = {
        "filter": {
            "min_transcript_confidence": 0.4,
            "skip_duplicates": False,
        }
    }
    filt = AdFilter(config)

    ad = ScrapedAd(
        ad_id="video_good",
        page_name="Brand",
        ad_type=AdType.VIDEO,
        media_url="https://example.com/video.mp4",
    )

    downloads = {
        "video_good": DownloadedMedia(
            ad_id="video_good",
            file_path=Path("/tmp/video_good.mp4"),
            file_size_bytes=1000000,
            mime_type="video/mp4",
        )
    }
    transcripts = {
        "video_good": Transcript(
            ad_id="video_good",
            text="This is a great ad about sleeping better at night.",
            confidence=0.88,
            word_count=10,
        )
    }

    results = filt.process_ads([ad], downloads, transcripts, "TestBrand")
    assert results[0].status == AdStatus.TRANSCRIBED
    assert results[0].transcript_confidence == 0.88


def test_filter_duplicate_detection():
    """Duplicate ads should be filtered."""
    from meta_ads_analyzer.analyzer.filter import AdFilter
    from meta_ads_analyzer.models import AdStatus, AdType, FilterReason, ScrapedAd

    config = {"filter": {"min_static_copy_words": 5, "skip_duplicates": True}}
    filt = AdFilter(config)

    long_text = " ".join(["word"] * 550)
    ad1 = ScrapedAd(ad_id="dup1", page_name="Brand", ad_type=AdType.STATIC, primary_text=long_text)
    ad2 = ScrapedAd(ad_id="dup2", page_name="Brand", ad_type=AdType.STATIC, primary_text=long_text)

    results = filt.process_ads([ad1, ad2], {}, {}, "TestBrand")
    statuses = [r.status for r in results]
    assert AdStatus.DOWNLOADED in statuses
    assert AdStatus.FILTERED_OUT in statuses
    filtered = [r for r in results if r.status == AdStatus.FILTERED_OUT]
    assert filtered[0].filter_reason == FilterReason.DUPLICATE


# ── Quality gate tests ──


def test_quality_gates_pass():
    from meta_ads_analyzer.models import AdAnalysis, AdContent, AdStatus, AdType
    from meta_ads_analyzer.quality.gates import QualityGates

    config = {"quality": {"min_ads_for_pattern": 3}}
    gates = QualityGates(config)

    contents = [
        AdContent(
            ad_id=f"ad_{i}",
            brand="Test",
            ad_type=AdType.VIDEO,
            transcript="good transcript here",
            transcript_confidence=0.85,
            status=AdStatus.ANALYZED,
            word_count=50,
        )
        for i in range(5)
    ]

    analyses = [
        AdAnalysis(
            ad_id=f"ad_{i}",
            brand="Test",
            analysis_confidence=0.8,
            copy_quality_score=0.7,
        )
        for i in range(5)
    ]

    report = gates.run_checks(contents, analyses)
    assert report.passed is True
    assert report.total_ads_analyzed == 5


def test_quality_gates_fail_insufficient_ads():
    from meta_ads_analyzer.models import AdAnalysis, AdContent, AdStatus, AdType
    from meta_ads_analyzer.quality.gates import QualityGates

    config = {"quality": {"min_ads_for_pattern": 10}}
    gates = QualityGates(config)

    contents = [
        AdContent(
            ad_id="ad_1", brand="Test", ad_type=AdType.VIDEO, status=AdStatus.ANALYZED
        )
    ]
    analyses = [
        AdAnalysis(ad_id="ad_1", brand="Test", analysis_confidence=0.9, copy_quality_score=0.8)
    ]

    report = gates.run_checks(contents, analyses)
    assert report.passed is False
    assert any("CRITICAL" in i for i in report.issues)


def test_quality_gates_zero_results():
    from meta_ads_analyzer.quality.gates import QualityGates

    config = {"quality": {"min_ads_for_pattern": 10}}
    gates = QualityGates(config)
    report = gates.run_checks([], [])
    assert report.passed is False


# ── Copy quality checker tests ──


def test_copy_quality_good_transcript():
    from meta_ads_analyzer.quality.gates import CopyQualityChecker

    result = CopyQualityChecker.check_transcript_quality(
        "This is a really good transcript about the product that helps people "
        "sleep better at night by using a special blend of ingredients."
    )
    assert result["passed"] is True
    assert result["score"] > 0.5


def test_copy_quality_repetitive_transcript():
    from meta_ads_analyzer.quality.gates import CopyQualityChecker

    result = CopyQualityChecker.check_transcript_quality(
        " ".join(["yeah"] * 100)
    )
    assert result["passed"] is False
    assert any("repetition" in i.lower() for i in result["issues"])


def test_copy_quality_short_transcript():
    from meta_ads_analyzer.quality.gates import CopyQualityChecker

    result = CopyQualityChecker.check_transcript_quality("Hello world")
    assert result["score"] < 0.8
    assert any("short" in i.lower() for i in result["issues"])


# ── DB store tests ──


@pytest.mark.asyncio
async def test_db_store_roundtrip():
    """Test saving and loading data through SQLite store."""
    from meta_ads_analyzer.db.store import AdStore
    from meta_ads_analyzer.models import AdContent, AdStatus, AdType, ScrapedAd

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = AdStore(db_path=db_path)

        async with store:
            # Create run
            await store.create_run("run_1", "test query", "TestBrand", {"test": True})

            # Save scraped ad
            ad = ScrapedAd(
                ad_id="ad_1",
                page_name="TestBrand",
                ad_type=AdType.VIDEO,
                primary_text="Test ad copy",
            )
            await store.save_scraped_ad("run_1", ad)

            # Retrieve
            ads = await store.get_scraped_ads("run_1")
            assert len(ads) == 1
            assert ads[0].ad_id == "ad_1"

            # Save content
            content = AdContent(
                ad_id="ad_1",
                brand="TestBrand",
                ad_type=AdType.VIDEO,
                transcript="Transcript text",
                status=AdStatus.TRANSCRIBED,
            )
            await store.save_ad_content("run_1", content)

            contents = await store.get_ad_contents("run_1")
            assert len(contents) == 1
            assert contents[0].transcript == "Transcript text"

            # Stats
            stats = await store.get_run_stats("run_1")
            assert stats["scraped_ads"] == 1
            assert stats["ad_content"] == 1


# ── Config env override test ──


def test_config_env_override(monkeypatch):
    from meta_ads_analyzer.utils.config import load_config

    monkeypatch.setenv("META_ADS_SCRAPER_MAX_ADS", "200")
    config = load_config()
    assert config["scraper"]["max_ads"] == 200


# ── Report generation test ──


def test_report_markdown_generation():
    from meta_ads_analyzer.models import PatternReport, QualityReport

    report = PatternReport(
        search_query="Athletic Greens",
        brand="AG1",
        total_ads_analyzed=25,
        common_pain_points=[
            {"pain_point": "Low energy", "frequency": 18, "percentage": 0.72}
        ],
        key_insights=["72% of ads lead with energy as primary pain point"],
        executive_summary="AG1 consistently targets health-conscious adults.",
        quality_report=QualityReport(
            total_ads_scraped=100,
            total_ads_analyzed=25,
            passed=True,
        ),
    )

    assert report.search_query == "Athletic Greens"
    assert len(report.common_pain_points) == 1

    # Test JSON roundtrip
    data = report.model_dump(mode="json")
    restored = PatternReport.model_validate(data)
    assert restored.total_ads_analyzed == 25
