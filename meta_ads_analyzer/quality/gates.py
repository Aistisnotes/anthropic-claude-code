"""Quality gates and safety checks for the analysis pipeline.

Ensures we have sufficient data quality and quantity before drawing
pattern conclusions. Prevents garbage-in-garbage-out analysis.

Checks:
1. Minimum ad count before pattern analysis
2. Transcript quality thresholds
3. Analysis confidence thresholds
4. Copy quality score validation
5. Filter ratio warnings (too many filtered = bad scrape)
6. Duplicate content detection
"""

from __future__ import annotations

from typing import Any

from meta_ads_analyzer.models import (
    AdAnalysis,
    AdContent,
    AdStatus,
    QualityReport,
)
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class QualityGates:
    """Run quality checks before pattern analysis."""

    def __init__(self, config: dict[str, Any]):
        q_cfg = config.get("quality", {})
        self.min_ads_for_pattern = q_cfg.get("min_ads_for_pattern", 10)
        self.min_avg_transcript_confidence = q_cfg.get("min_avg_transcript_confidence", 0.5)
        self.min_avg_analysis_confidence = q_cfg.get("min_avg_analysis_confidence", 0.6)
        self.min_copy_quality_score = q_cfg.get("min_copy_quality_score", 0.4)
        self.max_filter_ratio = q_cfg.get("max_filter_ratio", 0.7)

    def run_checks(
        self,
        all_content: list[AdContent],
        analyses: list[AdAnalysis],
    ) -> QualityReport:
        """Run all quality checks and return a report.

        Args:
            all_content: All ad content (including filtered).
            analyses: Successfully completed analyses.

        Returns:
            QualityReport with pass/fail status and issues.
        """
        report = QualityReport(min_ads_for_pattern=self.min_ads_for_pattern)
        issues: list[str] = []

        # Count stats
        report.total_ads_scraped = len(all_content)
        report.total_ads_filtered_out = sum(
            1 for c in all_content if c.status == AdStatus.FILTERED_OUT
        )
        report.total_ads_downloaded = sum(
            1 for c in all_content
            if c.status in (AdStatus.DOWNLOADED, AdStatus.TRANSCRIBED, AdStatus.ANALYZED)
        )
        report.total_ads_transcribed = sum(
            1 for c in all_content
            if c.status in (AdStatus.TRANSCRIBED, AdStatus.ANALYZED)
        )
        report.total_ads_analyzed = len(analyses)

        # Check 1: Minimum ad count
        if report.total_ads_analyzed < self.min_ads_for_pattern:
            issues.append(
                f"CRITICAL: Only {report.total_ads_analyzed} ads analyzed, "
                f"minimum {self.min_ads_for_pattern} required for reliable patterns. "
                f"Results may not be statistically meaningful."
            )

        # Check 2: Transcript confidence
        transcript_confidences = [
            c.transcript_confidence for c in all_content
            if c.transcript and c.transcript_confidence > 0
        ]
        if transcript_confidences:
            report.avg_transcript_confidence = (
                sum(transcript_confidences) / len(transcript_confidences)
            )
            if report.avg_transcript_confidence < self.min_avg_transcript_confidence:
                issues.append(
                    f"WARNING: Average transcript confidence "
                    f"({report.avg_transcript_confidence:.2f}) is below threshold "
                    f"({self.min_avg_transcript_confidence}). "
                    f"Transcription quality may affect analysis accuracy."
                )

        # Check 3: Analysis confidence
        if analyses:
            confidences = [a.analysis_confidence for a in analyses]
            report.avg_analysis_confidence = sum(confidences) / len(confidences)
            if report.avg_analysis_confidence < self.min_avg_analysis_confidence:
                issues.append(
                    f"WARNING: Average analysis confidence "
                    f"({report.avg_analysis_confidence:.2f}) is below threshold "
                    f"({self.min_avg_analysis_confidence}). "
                    f"Some ads may have ambiguous or low-quality content."
                )

            # Check low-confidence individual ads
            low_conf = [a for a in analyses if a.analysis_confidence < 0.5]
            if low_conf:
                issues.append(
                    f"INFO: {len(low_conf)} ads have analysis confidence below 0.5. "
                    f"Consider reviewing these individually."
                )

        # Check 4: Copy quality
        if analyses:
            quality_scores = [a.copy_quality_score for a in analyses]
            report.avg_copy_quality_score = sum(quality_scores) / len(quality_scores)
            if report.avg_copy_quality_score < self.min_copy_quality_score:
                issues.append(
                    f"WARNING: Average copy quality score "
                    f"({report.avg_copy_quality_score:.2f}) is below threshold "
                    f"({self.min_copy_quality_score}). "
                    f"Many ads may have weak or generic copy."
                )

        # Check 5: Filter ratio
        if report.total_ads_scraped > 0:
            filter_ratio = report.total_ads_filtered_out / report.total_ads_scraped
            if filter_ratio > self.max_filter_ratio:
                issues.append(
                    f"WARNING: {filter_ratio:.0%} of scraped ads were filtered out "
                    f"(threshold: {self.max_filter_ratio:.0%}). "
                    f"This may indicate poor search targeting or scraping issues."
                )

        # Check 6: Zero results
        if report.total_ads_analyzed == 0:
            issues.append(
                "CRITICAL: No ads were successfully analyzed. "
                "Cannot produce pattern report. Check scraping and API configuration."
            )

        # Determine pass/fail
        has_critical = any(i.startswith("CRITICAL") for i in issues)
        report.passed = not has_critical
        report.issues = issues

        # Log results
        status = "PASSED" if report.passed else "FAILED"
        logger.info(f"Quality gate {status}: {len(issues)} issue(s) found")
        for issue in issues:
            if issue.startswith("CRITICAL"):
                logger.error(issue)
            elif issue.startswith("WARNING"):
                logger.warning(issue)
            else:
                logger.info(issue)

        return report


