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
