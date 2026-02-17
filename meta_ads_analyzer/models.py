"""Core data models for the Meta Ads Analyzer pipeline."""

from __future__ import annotations

import enum
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class AdType(str, enum.Enum):
    VIDEO = "video"
    STATIC = "static"
    CAROUSEL = "carousel"
    UNKNOWN = "unknown"


class AdStatus(str, enum.Enum):
    SCRAPED = "scraped"
    DOWNLOADED = "downloaded"
    TRANSCRIBED = "transcribed"
    FILTERED_OUT = "filtered_out"
    ANALYZED = "analyzed"
    FAILED = "failed"


class FilterReason(str, enum.Enum):
    SHORT_COPY = "primary_copy_under_500_words"
    LOW_QUALITY_TRANSCRIPT = "low_quality_transcript"
    DOWNLOAD_FAILED = "download_failed"
    TRANSCRIPTION_FAILED = "transcription_failed"
    DUPLICATE = "duplicate"


class Priority(str, enum.Enum):
    """Ad priority classification for selection engine."""

    P1_ACTIVE_WINNER = "p1_active_winner"
    P2_PROVEN_RECENT = "p2_proven_recent"
    P3_STRATEGIC_DIRECTION = "p3_strategic_direction"
    P4_RECENT_MODERATE = "p4_recent_moderate"


class SkipReason(str, enum.Enum):
    """Reasons an ad is skipped during selection."""

    NO_LAUNCH_DATE = "no_launch_date"
    LEGACY_AUTOPILOT = "legacy_autopilot"
    FAILED_TEST = "failed_test"
    THIN_TEXT = "thin_text"
    BELOW_THRESHOLD = "below_threshold"
    DUPLICATE = "duplicate"


class ScrapedAd(BaseModel):
    """Raw ad data as scraped from Meta Ads Library."""

    ad_id: str
    page_name: str
    page_id: Optional[str] = None
    ad_type: AdType = AdType.UNKNOWN
    primary_text: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    cta_text: Optional[str] = None
    link_url: Optional[str] = None
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    started_running: Optional[str] = None
    platforms: list[str] = Field(default_factory=list)
    scrape_position: int = 0  # Order on Meta Ads Library page (0-indexed, sorted by impressions)
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    # Impression and spend data (Meta returns these as ranges like "10K-50K")
    impression_lower: int = 0
    impression_upper: Optional[int] = None
    spend_lower: float = 0.0
    spend_upper: Optional[float] = None
    spend_currency: str = "USD"

    @property
    def max_primary_text_words(self) -> int:
        """Word count for selection filtering."""
        if not self.primary_text:
            return 0
        return len(self.primary_text.strip().split())


class DownloadedMedia(BaseModel):
    """Info about downloaded media file."""

    ad_id: str
    file_path: Path
    file_size_bytes: int
    duration_seconds: Optional[float] = None
    mime_type: Optional[str] = None


class Transcript(BaseModel):
    """Transcription result for a video ad."""

    ad_id: str
    text: str
    language: str = "en"
    confidence: float = 0.0
    word_count: int = 0
    segments: list[TranscriptSegment] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


# Rebuild Transcript to resolve forward ref
Transcript.model_rebuild()


class AdContent(BaseModel):
    """Unified ad content ready for analysis. This is the input to the analyzer."""

    ad_id: str
    brand: str
    ad_type: AdType
    primary_text: Optional[str] = None
    headline: Optional[str] = None
    transcript: Optional[str] = None
    transcript_confidence: float = 0.0
    media_path: Optional[Path] = None
    word_count: int = 0
    scrape_position: int = 0  # Inherited from ScrapedAd — Meta Ads Library order
    status: AdStatus = AdStatus.SCRAPED
    filter_reason: Optional[FilterReason] = None


class AdAnalysis(BaseModel):
    """Analysis result for a single ad."""

    ad_id: str
    brand: str

    # Target customer
    target_customer_profile: str = ""
    target_demographics: str = ""
    target_psychographics: str = ""

    # Pain architecture
    pain_points: list[str] = Field(default_factory=list)
    pain_point_symptoms: list[str] = Field(default_factory=list)
    root_cause: str = ""
    root_cause_chain: list[str] = Field(default_factory=list)
    root_cause_depth: str = ""  # surface / moderate / deep / cellular

    # Mechanism & delivery
    mechanism: str = ""
    mechanism_depth: str = ""  # claim-only / process-level / cellular-molecular
    product_delivery_mechanism: str = ""

    # Proof architecture
    proof_elements: list[str] = Field(default_factory=list)
    proof_gaps: list[str] = Field(default_factory=list)

    # Belief & objection architecture
    beliefs_installed: list[str] = Field(default_factory=list)
    beliefs_missing: list[str] = Field(default_factory=list)
    objections_handled: list[str] = Field(default_factory=list)
    objections_open: list[str] = Field(default_factory=list)

    # Ingredient / component transparency
    ingredient_transparency: str = ""
    ingredient_transparency_score: float = 0.0  # 0-10

    # Unfalsifiability
    unfalsifiability_techniques: list[str] = Field(default_factory=list)
    unfalsifiability_cracks: list[str] = Field(default_factory=list)

    # Desire & idea
    mass_desire: str = ""
    big_idea: str = ""

    # Meta
    ad_angle: str = ""
    emotional_triggers: list[str] = Field(default_factory=list)
    emotional_sequence: list[str] = Field(default_factory=list)
    awareness_level: str = ""
    sophistication_level: str = ""
    hook_type: str = ""
    hook_psychology: str = ""
    cta_strategy: str = ""

    # Quality
    analysis_confidence: float = 0.0
    copy_quality_score: float = 0.0

    raw_llm_response: Optional[str] = None


