"""Classifier — classifies ads as winners/average/losers with spend-weighted scoring.

Weight tiers:
- Pillar (spend_share > 10%): 3x weight
- Strong (spend_share 5-10%): 2x weight
- Normal (spend_share 1-5%): 1x weight
- Minor (spend_share < 1%): 0.5x weight
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .csv_matcher import MatchResult, MatchSummary


class Classification(Enum):
    WINNER = "winner"
    AVERAGE = "average"
    LOSER = "loser"
    UNTESTED = "untested"


class WeightTier(Enum):
    PILLAR = "pillar"
    STRONG = "strong"
    NORMAL = "normal"
    MINOR = "minor"


WEIGHT_MULTIPLIERS = {
    WeightTier.PILLAR: 3.0,
    WeightTier.STRONG: 2.0,
    WeightTier.NORMAL: 1.0,
    WeightTier.MINOR: 0.5,
}


@dataclass
class Thresholds:
    """User-configurable classification thresholds."""
    winner_roas: float = 2.0
    winner_min_spend: float = 100.0
    loser_roas: float = 1.0
    loser_min_spend: float = 100.0
    untested_max_spend: float = 100.0
    # Average is implicitly between loser_roas and winner_roas


@dataclass
class ClassifiedAd:
    """A matched ad with classification and weight data."""
    match: MatchResult
    classification: Classification = Classification.UNTESTED
    weight_tier: WeightTier = WeightTier.MINOR
    weight_multiplier: float = 0.5
    spend_share: float = 0.0  # % of total account spend
    value_score: float = 0.0  # spend * ROAS (revenue proxy)


@dataclass
class ClassificationResult:
    """Full classification results."""
    all_classified: list[ClassifiedAd] = field(default_factory=list)
    winners: list[ClassifiedAd] = field(default_factory=list)
    average: list[ClassifiedAd] = field(default_factory=list)
    losers: list[ClassifiedAd] = field(default_factory=list)
    untested: list[ClassifiedAd] = field(default_factory=list)
    total_account_spend: float = 0.0
    thresholds: Optional[Thresholds] = None

    # Counts by weight tier within winners
    pillar_winners: int = 0
    strong_winners: int = 0
    normal_winners: int = 0
    minor_winners: int = 0


def _determine_weight_tier(spend_share: float) -> WeightTier:
    """Determine weight tier based on spend share."""
    if spend_share > 0.10:
        return WeightTier.PILLAR
    elif spend_share > 0.05:
        return WeightTier.STRONG
    elif spend_share > 0.01:
        return WeightTier.NORMAL
    else:
        return WeightTier.MINOR


def classify_ads(
    match_summary: MatchSummary,
    thresholds: Optional[Thresholds] = None,
) -> ClassificationResult:
    """Classify all matched ads with weighted scoring.

    Args:
        match_summary: Output from csv_matcher.match_tasks_to_csv
        thresholds: User-set thresholds (uses defaults if None)
    """
    if thresholds is None:
        thresholds = Thresholds()

    total_spend = match_summary.total_account_spend
    result = ClassificationResult(
        total_account_spend=total_spend,
        thresholds=thresholds,
    )

    for match in match_summary.matched:
        # Calculate spend share
        spend_share = match.total_spend / total_spend if total_spend > 0 else 0

        # Determine weight tier
        weight_tier = _determine_weight_tier(spend_share)
        weight_multiplier = WEIGHT_MULTIPLIERS[weight_tier]

        # Calculate value score
        value_score = match.total_spend * match.weighted_roas

        # Classify
        if match.total_spend < thresholds.untested_max_spend:
            classification = Classification.UNTESTED
        elif match.weighted_roas >= thresholds.winner_roas and match.total_spend >= thresholds.winner_min_spend:
            classification = Classification.WINNER
        elif match.weighted_roas <= thresholds.loser_roas and match.total_spend >= thresholds.loser_min_spend:
            classification = Classification.LOSER
        else:
            classification = Classification.AVERAGE

        classified = ClassifiedAd(
            match=match,
            classification=classification,
            weight_tier=weight_tier,
            weight_multiplier=weight_multiplier,
            spend_share=spend_share,
            value_score=value_score,
        )

        result.all_classified.append(classified)

        if classification == Classification.WINNER:
            result.winners.append(classified)
        elif classification == Classification.AVERAGE:
            result.average.append(classified)
        elif classification == Classification.LOSER:
            result.losers.append(classified)
        else:
            result.untested.append(classified)

    # Sort by value score (highest first)
    result.winners.sort(key=lambda x: x.value_score, reverse=True)
    result.losers.sort(key=lambda x: x.value_score, reverse=True)
    result.average.sort(key=lambda x: x.value_score, reverse=True)

    # Count weight tiers in winners
    result.pillar_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.PILLAR)
    result.strong_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.STRONG)
    result.normal_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.NORMAL)
    result.minor_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.MINOR)

    return result
