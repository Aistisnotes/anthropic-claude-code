"""Cross-ad pattern analysis using Claude API.

Takes a collection of individual AdAnalysis results and identifies patterns,
commonalities, and strategic insights across all analyzed ads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import anthropic

from meta_ads_analyzer.models import AdAnalysis, PatternReport, QualityReport
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "pattern_analysis.txt"


class PatternAnalyzer:
    """Identify patterns across multiple ad analyses."""

    def __init__(self, config: dict[str, Any]):
        a_cfg = config.get("analyzer", {})
        self.model = a_cfg.get("model", "claude-sonnet-4-20250514")
        self.temperature = a_cfg.get("temperature", 0.3)
        self.max_retries = a_cfg.get("max_retries", 3)
        self._client = anthropic.AsyncAnthropic()
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        if PROMPT_PATH.exists():
            return PROMPT_PATH.read_text()
        raise FileNotFoundError(f"Pattern analysis prompt not found: {PROMPT_PATH}")

    async def analyze_patterns(
        self,
        analyses: list[AdAnalysis],
        search_query: str,
        brand: str | None,
        quality_report: QualityReport | None = None,
    ) -> PatternReport:
        """Run pattern analysis across all individual ad analyses.

        Args:
            analyses: List of individual ad analysis results.
            search_query: Original search query.
            brand: Brand name if known.
            quality_report: Quality gate report to include.

        Returns:
            PatternReport with cross-ad insights.
        """
        logger.info(
            f"Running pattern analysis on {len(analyses)} ads for '{search_query}'"
        )

        # Prepare ad analyses as JSON for the prompt
        analyses_data = []
        for a in analyses:
            analyses_data.append({
                "ad_id": a.ad_id,
                "brand": a.brand,
                "target_customer_profile": a.target_customer_profile,
                "target_demographics": a.target_demographics,
                "target_psychographics": a.target_psychographics,
                "pain_points": a.pain_points,
                "pain_point_symptoms": a.pain_point_symptoms,
                "root_cause": a.root_cause,
                "mechanism": a.mechanism,
                "product_delivery_mechanism": a.product_delivery_mechanism,
                "mass_desire": a.mass_desire,
                "big_idea": a.big_idea,
                "ad_angle": a.ad_angle,
                "emotional_triggers": a.emotional_triggers,
                "awareness_level": a.awareness_level,
                "sophistication_level": a.sophistication_level,
                "hook_type": a.hook_type,
                "cta_strategy": a.cta_strategy,
                "analysis_confidence": a.analysis_confidence,
                "copy_quality_score": a.copy_quality_score,
            })

        prompt = self._build_prompt(
            search_query=search_query,
            brand=brand or "Unknown",
            total_ads=len(analyses),
            analyses_json=json.dumps(analyses_data, indent=2),
        )

        # Call Claude for pattern analysis (with retries)
        for attempt in range(self.max_retries):
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    temperature=self.temperature,
                    messages=[{"role": "user", "content": prompt}],
                )

                text = response.content[0].text
                report = self._parse_response(
                    text, search_query, brand, len(analyses), quality_report
                )

                if report:
                    logger.info("Pattern analysis complete")
                    return report

                logger.warning(f"Failed to parse pattern response, attempt {attempt + 1}")

            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 2)  # Start at 4s for pattern analysis
                logger.warning(f"Rate limited, waiting {wait}s")
                import asyncio
                await asyncio.sleep(wait)
            except anthropic.APIError as e:
                logger.error(f"API error in pattern analysis: {e}")
                if attempt < self.max_retries - 1:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)

        # Fallback: return minimal report
        logger.error("Pattern analysis failed after all retries")
        return PatternReport(
            search_query=search_query,
            brand=brand,
            total_ads_analyzed=len(analyses),
            quality_report=quality_report,
            executive_summary="Pattern analysis failed. Please retry.",
        )

    def _build_prompt(
        self,
        search_query: str,
        brand: str,
        total_ads: int,
        analyses_json: str,
    ) -> str:
        prompt = self._prompt_template
        prompt = prompt.replace("{{search_query}}", search_query)
        prompt = prompt.replace("{{brand}}", brand)
        prompt = prompt.replace("{{total_ads}}", str(total_ads))
        prompt = prompt.replace("{{ad_analyses_json}}", analyses_json)
        return prompt

    def _parse_response(
        self,
        response_text: str,
        search_query: str,
        brand: str | None,
        total_ads: int,
        quality_report: QualityReport | None,
    ) -> Optional[PatternReport]:
        """Parse pattern analysis response into PatternReport."""
        try:
            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text.strip()

            data = json.loads(json_str)

            report = PatternReport(
                search_query=search_query,
                brand=brand,
                total_ads_analyzed=total_ads,
                common_pain_points=data.get("common_pain_points", []),
                common_symptoms=data.get("common_symptoms", []),
                root_cause_patterns=data.get("root_cause_patterns", []),
                mechanism_patterns=data.get("mechanism_patterns", []),
                delivery_mechanism_patterns=data.get("delivery_mechanism_patterns", []),
                mass_desire_patterns=data.get("mass_desire_patterns", []),
                big_idea_patterns=data.get("big_idea_patterns", []),
                target_customer_patterns=data.get("target_customer_patterns", []),
                emotional_trigger_patterns=data.get("emotional_trigger_patterns", []),
                hook_patterns=data.get("hook_patterns", []),
                awareness_level_distribution=data.get("awareness_level_distribution", {}),
                executive_summary=data.get("executive_summary", ""),
                key_insights=data.get("key_insights", []),
                recommendations=data.get("recommendations", []),
                quality_report=quality_report,
            )

            # Generate markdown report
            report.full_report_markdown = self._generate_markdown(report)
            return report

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse pattern analysis response: {e}")
            return None

    def _generate_markdown(self, report: PatternReport) -> str:
        """Generate full markdown report from PatternReport."""
        lines = []
        lines.append(f"# Ad Pattern Analysis Report")
        lines.append(f"")
        lines.append(f"**Search Query**: {report.search_query}")
        if report.brand:
            lines.append(f"**Brand**: {report.brand}")
        lines.append(f"**Ads Analyzed**: {report.total_ads_analyzed}")
        lines.append(f"**Generated**: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")

        # Quality report
        if report.quality_report:
            qr = report.quality_report
            lines.append("---")
            lines.append("## Quality Gate Results")
            lines.append(f"- **Status**: {'PASSED' if qr.passed else 'WARNING'}")
            lines.append(f"- Ads scraped: {qr.total_ads_scraped}")
            lines.append(f"- Ads downloaded: {qr.total_ads_downloaded}")
            lines.append(f"- Ads transcribed: {qr.total_ads_transcribed}")
            lines.append(f"- Ads filtered out: {qr.total_ads_filtered_out}")
            lines.append(f"- Ads analyzed: {qr.total_ads_analyzed}")
            lines.append(f"- Avg transcript confidence: {qr.avg_transcript_confidence:.2f}")
            lines.append(f"- Avg analysis confidence: {qr.avg_analysis_confidence:.2f}")
            lines.append(f"- Avg copy quality: {qr.avg_copy_quality_score:.2f}")
            if qr.issues:
                lines.append("- **Issues**:")
                for issue in qr.issues:
                    lines.append(f"  - {issue}")
            lines.append("")

        # Executive Summary
        lines.append("---")
        lines.append("## Executive Summary")
        lines.append(report.executive_summary)
        lines.append("")

        # Key Insights
        if report.key_insights:
            lines.append("## Key Insights")
            for i, insight in enumerate(report.key_insights, 1):
                lines.append(f"{i}. {insight}")
            lines.append("")

        # Pain Points
        if report.common_pain_points:
            lines.append("## Common Pain Points")
            lines.append("| Pain Point | Frequency | % |")
            lines.append("|---|---|---|")
            for pp in report.common_pain_points:
                lines.append(
                    f"| {pp.get('pain_point', 'N/A')} | "
                    f"{pp.get('frequency', 0)} | "
                    f"{pp.get('percentage', 0):.0%} |"
                )
            lines.append("")

        # Symptoms
        if report.common_symptoms:
            lines.append("## Common Symptoms")
            for s in report.common_symptoms:
                lines.append(f"- **{s.get('symptom', 'N/A')}** ({s.get('frequency', 0)} ads)")
            lines.append("")

        # Root Causes
        if report.root_cause_patterns:
            lines.append("## Root Cause Patterns")
            for rc in report.root_cause_patterns:
                lines.append(f"### {rc.get('root_cause', 'N/A')} ({rc.get('frequency', 0)} ads)")
                lines.append(rc.get("description", ""))
                lines.append("")

        # Mechanisms
        if report.mechanism_patterns:
            lines.append("## Mechanism Patterns")
            for m in report.mechanism_patterns:
                lines.append(f"### {m.get('mechanism', 'N/A')} ({m.get('frequency', 0)} ads)")
                lines.append(m.get("description", ""))
                lines.append("")

        # Delivery Mechanisms
        if report.delivery_mechanism_patterns:
            lines.append("## Delivery Mechanism Patterns")
            for dm in report.delivery_mechanism_patterns:
                lines.append(
                    f"- **{dm.get('delivery_type', 'N/A')}** "
                    f"({dm.get('frequency', 0)} ads): {dm.get('notes', '')}"
                )
            lines.append("")

        # Mass Desires
        if report.mass_desire_patterns:
            lines.append("## Mass Desire Patterns")
            for md in report.mass_desire_patterns:
                lines.append(f"### {md.get('desire', 'N/A')} ({md.get('frequency', 0)} ads)")
                lines.append(md.get("description", ""))
                lines.append("")

        # Big Ideas
        if report.big_idea_patterns:
            lines.append("## Big Idea Patterns")
            for bi in report.big_idea_patterns:
                lines.append(f"### {bi.get('idea_theme', 'N/A')} ({bi.get('frequency', 0)} ads)")
                lines.append(bi.get("description", ""))
                lines.append("")

        # Target Customer
        if report.target_customer_patterns:
            lines.append("## Target Customer Segments")
            for tc in report.target_customer_patterns:
                lines.append(f"### {tc.get('segment', 'N/A')} ({tc.get('frequency', 0)} ads)")
                lines.append(tc.get("profile", ""))
                lines.append("")

        # Emotional Triggers
        if report.emotional_trigger_patterns:
            lines.append("## Emotional Triggers")
            lines.append("| Emotion | Frequency | Context |")
            lines.append("|---|---|---|")
            for et in report.emotional_trigger_patterns:
                lines.append(
                    f"| {et.get('emotion', 'N/A')} | "
                    f"{et.get('frequency', 0)} | "
                    f"{et.get('context', '')} |"
                )
            lines.append("")

        # Hook Patterns
        if report.hook_patterns:
            lines.append("## Hook Patterns")
            for hp in report.hook_patterns:
                lines.append(
                    f"- **{hp.get('hook_type', 'N/A')}** ({hp.get('frequency', 0)} ads): "
                    f"{hp.get('effectiveness_notes', '')}"
                )
            lines.append("")

        # Awareness Levels
        if report.awareness_level_distribution:
            lines.append("## Awareness Level Distribution")
            for level, count in report.awareness_level_distribution.items():
                bar = "█" * count
                lines.append(f"- {level}: {count} {bar}")
            lines.append("")

        # Recommendations
        if report.recommendations:
            lines.append("---")
            lines.append("## Strategic Recommendations")
            for i, rec in enumerate(report.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        return "\n".join(lines)