class QualityReport(BaseModel):
    """Quality gate results before pattern analysis."""

    total_ads_scraped: int = 0
    total_ads_downloaded: int = 0
    total_ads_transcribed: int = 0
    total_ads_filtered_out: int = 0
    total_ads_analyzed: int = 0
    avg_transcript_confidence: float = 0.0
    avg_analysis_confidence: float = 0.0
    avg_copy_quality_score: float = 0.0
    min_ads_for_pattern: int = 10
    passed: bool = False
    issues: list[str] = Field(default_factory=list)


class PatternReport(BaseModel):
    """Final pattern analysis across all analyzed ads for a brand/search."""

    search_query: str
    brand: Optional[str] = None
    total_ads_analyzed: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    # Patterns (legacy, still populated)
    common_pain_points: list[dict] = Field(default_factory=list)
    common_symptoms: list[dict] = Field(default_factory=list)
    root_cause_patterns: list[dict] = Field(default_factory=list)
    mechanism_patterns: list[dict] = Field(default_factory=list)
    delivery_mechanism_patterns: list[dict] = Field(default_factory=list)
    mass_desire_patterns: list[dict] = Field(default_factory=list)
    big_idea_patterns: list[dict] = Field(default_factory=list)
    target_customer_patterns: list[dict] = Field(default_factory=list)
    emotional_trigger_patterns: list[dict] = Field(default_factory=list)
    hook_patterns: list[dict] = Field(default_factory=list)
    awareness_level_distribution: dict = Field(default_factory=dict)

    # NEW: Explicit dimension distributions for compare command
    angle_distribution: dict[str, int] = Field(default_factory=dict)
    format_distribution: dict[str, int] = Field(default_factory=dict)
    offer_distribution: dict[str, int] = Field(default_factory=dict)
    cta_distribution: dict[str, int] = Field(default_factory=dict)

    # Deep analysis: gaps and weaknesses
    competitive_verdict: str = ""
    root_cause_gaps: list[dict] = Field(default_factory=list)
    mechanism_gaps: list[dict] = Field(default_factory=list)
    proof_gaps: list[dict] = Field(default_factory=list)
    belief_gaps: list[dict] = Field(default_factory=list)
    objection_gaps: list[dict] = Field(default_factory=list)
    ingredient_transparency_analysis: dict = Field(default_factory=dict)
    unfalsifiability_analysis: dict = Field(default_factory=dict)

    # Loopholes: exploitable weaknesses with scoring
    loopholes: list[dict] = Field(default_factory=list)

    # Execution guidance
    priority_matrix: list[dict] = Field(default_factory=list)
    what_not_to_do: list[str] = Field(default_factory=list)

    # Summary
    executive_summary: str = ""
    key_insights: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    # Quality
    quality_report: Optional[QualityReport] = None
    full_report_markdown: str = ""


class AdvertiserEntry(BaseModel):
    """Aggregated advertiser data from scan."""

    page_id: Optional[str] = None
    page_name: str
    ad_count: int = 0
    active_ad_count: int = 0
    recent_ad_count: int = 0  # ads launched in last 30 days
    total_impression_lower: int = 0
    max_impression_upper: int = 0
    earliest_launch: Optional[datetime] = None
    latest_launch: Optional[datetime] = None
    headlines: list[str] = Field(default_factory=list)
    relevance_score: int = 0  # composite ranking score


class ClassifiedAd(BaseModel):
    """An ad with priority classification applied."""

    ad: ScrapedAd
    priority: Optional[Priority] = None
    priority_label: str = "SKIP"
    skip_reason: Optional[SkipReason] = None
    days_since_launch: Optional[int] = None


class SelectionStats(BaseModel):
    """Statistics from ad selection process."""

    total_scanned: int = 0
    total_selected: int = 0
    total_skipped: int = 0
    duplicates_removed: int = 0
    by_priority: dict[str, int] = Field(default_factory=dict)
    skip_reasons: dict[str, int] = Field(default_factory=dict)


class SelectionResult(BaseModel):
    """Result from selectAds() function."""

    selected: list[ClassifiedAd] = Field(default_factory=list)
    skipped: list[ClassifiedAd] = Field(default_factory=list)
    stats: SelectionStats = Field(default_factory=SelectionStats)


class ScanResult(BaseModel):
    """Complete scan result with advertiser rankings."""

    keyword: str
    country: str = "US"
    scan_date: datetime = Field(default_factory=datetime.utcnow)
    ads: list[ScrapedAd] = Field(default_factory=list)
    advertisers: list[AdvertiserEntry] = Field(default_factory=list)
    total_fetched: int = 0
    pages_scanned: int = 0

    # Optional: selection results if --select flag used
    selection: Optional[SelectionResult] = None


class BrandSelection(BaseModel):
    """Selected brand with chosen ads for analysis."""

    advertiser: AdvertiserEntry
    selected_ads: list[ClassifiedAd]
    selection_stats: SelectionStats


class BrandReport(BaseModel):
    """Per-brand analysis report for market research."""

    advertiser: AdvertiserEntry
    keyword: str
    selection_stats: SelectionStats
    pattern_report: PatternReport
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class MarketResult(BaseModel):
    """Complete market research result."""

    keyword: str
    country: str
    scan_date: datetime
    total_advertisers: int
    brands_analyzed: int
    brand_reports: list[BrandReport] = Field(default_factory=list)
