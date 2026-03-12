"""Pattern Analyzer — Claude-powered weighted pattern analysis across winners vs losers.

Sends all classified scripts to Claude with their weight tiers.
Pillar ad patterns count 3x more than minor ad patterns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .classifier import ClassificationResult, ClassifiedAd, WeightTier
from .script_reader import ScriptContent


@dataclass
class PatternInsight:
    """A single pattern insight from analysis."""
    category: str  # e.g., "pain_points", "hooks", "root_cause_depth"
    pattern: str
    frequency: int  # how many ads exhibit this
    weighted_frequency: float  # frequency adjusted by weight
    supporting_ads: list[str] = field(default_factory=list)
    avg_roas: float = 0.0
    total_spend: float = 0.0


@dataclass
class PatternAnalysis:
    """Complete pattern analysis results."""
    winner_patterns: dict[str, list[PatternInsight]] = field(default_factory=dict)
    loser_patterns: dict[str, list[PatternInsight]] = field(default_factory=dict)
    cross_insights: list[str] = field(default_factory=list)
    raw_analysis: str = ""  # Full Claude response


def _build_ad_summary(
    classified: ClassifiedAd,
    script: ScriptContent | None,
) -> dict[str, Any]:
    """Build a summary dict for one ad to send to Claude."""
    summary: dict[str, Any] = {
        "task_name": classified.match.task.name,
        "classification": classified.classification.value,
        "weight_tier": classified.weight_tier.value,
        "weight_multiplier": classified.weight_multiplier,
        "spend": round(classified.match.total_spend, 2),
        "spend_share": f"{classified.spend_share * 100:.1f}%",
        "roas": round(classified.match.weighted_roas, 2),
        "value_score": round(classified.value_score, 2),
    }
    if script and not script.no_content_found:
        summary.update({
            "hooks": script.hooks,
            "body_copy": script.body_copy[:500] if script.body_copy else "",
            "pain_point": script.pain_point,
            "symptoms": script.symptoms,
            "root_cause": script.root_cause,
            "root_cause_depth": script.root_cause_depth,
            "mechanism_ump": script.mechanism_ump,
            "mechanism_ums": script.mechanism_ums,
            "avatar": script.avatar,
            "ad_format": script.ad_format,
            "awareness_level": script.awareness_level,
            "emotional_triggers": script.emotional_triggers,
            "language_patterns": script.language_patterns,
            "cta_type": script.cta_type,
            "lead_type": script.lead_type,
        })
    return summary


PATTERN_ANALYSIS_PROMPT = """You are analyzing ad creative performance data to find patterns in winners vs losers.

IMPORTANT: Weight tiers determine how much each ad's patterns should influence your analysis:
- Pillar (3x weight): These ads take >10% of total account spend. Their patterns are the MOST important.
- Strong (2x weight): 5-10% of spend. Very significant.
- Normal (1x weight): 1-5% of spend. Standard significance.
- Minor (0.5x weight): <1% of spend. Low significance — could be noise.

WINNER ADS (sorted by value score):
{winners_json}

LOSER ADS (sorted by spend — high-spend losers = expensive mistakes):
{losers_json}

AVERAGE ADS:
{average_json}

Analyze the data and provide your response in EXACTLY this structure:

## WINNER PATTERNS (weighted by spend significance)

### Pain Points
[Which pain points appear in highest-weighted winners? Be specific.]

### Root Cause Depth
[Which root cause depth works? surface vs cellular vs molecular — with spend data]

### Mechanisms (UMP/UMS)
[Which mechanism patterns resonate? What UMP/UMS combinations drive results?]

### Avatars
[Which avatar types convert? Specific habits, life patterns mentioned]

### Awareness Levels
[Which awareness levels perform? With ROAS and spend data]

### Hooks
[Specific hook patterns from top-weighted winners. Quote actual hooks when possible.]

### Ad Formats
[Which formats work? UGC, AI, VSL, etc. with performance data]

### Concept Levels
[Which concept levels (L1-L5) perform?]

### Emotional Triggers
[Which emotional triggers appear in weighted winners?]

### Language Patterns
[Specific phrases/patterns that appear in winners but NOT losers]

### Lead Types
[Which lead types convert? story, problem-solution, testimonial, etc.]

### Symptoms
[Which symptoms resonate vs which don't?]

## LOSER PATTERNS (weighted — focus on expensive mistakes)

### High-Spend Losers
[What do the HIGHEST-spend losers share? These are the most expensive mistakes.]

### Common Mistakes
[Wrong depth, wrong avatar, wrong awareness level patterns]

### What to STOP Immediately
[Clear recommendations on what to stop doing, based on loser patterns]

## CROSS-PATTERN INSIGHTS

[Provide 5-8 specific, data-backed cross-pattern insights. Format each as:]
- "[Pattern description]" — [Supporting data: which ads, ROAS, spend figures]

Examples of good insights:
- "Molecular root cause ads averaged 2.3x ROAS at $45k combined spend vs surface-level at 0.8x ROAS at $12k spend"
- "Top 3 pillar ads all use [specific pattern]"
- "[Language pattern] appeared in 4/5 pillar winners, 0/8 losers"
- "UGC format drives 40% of revenue from 25% of spend"

Be specific. Use actual numbers from the data. Reference specific ads by name when relevant."""


def analyze_patterns(
    classification: ClassificationResult,
    scripts: dict[str, ScriptContent],  # task_id → ScriptContent
) -> PatternAnalysis:
    """Run Claude-powered pattern analysis across all classified ads.

    Args:
        classification: Output from classifier.classify_ads
        scripts: Dict mapping task_id → ScriptContent
    """
    # Build summaries for each category
    winner_summaries = []
    for ad in classification.winners:
        script = scripts.get(ad.match.task.task_id)
        winner_summaries.append(_build_ad_summary(ad, script))

    loser_summaries = []
    for ad in classification.losers:
        script = scripts.get(ad.match.task.task_id)
        loser_summaries.append(_build_ad_summary(ad, script))

    average_summaries = []
    for ad in classification.average:
        script = scripts.get(ad.match.task.task_id)
        average_summaries.append(_build_ad_summary(ad, script))

    # Build prompt
    prompt = PATTERN_ANALYSIS_PROMPT.format(
        winners_json=json.dumps(winner_summaries, indent=2, default=str),
        losers_json=json.dumps(loser_summaries, indent=2, default=str),
        average_json=json.dumps(average_summaries, indent=2, default=str),
    )

    # Call Claude
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_analysis = message.content[0].text

    return PatternAnalysis(
        raw_analysis=raw_analysis,
        winner_patterns={},  # Raw text is the primary output
        loser_patterns={},
        cross_insights=_extract_cross_insights(raw_analysis),
    )


def _extract_cross_insights(raw_analysis: str) -> list[str]:
    """Extract cross-pattern insights from the raw analysis text."""
    insights: list[str] = []
    in_cross_section = False

    for line in raw_analysis.split("\n"):
        line = line.strip()
        if "CROSS-PATTERN INSIGHTS" in line.upper():
            in_cross_section = True
            continue
        if in_cross_section and line.startswith("- "):
            insights.append(line[2:].strip())
        elif in_cross_section and line.startswith("#"):
            break  # Next section

    return insights