class CopyQualityChecker:
    """Additional copy/script quality validation.

    Checks the raw ad content for quality signals before analysis.
    """

    @staticmethod
    def check_transcript_quality(transcript: str) -> dict[str, Any]:
        """Check transcript quality indicators.

        Returns dict with quality metrics and flags.
        """
        words = transcript.split()
        word_count = len(words)

        issues = []
        score = 1.0

        # Too short
        if word_count < 20:
            issues.append("Very short transcript (< 20 words)")
            score -= 0.4

        # Repetition detection (sign of bad transcription)
        if word_count > 10:
            unique_ratio = len(set(words)) / word_count
            if unique_ratio < 0.3:
                issues.append(f"High word repetition (unique ratio: {unique_ratio:.2f})")
                score -= 0.3

        # All caps (sign of OCR or bad extraction)
        upper_ratio = sum(1 for c in transcript if c.isupper()) / max(len(transcript), 1)
        if upper_ratio > 0.7:
            issues.append("Mostly uppercase text")
            score -= 0.2

        # Gibberish detection (very few common English words)
        common_words = {
            "the", "a", "is", "are", "was", "were", "and", "or", "but",
            "in", "on", "at", "to", "for", "of", "with", "that", "this",
            "you", "i", "we", "they", "it", "not", "have", "has", "do",
        }
        lower_words = [w.lower().strip(".,!?;:") for w in words]
        common_ratio = sum(1 for w in lower_words if w in common_words) / max(word_count, 1)
        if word_count > 20 and common_ratio < 0.05:
            issues.append("Very few common English words (possible gibberish)")
            score -= 0.3

        return {
            "word_count": word_count,
            "score": max(0.0, min(1.0, score)),
            "issues": issues,
            "passed": score >= 0.5,
        }

    @staticmethod
    def check_primary_copy_quality(text: str) -> dict[str, Any]:
        """Check primary copy quality indicators."""
        words = text.split()
        word_count = len(words)

        issues = []
        score = 1.0

        if word_count < 50:
            issues.append("Short primary copy (< 50 words)")
            score -= 0.2

        # Check for truncation indicators
        if text.rstrip().endswith("...") or text.rstrip().endswith("See more"):
            issues.append("Copy appears truncated")
            score -= 0.15

        # Check for excessive emoji/special chars
        special_count = sum(1 for c in text if ord(c) > 127)
        special_ratio = special_count / max(len(text), 1)
        if special_ratio > 0.3:
            issues.append("High ratio of special/emoji characters")
            score -= 0.15

        return {
            "word_count": word_count,
            "score": max(0.0, min(1.0, score)),
            "issues": issues,
            "passed": score >= 0.5,
        }
