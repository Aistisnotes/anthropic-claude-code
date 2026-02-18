"""Strategic dimension models for DR-focused comparison analysis.

This module defines the 6 core dimensions that drive direct response results:
1. Root Causes - What each brand claims causes the problem
2. Mechanisms - What/how each brand claims to fix it
3. Target Audience - Who each brand speaks to
4. Pain Points - Specific problems each brand leads with
5. Pain Point Symptoms - Daily experiences/symptoms referenced
6. Mass Desires - Transformation/outcome promised
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RootCausePattern(BaseModel):
    """Root cause explanation pattern across brands."""

    text: str  # The root cause explanation
    depth_level: str  # surface/moderate/deep/cellular/molecular
    upstream_gap: str = ""  # What causes THIS root cause (missing upstream)
    frequency: int = 0  # How many ads reference this
    brands_using: list[str] = Field(default_factory=list)
    example_ad_copy: str = ""  # Direct quote from ad
    psychological_principle: str = ""  # System 1, villain externalization, etc.


class MechanismPattern(BaseModel):
    """Unique mechanism pattern across brands."""

    text: str  # The mechanism explanation
    mechanism_type: str = "new_mechanism"  # new_mechanism/new_information/new_identity
    depth: str = "process-level"  # claim-only/process-level/cellular/molecular
    frequency: int = 0
    brands_using: list[str] = Field(default_factory=list)
    example_ad_copy: str = ""
    believability_score: float = 0.0  # 0-1, how credible the mechanism feels
    connects_to_root_cause: bool = False  # Does it directly solve the root cause?


class TargetAudiencePattern(BaseModel):
    """Target audience/avatar pattern across brands."""

    demographics: str = ""  # Age, gender, location, income level
    psychographics: str = ""  # Values, lifestyle, concerns, aspirations
    identity: str = ""  # "People who are...", tribal belonging
    frequency: int = 0
    brands_using: list[str] = Field(default_factory=list)
    example_ad_copy: str = ""


class PainPointPattern(BaseModel):
    """Pain point pattern across brands."""

    pain_point: str  # Specific problem (e.g., "crepey skin on arms")
    intensity: str = "medium"  # low/medium/high/extreme
    frequency: int = 0
    brands_using: list[str] = Field(default_factory=list)
    example_ad_copy: str = ""
    emotional_trigger: str = ""  # fear, shame, frustration, anxiety


class SymptomPattern(BaseModel):
    """Pain point symptom pattern (daily experiences)."""

    symptom: str  # Observable symptom (e.g., "waking up with puffy face")
    frequency: int = 0
    brands_using: list[str] = Field(default_factory=list)
    example_ad_copy: str = ""


class MassDesirePattern(BaseModel):
    """Mass desire/transformation pattern across brands."""

    desire: str  # The transformation promised
    timeframe: str = ""  # "in 30 days", "overnight", etc.
    specificity: str = "vague"  # vague/moderate/specific/measurable
    frequency: int = 0
    brands_using: list[str] = Field(default_factory=list)
    example_ad_copy: str = ""


class StrategicDimensions(BaseModel):
    """Complete 6-dimension analysis for a single brand or market."""

    root_causes: list[RootCausePattern] = Field(default_factory=list)
    mechanisms: list[MechanismPattern] = Field(default_factory=list)
    target_audiences: list[TargetAudiencePattern] = Field(default_factory=list)
    pain_points: list[PainPointPattern] = Field(default_factory=list)
    symptoms: list[SymptomPattern] = Field(default_factory=list)
    mass_desires: list[MassDesirePattern] = Field(default_factory=list)


class DimensionComparison(BaseModel):
    """Comparison of one dimension type across all brands in market."""

    dimension_type: str  # root_causes, mechanisms, etc.
    pattern_1: dict  # Most common pattern with brands, frequency, example
    pattern_2: dict = Field(default_factory=dict)  # Second most common
    pattern_3: dict = Field(default_factory=dict)  # Third if exists
    how_patterns_differ: str = ""  # Narrative explanation of differences
    loopholes: list[str] = Field(default_factory=list)  # Opportunities for focus brand


class MarketSophisticationLevel(BaseModel):
    """Market sophistication assessment per Eugene Schwartz."""

    stage: int  # 1-5 (Stage 1 = first to market, Stage 5 = complete sophistication)
    stage_name: str  # e.g., "Stage 3 - Market Saturation"
    evidence: str  # Why we classified it at this stage
    strategic_response: str  # new_mechanism/new_information/new_identity
    response_rationale: str  # Why this response works at this stage


class LoopholeOpportunity(BaseModel):
    """Complete loophole as arbitrage opportunity (High TAM + Low Competition + Believable)."""

    loophole_id: str  # L1, L2, etc.
    title: str  # Short title (e.g., "The Hormonal Trigger Nobody Explains")

    # THE GAP
    the_gap: str  # What's missing from the market? Detailed explanation

    # WHY IT'S MASSIVE (TAM + Competition)
    tam_size: str  # large/medium/small
    tam_rationale: str  # Why the audience is large
    meta_competition: str  # none/low/medium
    meta_competition_evidence: str  # Proof of low competition
    believability_score: float = 0.0  # 0-1, how credible this angle feels

    # EXECUTION STRATEGY (combines all 6 dimensions)
    root_cause: str  # Specific root cause to lead with
    mechanism: str  # Specific mechanism to position
    target_avatar: str  # Specific avatar (demographics + psychographics)
    pain_point: str  # Primary pain point to agitate
    symptoms: list[str] = Field(default_factory=list)  # Specific symptoms to reference
    mass_desire: str  # Transformation promise

    # MARKET SOPHISTICATION RESPONSE
    sophistication_response: str  # new_mechanism/new_information/new_identity
    response_rationale: str  # Why this response works

    # TACTICAL EXECUTION
    hook_examples: list[str] = Field(default_factory=list)  # 3-5 specific hook examples
    proof_strategy: str = ""  # What proof to provide
    objection_handling: str = ""  # Key objections to address

    # SCORING
    priority_score: int = 0  # 0-100 composite score
    effort_level: str = "medium"  # low/medium/high
    timeline: str = ""  # "Launch in 2 weeks", "Requires R&D - 8 weeks"
    risk_level: str = "medium"  # low/medium/high
    defensibility: str = ""  # Why this is hard for competitors to copy


class StrategicMarketMap(BaseModel):
    """Complete market map with 6 strategic dimensions."""

    meta: dict  # keyword, brands_compared, generated_at
    sophistication_level: MarketSophisticationLevel

    # 6 dimension comparisons
    root_cause_comparison: DimensionComparison
    mechanism_comparison: DimensionComparison
    audience_comparison: DimensionComparison
    pain_point_comparison: DimensionComparison
    symptom_comparison: DimensionComparison
    desire_comparison: DimensionComparison

    # Brand-level summaries
    brand_summaries: list[dict] = Field(default_factory=list)

    # Root Cause x Mechanism matrix
    root_cause_mechanism_matrix: list[dict] = Field(default_factory=list)


class StrategicLoopholeDocument(BaseModel):
    """Complete loophole document with 5-7 execution-ready strategies."""

    meta: dict  # keyword, focus_brand, brands_compared, generated_at

    # Market-level analysis
    market_narrative: str = ""  # 3-5 paragraph overview
    sophistication_assessment: MarketSophisticationLevel

    # Validated loopholes (5-7 complete strategies)
    loopholes: list[LoopholeOpportunity] = Field(default_factory=list)

    # Competitive landscape table
    competitive_landscape: list[dict] = Field(default_factory=list)

    # What NOT to do
    what_not_to_do: list[str] = Field(default_factory=list)


class BlueOceanAdConcept(BaseModel):
    """A single ad concept for blue ocean execution."""

    title: str
    hook: str
    angle: str
    root_cause: str
    mechanism: str
    why_it_works: str


class BlueOceanWeekPlan(BaseModel):
    """Week in the blue ocean testing roadmap."""

    week: str  # "Week 1", "Weeks 2-3", etc.
    focus: str
    actions: list[str] = Field(default_factory=list)


class BlueOceanResult(BaseModel):
    """Report when no brands have 50+ qualifying ads in the market."""

    keyword: str
    focus_brand: Optional[str] = None
    generated_at: str = ""  # ISO datetime string

    # Finding
    brands_scanned: int = 0
    max_qualifying_ads: int = 0
    brand_ad_counts: list[dict] = Field(default_factory=list)  # [{brand, qualifying_ads}]

    # Market summary (Claude-generated)
    blue_ocean_summary: str = ""

    # Focus brand analysis (populated if focus_brand specified)
    focus_brand_ads_analyzed: int = 0
    focus_brand_root_causes: list[str] = Field(default_factory=list)
    focus_brand_mechanisms: list[str] = Field(default_factory=list)
    focus_brand_avatar: str = ""
    focus_brand_top_pain_points: list[str] = Field(default_factory=list)
    focus_brand_strengths: list[str] = Field(default_factory=list)
    focus_brand_gaps: list[str] = Field(default_factory=list)

    # Strategy (Claude-generated)
    execution_recommendations: list[str] = Field(default_factory=list)
    first_5_ad_concepts: list[BlueOceanAdConcept] = Field(default_factory=list)
    testing_roadmap: list[BlueOceanWeekPlan] = Field(default_factory=list)

    # Adjacent market insights
    adjacent_keywords: list[dict] = Field(default_factory=list)  # [{keyword, brands_with_50_plus, max_ads, has_competition}]
    adjacent_insights: str = ""


class StrategicCompareResult(BaseModel):
    """Complete strategic comparison result."""

    keyword: str
    market_map: Optional[StrategicMarketMap] = None
    loophole_doc: Optional[StrategicLoopholeDocument] = None
    blue_ocean_result: Optional[BlueOceanResult] = None
    competition_level: str = "normal"  # normal / thin / blue_ocean
