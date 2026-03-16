"""Novelty filter for pattern analysis (FIX 6).

Filters out "already known" baseline patterns that appear in both winners
and losers at similar rates. Surfaces patterns that actually differentiate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

BASELINE_THRESHOLD = 0.85  # 85% — patterns appearing in this % of ALL ads are baseline


@dataclass
class PatternSignal:
    """A pattern with differentiation metrics."""
    pattern: str
    winner_rate: float  # % of winners with this pattern
    loser_rate: float   # % of losers with this pattern
    total_rate: float   # % of all ads with this pattern
    differentiation: float  # winner_rate - loser_rate (positive = winner signal)
    signal_strength: str  # "HIGH", "MEDIUM", "LOW", "BASELINE"


@dataclass
class NoveltyResult:
    """Result of novelty filtering."""
    winner_signals: list[PatternSignal] = field(default_factory=list)
    loser_signals: list[PatternSignal] = field(default_factory=list)
    baseline_patterns: list[PatternSignal] = field(default_factory=list)


def compute_novelty(
    winner_patterns: dict[str, int],
    loser_patterns: dict[str, int],
    total_winners: int,
    total_losers: int,
    baseline_threshold: float = BASELINE_THRESHOLD,
) -> NoveltyResult:
    """Compute novelty scores for patterns across winners and losers.

    Args:
        winner_patterns: {pattern_name: count_in_winners}
        loser_patterns: {pattern_name: count_in_losers}
        total_winners: Total number of winner ads.
        total_losers: Total number of loser ads.
        baseline_threshold: % threshold above which a pattern is "baseline".

    Returns:
        NoveltyResult with categorized patterns.
    """
    all_patterns = set(winner_patterns.keys()) | set(loser_patterns.keys())
    total_ads = total_winners + total_losers

    if total_ads == 0:
        return NoveltyResult()

    result = NoveltyResult()

    for pattern in all_patterns:
        w_count = winner_patterns.get(pattern, 0)
        l_count = loser_patterns.get(pattern, 0)

        w_rate = w_count / total_winners if total_winners > 0 else 0
        l_rate = l_count / total_losers if total_losers > 0 else 0
        t_rate = (w_count + l_count) / total_ads

        diff = w_rate - l_rate

        # Determine signal strength
        if t_rate >= baseline_threshold:
            strength = "BASELINE"
        elif abs(diff) >= 0.5:
            strength = "HIGH"
        elif abs(diff) >= 0.25:
            strength = "MEDIUM"
        else:
            strength = "LOW"

        signal = PatternSignal(
            pattern=pattern,
            winner_rate=round(w_rate, 3),
            loser_rate=round(l_rate, 3),
            total_rate=round(t_rate, 3),
            differentiation=round(diff, 3),
            signal_strength=strength,
        )

        if strength == "BASELINE":
            result.baseline_patterns.append(signal)
        elif diff > 0:
            result.winner_signals.append(signal)
        else:
            result.loser_signals.append(signal)

    # Sort by differentiation power
    result.winner_signals.sort(key=lambda s: s.differentiation, reverse=True)
    result.loser_signals.sort(key=lambda s: s.differentiation)  # most negative first
    result.baseline_patterns.sort(key=lambda s: s.total_rate, reverse=True)

    logger.info(
        f"Novelty filter: {len(result.winner_signals)} winner signals, "
        f"{len(result.loser_signals)} loser signals, "
        f"{len(result.baseline_patterns)} baseline patterns"
    )

    return result
