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
from jinja2 import Template

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
                "root_cause_chain": a.root_cause_chain,
                "root_cause_depth": a.root_cause_depth,
                "mechanism": a.mechanism,
                "mechanism_depth": a.mechanism_depth,
                "product_delivery_mechanism": a.product_delivery_mechanism,
                "proof_elements": a.proof_elements,
                "proof_gaps": a.proof_gaps,
                "beliefs_installed": a.beliefs_installed,
                "beliefs_missing": a.beliefs_missing,
                "objections_handled": a.objections_handled,
                "objections_open": a.objections_open,
                "ingredient_transparency": a.ingredient_transparency,
                "ingredient_transparency_score": a.ingredient_transparency_score,
                "unfalsifiability_techniques": a.unfalsifiability_techniques,
                "unfalsifiability_cracks": a.unfalsifiability_cracks,
                "mass_desire": a.mass_desire,
                "big_idea": a.big_idea,
                "ad_angle": a.ad_angle,
                "emotional_triggers": a.emotional_triggers,
                "emotional_sequence": a.emotional_sequence,
                "awareness_level": a.awareness_level,
                "sophistication_level": a.sophistication_level,
                "hook_type": a.hook_type,
                "hook_psychology": a.hook_psychology,
                "cta_strategy": a.cta_strategy,
                "analysis_confidence": a.analysis_confidence,
                "copy_quality_score": a.copy_quality_score,
            })

        # Calculate dataset size for adaptive depth
        total_ads = len(analyses)
        dataset_size = "small" if total_ads < 8 else "medium" if total_ads < 20 else "large"

        prompt = self._build_prompt(
            search_query=search_query,
            brand=brand or "Unknown",
            total_ads=total_ads,
            analyses_json=json.dumps(analyses_data, indent=2),
            small_dataset=(dataset_size == "small"),
            dataset_size=dataset_size,
        )

        # Call Claude for pattern analysis (with retries)
        for attempt in range(self.max_retries):
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=16384,
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
        small_dataset: bool = False,
        dataset_size: str = "large",
    ) -> str:
        # Use Jinja2 for template rendering with conditional support
        template = Template(self._prompt_template)
        return template.render(
            search_query=search_query,
            brand=brand,
            total_ads=total_ads,
            ad_analyses_json=analyses_json,
            small_dataset=small_dataset,
            dataset_size=dataset_size,
        )

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
                # NEW: Dimension distributions for compare command
                angle_distribution=data.get("angle_distribution", {}),
                format_distribution=data.get("format_distribution", {}),
                offer_distribution=data.get("offer_distribution", {}),
                cta_distribution=data.get("cta_distribution", {}),
                # Deep analysis fields
                competitive_verdict=data.get("competitive_verdict", ""),
                root_cause_gaps=data.get("root_cause_gaps", []),
                mechanism_gaps=data.get("mechanism_gaps", []),
                proof_gaps=data.get("proof_gaps", []),
                belief_gaps=data.get("belief_gaps", []),
                objection_gaps=data.get("objection_gaps", []),
                ingredient_transparency_analysis=data.get(
                    "ingredient_transparency_analysis", {}
                ),
                unfalsifiability_analysis=data.get("unfalsifiability_analysis", {}),
                loopholes=data.get("loopholes", []),
                priority_matrix=data.get("priority_matrix", []),
                what_not_to_do=data.get("what_not_to_do", []),
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
        """Generate deep strategic intelligence report from PatternReport."""
        lines = []
        lines.append("# Competitive Intelligence Report")
        lines.append("")
        lines.append(f"**Search Query**: {report.search_query}")
        if report.brand:
            lines.append(f"**Brand**: {report.brand}")
        lines.append(f"**Ads Analyzed**: {report.total_ads_analyzed}")
        lines.append(
            f"**Generated**: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        lines.append("")

        # Quality report
        if report.quality_report:
            qr = report.quality_report
            lines.append("---")
            lines.append("## Data Quality")
            lines.append(f"- **Status**: {'PASSED' if qr.passed else 'WARNING'}")
            lines.append(
                f"- Scraped: {qr.total_ads_scraped} | Downloaded: "
                f"{qr.total_ads_downloaded} | Transcribed: "
                f"{qr.total_ads_transcribed} | Filtered: "
                f"{qr.total_ads_filtered_out} | Analyzed: "
                f"{qr.total_ads_analyzed}"
            )
            lines.append(
                f"- Avg confidence: transcript={qr.avg_transcript_confidence:.2f}, "
                f"analysis={qr.avg_analysis_confidence:.2f}, "
                f"copy quality={qr.avg_copy_quality_score:.2f}"
            )
            lines.append("")

        # Competitive Verdict
        if report.competitive_verdict:
            lines.append("---")
            lines.append("## COMPETITIVE VERDICT")
            lines.append("")
            lines.append(f"> {report.competitive_verdict}")
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

        # === LOOPHOLES (the money section) ===
        if report.loopholes:
            lines.append("---")
            lines.append("## VALIDATED LOOPHOLES")
            lines.append("")
            for lh in report.loopholes:
                rank = lh.get("rank", "?")
                title = lh.get("title", "Untitled")
                score = lh.get("score", 0)
                effort = lh.get("effort", "?")
                timeline = lh.get("timeline", "?")

                lines.append(f"### LOOPHOLE #{rank}: {title} — Score: {score}/50")
                lines.append("")
                lines.append(f"**THE GAP**: {lh.get('gap', '')}")
                lines.append("")
                lines.append(f"**WHY IT'S MASSIVE**: {lh.get('why_massive', '')}")
                lines.append("")

                hooks = lh.get("execution_hooks", [])
                if hooks:
                    lines.append("**EXECUTION HOOKS**:")
                    for hook in hooks:
                        lines.append(f"- {hook}")
                    lines.append("")

                lines.append(f"**Effort**: {effort} | **Timeline**: {timeline}")
                lines.append("")

        # Priority Matrix
        if report.priority_matrix:
            lines.append("---")
            lines.append("## Priority Matrix")
            lines.append("")
            lines.append("| Rank | Loophole | Score | Effort | Timeline | Why First |")
            lines.append("|---|---|---|---|---|---|")
            for pm in report.priority_matrix:
                lines.append(
                    f"| {pm.get('rank', '')} | "
                    f"**{pm.get('loophole', '')}** | "
                    f"{pm.get('score', '')}/50 | "
                    f"{pm.get('effort', '')} | "
                    f"{pm.get('timeline', '')} | "
                    f"{pm.get('why_first', '')} |"
                )
            lines.append("")

        # What NOT to do
        if report.what_not_to_do:
            lines.append("## What NOT To Do")
            for item in report.what_not_to_do:
                lines.append(f"- {item}")
            lines.append("")

        # === GAP ANALYSIS SECTIONS ===
        lines.append("---")
        lines.append("## GAP ANALYSIS")
        lines.append("")

        # Root Cause Gaps
        if report.root_cause_gaps:
            lines.append("### Root Cause Gaps")
            for gap in report.root_cause_gaps:
                lines.append(
                    f"- **{gap.get('gap', '')}** "
                    f"[{gap.get('exploitability', '?')} exploitability]"
                )
                lines.append(f"  - Why it matters: {gap.get('why_it_matters', '')}")
                lines.append(f"  - Execution: {gap.get('execution_angle', '')}")
            lines.append("")

        # Mechanism Gaps
        if report.mechanism_gaps:
            lines.append("### Mechanism Gaps")
            for gap in report.mechanism_gaps:
                lines.append(
                    f"- **{gap.get('gap', '')}** "
                    f"[{gap.get('exploitability', '?')} exploitability]"
                )
                lines.append(f"  - Missing: {gap.get('missing_explanation', '')}")
                lines.append(f"  - Execution: {gap.get('execution_angle', '')}")
            lines.append("")

        # Proof Gaps
        if report.proof_gaps:
            lines.append("### Proof Architecture Gaps")
            lines.append(
                "| Unproven Claim | Frequency | Vulnerability | Counter-Proof |"
            )
            lines.append("|---|---|---|---|")
            for gap in report.proof_gaps:
                lines.append(
                    f"| {gap.get('gap', '')} | "
                    f"{gap.get('frequency', '')} | "
                    f"{gap.get('vulnerability', '')} | "
                    f"{gap.get('exploit_with', '')} |"
                )
            lines.append("")

        # Belief Gaps
        if report.belief_gaps:
            lines.append("### Belief Installation Gaps")
            for gap in report.belief_gaps:
                lines.append(f"- **Missing belief**: {gap.get('missing_belief', '')}")
                lines.append(f"  - Why critical: {gap.get('why_critical', '')}")
                lines.append(
                    f"  - Competitor advantage: "
                    f"{gap.get('competitor_advantage', '')}"
                )
            lines.append("")

        # Objection Gaps
        if report.objection_gaps:
            lines.append("### Unhandled Objections")
            lines.append(
                "| Objection | Risk Level | Exploit Angle |"
            )
            lines.append("|---|---|---|")
            for gap in report.objection_gaps:
                lines.append(
                    f"| {gap.get('unhandled_objection', '')} | "
                    f"{gap.get('risk_level', '')} | "
                    f"{gap.get('exploit_angle', '')} |"
                )
            lines.append("")

        # Ingredient Transparency
        ita = report.ingredient_transparency_analysis
        if ita:
            lines.append("### Ingredient Transparency")
            lines.append(f"- **Overall Score**: {ita.get('overall_score', '?')}/10")
            lines.append(f"- **What they reveal**: {ita.get('what_they_reveal', '')}")
            lines.append(f"- **What they hide**: {ita.get('what_they_hide', '')}")
            lines.append(f"- **Attack vector**: {ita.get('attack_vector', '')}")
            lines.append("")

        # Unfalsifiability
        ufa = report.unfalsifiability_analysis
        if ufa:
            lines.append("### Unfalsifiability Analysis")
            techs = ufa.get("techniques_used", [])
            if techs:
                lines.append("**Techniques used**:")
                for t in techs:
                    lines.append(f"- {t}")
            cracks = ufa.get("cracks_found", [])
            if cracks:
                lines.append("")
                lines.append("**Cracks found**:")
                for c in cracks:
                    lines.append(f"- {c}")
            strat = ufa.get("attack_strategy", "")
            if strat:
                lines.append("")
                lines.append(f"**Attack strategy**: {strat}")
            lines.append("")

        # === PATTERN DATA (supporting detail) ===
        lines.append("---")
        lines.append("## PATTERN DATA")
        lines.append("")

        # Root Cause Patterns
        if report.root_cause_patterns:
            lines.append("### Root Cause Patterns")
            lines.append(
                "| Root Cause | Frequency | Depth | Upstream Gap |"
            )
            lines.append("|---|---|---|---|")
            for rc in report.root_cause_patterns:
                lines.append(
                    f"| {rc.get('root_cause', '')} | "
                    f"{rc.get('frequency', 0)} | "
                    f"{rc.get('depth', '?')} | "
                    f"{rc.get('upstream_gap', 'None identified')} |"
                )
            lines.append("")

        # Mechanism Patterns
        if report.mechanism_patterns:
            lines.append("### Mechanism Patterns")
            lines.append(
                "| Mechanism | Frequency | Depth | Stops Short At |"
            )
            lines.append("|---|---|---|---|")
            for m in report.mechanism_patterns:
                lines.append(
                    f"| {m.get('mechanism', '')} | "
                    f"{m.get('frequency', 0)} | "
                    f"{m.get('depth', '?')} | "
                    f"{m.get('stops_short_at', '')} |"
                )
            lines.append("")

        # Pain Points
        if report.common_pain_points:
            lines.append("### Pain Points")
            lines.append("| Pain Point | Frequency | % |")
            lines.append("|---|---|---|")
            for pp in report.common_pain_points:
                pct = pp.get("percentage", 0)
                pct_display = pct if pct > 1 else pct * 100
                lines.append(
                    f"| {pp.get('pain_point', '')} | "
                    f"{pp.get('frequency', 0)} | "
                    f"{pct_display:.0f}% |"
                )
            lines.append("")

        # Hook Patterns
        if report.hook_patterns:
            lines.append("### Hook Patterns")
            for hp in report.hook_patterns:
                lines.append(
                    f"- **{hp.get('hook_type', '')}** "
                    f"({hp.get('frequency', 0)} ads)"
                )
                lines.append(
                    f"  - Psychology: {hp.get('effectiveness_notes', '')}"
                )
                counter = hp.get("counter_hook", "")
                if counter:
                    lines.append(f"  - Counter: {counter}")
            lines.append("")

        # Target Customer
        if report.target_customer_patterns:
            lines.append("### Target Customer Segments")
            for tc in report.target_customer_patterns:
                lines.append(
                    f"- **{tc.get('segment', '')}** "
                    f"({tc.get('frequency', 0)} ads): {tc.get('profile', '')}"
                )
            lines.append("")

        # Emotional Triggers
        if report.emotional_trigger_patterns:
            lines.append("### Emotional Architecture")
            lines.append("| Emotion | Frequency | Psychological Function |")
            lines.append("|---|---|---|")
            for et in report.emotional_trigger_patterns:
                lines.append(
                    f"| {et.get('emotion', '')} | "
                    f"{et.get('frequency', 0)} | "
                    f"{et.get('context', '')} |"
                )
            lines.append("")

        # Awareness Levels
        if report.awareness_level_distribution:
            lines.append("### Awareness Level Distribution")
            for level, count in report.awareness_level_distribution.items():
                bar = ">" * min(count, 50)
                lines.append(f"- {level}: {count} {bar}")
            lines.append("")

        # Delivery
        if report.delivery_mechanism_patterns:
            lines.append("### Delivery Mechanism")
            for dm in report.delivery_mechanism_patterns:
                lines.append(
                    f"- **{dm.get('delivery_type', '')}** "
                    f"({dm.get('frequency', 0)} ads): {dm.get('notes', '')}"
                )
            lines.append("")

        # === STRATEGIC RECOMMENDATIONS ===
        if report.recommendations:
            lines.append("---")
            lines.append("## STRATEGIC RECOMMENDATIONS")
            lines.append("")
            for i, rec in enumerate(report.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        return "\n".join(lines)
