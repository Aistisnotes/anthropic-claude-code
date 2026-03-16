"""Winner / Loser / Untested classifier for aggregated ads.

Applies threshold-based classification AFTER aggregation.
Handles ROAS = 0 correctly (FIX 3): zero return with spend = LOSER.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from creative_feedback_loop.csv_aggregator import AggregatedAd

logger = logging.getLogger(__name__)


@dataclass
class ThresholdConfig:
    """Separate winner and loser threshold configuration (FIX 2)."""
    winner_roas_min: float = 1.0
    winner_spend_min: float = 50.0
    loser_roas_max: float = 1.0
    loser_spend_min: float = 50.0


@dataclass
class ClassifiedAd:
    """An aggregated ad with a winner/loser/untested classification."""
    ad: AggregatedAd
    classification: str  # "winner", "loser", "untested"
    reason: str = ""


def classify_ads(
    ads: list[AggregatedAd],
    thresholds: ThresholdConfig | None = None,
) -> tuple[list[ClassifiedAd], dict[str, int]]:
    """Classify aggregated ads into winners, losers, untested.

    FIX 2: Uses separate winner/loser thresholds with lower defaults.
    FIX 3: ROAS = 0 with spend above minimum → LOSER.

    Returns:
        (list of ClassifiedAd, counts dict)
    """
    if thresholds is None:
        thresholds = ThresholdConfig()

    results: list[ClassifiedAd] = []
    counts = {"winner": 0, "loser": 0, "untested": 0}

    for ad in ads:
        classification, reason = _classify_single(ad, thresholds)
        results.append(ClassifiedAd(ad=ad, classification=classification, reason=reason))
        counts[classification] += 1

    logger.info(
        f"Classification complete: {counts['winner']} winners, "
        f"{counts['loser']} losers, {counts['untested']} untested"
    )

    return results, counts


def _classify_single(ad: AggregatedAd, t: ThresholdConfig) -> tuple[str, str]:
    """Classify a single ad. Returns (classification, reason)."""

    # Winner: ROAS >= threshold AND spend >= minimum
    if ad.total_spend >= t.winner_spend_min and ad.blended_roas >= t.winner_roas_min:
        return "winner", (
            f"ROAS {ad.blended_roas:.2f} >= {t.winner_roas_min} "
            f"and spend ${ad.total_spend:.2f} >= ${t.winner_spend_min}"
        )

    # Loser: ROAS < threshold AND spend >= minimum (FIX 3: includes ROAS = 0)
    if ad.total_spend >= t.loser_spend_min and ad.blended_roas < t.loser_roas_max:
        if ad.blended_roas == 0:
            return "loser", (
                f"ROAS = 0 (zero return) with spend ${ad.total_spend:.2f} "
                f">= ${t.loser_spend_min} — spent money, got nothing"
            )
        return "loser", (
            f"ROAS {ad.blended_roas:.2f} < {t.loser_roas_max} "
            f"and spend ${ad.total_spend:.2f} >= ${t.loser_spend_min}"
        )

    # Untested: not enough spend to classify
    return "untested", (
        f"Spend ${ad.total_spend:.2f} below minimum thresholds "
        f"(winner: ${t.winner_spend_min}, loser: ${t.loser_spend_min})"
    )
