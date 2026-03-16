"""Top 50 by spend — separate unfiltered section (FIX 5).

Takes top 50 ads by AGGREGATED total spend from the entire CSV.
NO winner/loser thresholds — just rank by spend.
Simple ROAS classification: profitable / unprofitable / no conversions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from creative_feedback_loop.csv_aggregator import AggregatedAd
from creative_feedback_loop.clickup_matcher import ClickUpTask, MatchedAd, ClassifiedAd

logger = logging.getLogger(__name__)


@dataclass
class Top50Ad:
    """An ad in the Top 50 by spend."""
    rank: int
    ad: AggregatedAd
    profitability: str  # "profitable", "unprofitable", "no_conversions"
    clickup_task: ClickUpTask | None = None
    match_score: float = 0.0


def build_top50(
    all_ads: list[AggregatedAd],
    clickup_tasks: list[ClickUpTask] | None = None,
    roas_threshold: float = 1.0,
) -> list[Top50Ad]:
    """Build the Top 50 section — unfiltered, ranked by total spend.

    Args:
        all_ads: All aggregated ads (already sorted by spend from aggregator).
        clickup_tasks: Optional ClickUp tasks for matching.
        roas_threshold: Simple threshold for profitable vs unprofitable.

    Returns:
        List of Top50Ad, max 50.
    """
    from creative_feedback_loop.clickup_matcher import _similarity, _normalize

    top = all_ads[:50]
    results: list[Top50Ad] = []

    for rank, ad in enumerate(top, 1):
        # Simple profitability classification
        if ad.blended_roas == 0 and ad.total_spend > 0:
            profitability = "no_conversions"
        elif ad.blended_roas >= roas_threshold:
            profitability = "profitable"
        else:
            profitability = "unprofitable"

        # Try to match to ClickUp
        best_task = None
        best_score = 0.0
        if clickup_tasks:
            for task in clickup_tasks:
                if _normalize(ad.ad_name) == _normalize(task.name):
                    best_task = task
                    best_score = 1.0
                    break
                norm_ad = _normalize(ad.ad_name)
                norm_task = _normalize(task.name)
                if norm_ad in norm_task or norm_task in norm_ad:
                    if 0.85 > best_score:
                        best_task = task
                        best_score = 0.85
                    continue
                score = _similarity(ad.ad_name, task.name)
                if score > best_score and score >= 0.6:
                    best_task = task
                    best_score = score

        results.append(Top50Ad(
            rank=rank,
            ad=ad,
            profitability=profitability,
            clickup_task=best_task,
            match_score=best_score,
        ))

    logger.info(
        f"Top 50 built: {sum(1 for r in results if r.profitability == 'profitable')} profitable, "
        f"{sum(1 for r in results if r.profitability == 'unprofitable')} unprofitable, "
        f"{sum(1 for r in results if r.profitability == 'no_conversions')} no conversions"
    )

    return results
