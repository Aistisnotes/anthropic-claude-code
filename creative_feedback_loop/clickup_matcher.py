"""Match aggregated CSV ads to ClickUp creative tasks.

Uses fuzzy name matching to link Meta Ads Manager ad names to ClickUp task names.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from creative_feedback_loop.classifier import ClassifiedAd
from creative_feedback_loop.csv_aggregator import AggregatedAd

logger = logging.getLogger(__name__)


@dataclass
class ClickUpTask:
    """A creative task from ClickUp."""
    task_id: str
    name: str
    status: str = ""
    script: str = ""
    custom_fields: dict[str, Any] = field(default_factory=dict)
    url: str = ""


@dataclass
class MatchedAd:
    """An ad matched to a ClickUp task (or unmatched)."""
    classified_ad: ClassifiedAd
    clickup_task: ClickUpTask | None = None
    match_score: float = 0.0
    match_method: str = ""


def _normalize(name: str) -> str:
    """Normalize an ad/task name for comparison."""
    name = name.lower().strip()
    # Remove common suffixes like "- v2", "(copy)", etc.
    name = re.sub(r"\s*[-_]\s*(v\d+|copy|duplicate|test)\s*$", "", name, flags=re.IGNORECASE)
    # Remove extra whitespace
    name = re.sub(r"\s+", " ", name)
    return name


def _similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two strings."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def match_ads_to_clickup(
    classified_ads: list[ClassifiedAd],
    clickup_tasks: list[ClickUpTask],
    min_match_score: float = 0.6,
) -> list[MatchedAd]:
    """Match classified ads to ClickUp tasks by name similarity.

    Args:
        classified_ads: Ads already classified as winner/loser/untested.
        clickup_tasks: Tasks pulled from ClickUp.
        min_match_score: Minimum similarity to consider a match.

    Returns:
        List of MatchedAd with optional ClickUp task attached.
    """
    results: list[MatchedAd] = []
    matched_count = 0
    unmatched_count = 0

    for c_ad in classified_ads:
        best_task: ClickUpTask | None = None
        best_score = 0.0
        best_method = ""

        ad_name = c_ad.ad.ad_name

        for task in clickup_tasks:
            # Exact match (case-insensitive)
            if _normalize(ad_name) == _normalize(task.name):
                best_task = task
                best_score = 1.0
                best_method = "exact"
                break

            # Check if one contains the other
            norm_ad = _normalize(ad_name)
            norm_task = _normalize(task.name)
            if norm_ad in norm_task or norm_task in norm_ad:
                score = 0.85
                if score > best_score:
                    best_task = task
                    best_score = score
                    best_method = "contains"
                continue

            # Fuzzy match
            score = _similarity(ad_name, task.name)
            if score > best_score:
                best_task = task
                best_score = score
                best_method = "fuzzy"

        if best_score >= min_match_score and best_task is not None:
            results.append(MatchedAd(
                classified_ad=c_ad,
                clickup_task=best_task,
                match_score=best_score,
                match_method=best_method,
            ))
            matched_count += 1
        else:
            results.append(MatchedAd(classified_ad=c_ad))
            unmatched_count += 1

    logger.info(
        f"ClickUp matching: {matched_count} matched, {unmatched_count} unmatched "
        f"(out of {len(classified_ads)} ads)"
    )

    return results
