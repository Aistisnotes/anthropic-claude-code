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
    winner_roas: float = 1.5
    winner_min_spend: float = 500.0
    loser_roas: float = 0.8
    loser_min_spend: float = 500.0
    untested_max_spend: float = 100.0


@dataclass
class ClassifiedAd:
    """A matched ad with classification and weight data."""
    match: MatchResult
    classification: Classification = Classification.UNTESTED
    weight_tier: WeightTier = WeightTier.MINOR
    weight_multiplier: float = 0.5
    spend_share: float = 0.0
    value_score: float = 0.0


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
    classification_log: list[str] = field(default_factory=list)

    pillar_winners: int = 0
    strong_winners: int = 0
    normal_winners: int = 0
    minor_winners: int = 0


def _determine_weight_tier(spend_share: float) -> WeightTier:
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

    Uses thresholds for winner/loser/untested classification.
    Logs every classification decision for debugging.
    """
    if thresholds is None:
        thresholds = Thresholds()

    total_spend = match_summary.total_account_spend
    result = ClassificationResult(
        total_account_spend=total_spend,
        thresholds=thresholds,
    )

    log = result.classification_log
    log.append(f"=== CLASSIFICATION START ===")
    log.append(f"Total account spend: ${total_spend:,.0f}")
    log.append(f"Thresholds: Winner ROAS>={thresholds.winner_roas} AND Spend>=${thresholds.winner_min_spend}")
    log.append(f"Thresholds: Loser ROAS<={thresholds.loser_roas} AND Spend>={thresholds.loser_min_spend}")
    log.append(f"Thresholds: Untested Spend<{thresholds.untested_max_spend}")
    log.append(f"Matched ads to classify: {len(match_summary.matched)}")
    log.append("---")

    for match in match_summary.matched:
        spend_share = match.total_spend / total_spend if total_spend > 0 else 0
        weight_tier = _determine_weight_tier(spend_share)
        weight_multiplier = WEIGHT_MULTIPLIERS[weight_tier]
        value_score = match.total_spend * match.weighted_roas

        # Classification logic with detailed reason tracking
        if match.total_spend < thresholds.untested_max_spend:
            classification = Classification.UNTESTED
            reason = f"Spend ${match.total_spend:,.0f} < untested threshold ${thresholds.untested_max_spend:,.0f}"
        elif match.weighted_roas >= thresholds.winner_roas and match.total_spend >= thresholds.winner_min_spend:
            classification = Classification.WINNER
            reason = f"ROAS {match.weighted_roas:.2f} >= {thresholds.winner_roas} AND Spend ${match.total_spend:,.0f} >= ${thresholds.winner_min_spend:,.0f}"
        elif match.weighted_roas <= thresholds.loser_roas and match.total_spend >= thresholds.loser_min_spend:
            classification = Classification.LOSER
            reason = f"ROAS {match.weighted_roas:.2f} <= {thresholds.loser_roas} AND Spend ${match.total_spend:,.0f} >= ${thresholds.loser_min_spend:,.0f}"
        else:
            classification = Classification.AVERAGE
            # Explain WHY it's average
            reasons = []
            if match.weighted_roas > thresholds.loser_roas and match.weighted_roas < thresholds.winner_roas:
                reasons.append(f"ROAS {match.weighted_roas:.2f} between {thresholds.loser_roas} and {thresholds.winner_roas}")
            elif match.weighted_roas >= thresholds.winner_roas and match.total_spend < thresholds.winner_min_spend:
                reasons.append(f"ROAS {match.weighted_roas:.2f} qualifies as winner BUT Spend ${match.total_spend:,.0f} < min ${thresholds.winner_min_spend:,.0f}")
            elif match.weighted_roas <= thresholds.loser_roas and match.total_spend < thresholds.loser_min_spend:
                reasons.append(f"ROAS {match.weighted_roas:.2f} qualifies as loser BUT Spend ${match.total_spend:,.0f} < min ${thresholds.loser_min_spend:,.0f}")
            reason = "; ".join(reasons) if reasons else f"ROAS {match.weighted_roas:.2f}, Spend ${match.total_spend:,.0f} — doesn't meet winner or loser criteria"

        log.append(
            f"{classification.value.upper()}: '{match.task.name[:50]}' — "
            f"ROAS={match.weighted_roas:.2f}, Spend=${match.total_spend:,.0f}, "
            f"Share={spend_share*100:.1f}%, Tier={weight_tier.value} — {reason}"
        )

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

    # Sort
    result.winners.sort(key=lambda x: x.value_score, reverse=True)
    result.losers.sort(key=lambda x: x.value_score, reverse=True)
    result.average.sort(key=lambda x: x.value_score, reverse=True)

    # Count weight tiers
    result.pillar_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.PILLAR)
    result.strong_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.STRONG)
    result.normal_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.NORMAL)
    result.minor_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.MINOR)

    log.append("---")
    log.append(f"TOTALS: {len(result.winners)} winners, {len(result.average)} average, {len(result.losers)} losers, {len(result.untested)} untested")
    log.append(f"=== CLASSIFICATION END ===")

    return result


def classify_top50(
    match_summary: MatchSummary,
    winner_roas: float = 1.5,
    loser_roas: float = 0.8,
) -> ClassificationResult:
    """Classify top 50 ads by ROAS only — NO spend minimum.

    These are already the top spenders, so spend thresholds don't apply.
    No untested category either — all top 50 have significant spend.
    """
    total_spend = match_summary.total_account_spend
    result = ClassificationResult(total_account_spend=total_spend)

    log = result.classification_log
    log.append(f"=== TOP 50 CLASSIFICATION (ROAS-only) ===")
    log.append(f"Winner: ROAS >= {winner_roas} (no spend minimum)")
    log.append(f"Loser: ROAS <= {loser_roas} (no spend minimum)")
    log.append(f"Average: ROAS between {loser_roas} and {winner_roas}")
    log.append(f"Matched ads: {len(match_summary.matched)}")
    log.append("---")

    for match in match_summary.matched:
        spend_share = match.total_spend / total_spend if total_spend > 0 else 0
        weight_tier = _determine_weight_tier(spend_share)
        weight_multiplier = WEIGHT_MULTIPLIERS[weight_tier]
        value_score = match.total_spend * match.weighted_roas

        # ROAS-only classification for top 50
        if match.weighted_roas >= winner_roas:
            classification = Classification.WINNER
            reason = f"ROAS {match.weighted_roas:.2f} >= {winner_roas}"
        elif match.weighted_roas <= loser_roas:
            classification = Classification.LOSER
            reason = f"ROAS {match.weighted_roas:.2f} <= {loser_roas}"
        else:
            classification = Classification.AVERAGE
            reason = f"ROAS {match.weighted_roas:.2f} between {loser_roas} and {winner_roas}"

        log.append(
            f"{classification.value.upper()}: '{match.task.name[:50]}' — "
            f"ROAS={match.weighted_roas:.2f}, Spend=${match.total_spend:,.0f}, "
            f"Share={spend_share*100:.1f}% — {reason}"
        )

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

    result.winners.sort(key=lambda x: x.value_score, reverse=True)
    result.losers.sort(key=lambda x: x.value_score, reverse=True)
    result.average.sort(key=lambda x: x.value_score, reverse=True)

    result.pillar_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.PILLAR)
    result.strong_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.STRONG)
    result.normal_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.NORMAL)
    result.minor_winners = sum(1 for w in result.winners if w.weight_tier == WeightTier.MINOR)

    log.append("---")
    log.append(f"TOTALS: {len(result.winners)} winners, {len(result.average)} average, {len(result.losers)} losers")
    log.append(f"=== TOP 50 CLASSIFICATION END ===")

    return result
