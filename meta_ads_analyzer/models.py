"""Core data models for the Meta Ads Analyzer pipeline."""

from __future__ import annotations

import enum
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class AdType(str, enum.Enum):
    VIDEO = "video"
    STATIC = "static"
    CAROUSEL = "carousel"
    UNKNOWN = "unknown"


class ProductType(str, enum.Enum):
    """Product/service type classification for market filtering."""

    SUPPLEMENT = "supplement"
    DEVICE = "device"
    SERVICE = "service"
    SKINCARE = "skincare"
    TOOL = "tool"
    APPAREL = "apparel"
    SOFTWARE = "software"
    INFO_PRODUCT = "info_product"
    FOOD_BEVERAGE = "food_beverage"
    OTHER = "other"
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
    brand_name: Optional[str] = None  # Actual product/brand name extracted from ad copy
    ad_type: AdType = AdType.UNKNOWN
    product_type: ProductType = ProductType.UNKNOWN
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
    video_text_overlay: Optional[str] = None  # Text extracted from video frames via OCR
    media_path: Optional[Path] = None
    word_count: int = 0
    scrape_position: int = 0  # Inherited from ScrapedAd — Meta Ads Library order
    status: AdStatus = AdStatus.SCRAPED
    filter_reason: Optional[FilterReason] = None


class AdAnalysis(BaseModel):
    """Analysis result for a single ad."""

    ad_id: str
    brand: str
    brand_name: Optional[str] = None  # Actual product/brand name from ad copy

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
    brand_name: Optional[str] = None  # Actual product/brand name (may differ from page_name)
    ad_count: int = 0
    active_ad_count: int = 0
    recent_ad_count: int = 0  # ads launched in last 30 days
    total_impression_lower: int = 0
    max_impression_upper: int = 0
    earliest_launch: Optional[datetime] = None
    latest_launch: Optional[datetime] = None
    headlines: list[str] = Field(default_factory=list)
    relevance_score: int = 0  # composite ranking score


class PageType(str, enum.Enum):
    """Page type classification for brand networks."""

    BRANDED = "branded"  # Official brand page
    DOCTOR_AUTHORITY = "doctor_authority"  # Dr./MD credentialed page
    LIFESTYLE = "lifestyle"  # Lifestyle/wellness topic page
    NICHE_TOPIC = "niche_topic"  # Specific health topic page
    GENERIC = "generic"  # Generic product page
    UNKNOWN = "unknown"


class NetworkPage(BaseModel):
    """Single page within a brand network."""

    page_name: str
    page_id: Optional[str] = None
    page_type: PageType = PageType.UNKNOWN
    ad_count: int = 0
    primary_domain: Optional[str] = None
    signals: list[str] = Field(default_factory=list)  # Why grouped here


class PageNetwork(BaseModel):
    """Detected brand network spanning multiple pages."""

    network_name: str  # Derived brand name
    primary_page: str  # Main branded page
    pages: list[NetworkPage] = Field(default_factory=list)
    total_ads: int = 0
    unique_domains: list[str] = Field(default_factory=list)
    network_confidence: float = 0.0  # 0-1 confidence in grouping


class NetworkedAdvertiser(AdvertiserEntry):
    """Advertiser with network information."""

    network: Optional[PageNetwork] = None
    is_network: bool = False


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
    competition_level: str = "normal"  # normal / thin / blue_ocean
    blue_ocean_result: Optional[Any] = None  # BlueOceanResult (dict-serialized)


# ============================================================================
# Comparison Analysis Models (Session 3: Compare Command)
# ============================================================================


class DimensionCoverage(BaseModel):
    """Coverage data for one dimension value across brands."""

    dimension: str
    brands: dict[str, int]  # brand_name -> count
    coverage: int  # number of brands using this dimension
    coverage_percent: int
    total: int  # total ads across all brands using this dimension


class SaturationZone(BaseModel):
    """Saturation classification for a dimension type."""

    saturated: list[DimensionCoverage] = Field(default_factory=list)  # 60%+ coverage
    moderate: list[DimensionCoverage] = Field(default_factory=list)  # 30-59% coverage
    whitespace: list[DimensionCoverage] = Field(default_factory=list)  # <30% coverage


class BrandProfile(BaseModel):
    """Compact brand strategy profile for market map."""

    name: str
    activity: str
    primary_hook: str
    primary_angle: str
    primary_emotion: str
    primary_format: str
    primary_cta: str
    content_depth: str
    hook_diversity: int
    angle_diversity: int
    ads_analyzed: int


class MarketMap(BaseModel):
    """Cross-brand comparison map with dimension matrices."""

    meta: dict[str, Any]
    matrices: dict[str, list[DimensionCoverage]]  # 6 dimension types
    saturation: dict[str, SaturationZone]
    profiles: list[BrandProfile] = Field(default_factory=list)


class MarketGap(BaseModel):
    """Market-wide gap (dimension with 0% coverage)."""

    dimension: str
    opportunity: str = "wide_open"


class UnderexploitedOpportunity(BaseModel):
    """Proven but uncrowded strategy (1-2 brands, <30% coverage)."""

    category: str
    dimension: str
    used_by: list[str]
    coverage_percent: int
    total_ads: int


class PriorityEntry(BaseModel):
    """Ranked opportunity with P1/P2/P3/P4 tier."""

    category: str
    dimension: str
    gap_score: int
    coverage_percent: int
    brands_using: int
    priority_score: int
    tier: str  # P1_HIGH, P2_MEDIUM, P3_LOW, P4_MONITOR


class BrandGap(BaseModel):
    """Competitor strategy missing from focus brand."""

    category: str
    dimension: str
    competitors_using: list[str]
    competitor_count: int


class StrategicRecommendations(BaseModel):
    """Claude-enhanced strategic layer with deep competitive analysis."""

    market_narrative: Optional[str] = None
    root_cause_comparison: dict = Field(default_factory=dict)
    mechanism_comparison: dict = Field(default_factory=dict)
    proof_architecture_comparison: dict = Field(default_factory=dict)
    belief_installation_analysis: dict = Field(default_factory=dict)
    top_opportunities: list[dict] = Field(default_factory=list)
    contrarian_plays: list[dict] = Field(default_factory=list)
    what_not_to_do: list[str] = Field(default_factory=list)
    immediate_actions: list[dict] = Field(default_factory=list)  # Optional, may be removed


class LoopholeDocument(BaseModel):
    """Complete competitive gap analysis with priority matrix."""

    meta: dict[str, Any]
    market_gaps: dict[str, list[MarketGap]]
    saturation_zones: dict[str, list[dict]]
    underexploited: list[UnderexploitedOpportunity] = Field(default_factory=list)
    priority_matrix: list[PriorityEntry] = Field(default_factory=list)
    brand_gaps: Optional[list[BrandGap]] = None
    strategic_recommendations: Optional[StrategicRecommendations] = None


class CompareResult(BaseModel):
    """Complete comparison analysis result."""

    keyword: str
    market_map: MarketMap
    loophole_doc: LoopholeDocument
    generated_at: datetime = Field(default_factory=datetime.utcnow)
