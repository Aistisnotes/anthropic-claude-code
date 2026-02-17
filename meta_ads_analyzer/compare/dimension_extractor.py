"""Extract dimension distributions from PatternReport for comparison analysis."""

from __future__ import annotations

from meta_ads_analyzer.models import PatternReport
from meta_ads_analyzer.compare.dimensions import (
    ALL_HOOKS,
    ALL_ANGLES,
    ALL_EMOTIONS,
    ALL_FORMATS,
    ALL_OFFERS,
    ALL_CTAS,
)


class DimensionExtractor:
    """Extract 6 dimension distributions from PatternReport.

    Since Session 3 Commit 1 extended PatternReport to include explicit
    distributions for all 6 dimensions, this class is now a simple passthrough
    with validation.
    """

    @staticmethod
    def extract_all_dimensions(report: PatternReport) -> dict[str, dict[str, int]]:
        """Extract all 6 dimension distributions from pattern report.

        Args:
            report: PatternReport with analysis results

        Returns:
            Dict mapping dimension name to {value: count} distribution
        """
        return {
            'hooks': DimensionExtractor._extract_from_patterns(
                report.hook_patterns, 'hook_type', ALL_HOOKS
            ),
            'angles': report.angle_distribution,
            'emotions': DimensionExtractor._extract_from_patterns(
                report.emotional_trigger_patterns, 'emotion', ALL_EMOTIONS
            ),
            'formats': report.format_distribution,
            'offers': report.offer_distribution,
            'ctas': report.cta_distribution,
        }

    @staticmethod
    def _extract_from_patterns(
        patterns: list[dict], key: str, valid_values: list[str]
    ) -> dict[str, int]:
        """Extract distribution from pattern list (hooks and emotions).

        Args:
            patterns: List of pattern dicts with frequency counts
            key: Key to extract value from ('hook_type' or 'emotion')
            valid_values: List of valid dimension values

        Returns:
            Dict mapping dimension value to frequency count
        """
        dist = {}
        for pattern in patterns:
            # Try key first, fall back to 'pattern'
            value = pattern.get(key) or pattern.get('pattern')
            freq = pattern.get('frequency', 0)

            if value and value in valid_values:
                dist[value] = dist.get(value, 0) + freq

        return dist
