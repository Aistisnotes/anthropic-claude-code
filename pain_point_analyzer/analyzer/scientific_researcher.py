"""Step 4: Scientific Research.

For the top pain points, perform deep scientific analysis of the evidence
linking each ingredient to the pain point.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .ingredient_extractor import Ingredient
from .trends_validator import TrendResult

logger = logging.getLogger(__name__)


@dataclass
class StudyReference:
    description: str
    dosage: str = ""
    duration: str = ""
    effect_size: str = ""
    year: str = ""


@dataclass
class IngredientEvidence:
    ingredient_name: str
    evidence_strength: str  # strong, moderate, weak
    mechanism: str
    key_studies: list[StudyReference] = field(default_factory=list)
    contraindications: list[str] = field(default_factory=list)
    optimal_dosage: str = ""


@dataclass
class SynergyInfo:
    ingredients: list[str]
    pain_point: str
    synergy_description: str
    mechanism: str


@dataclass
class ScientificReport:
    pain_point_name: str
    summary: str
    overall_evidence_strength: str
    ingredient_evidence: list[IngredientEvidence]
    synergies: list[SynergyInfo] = field(default_factory=list)
    pathway: list[str] = field(default_factory=list)
    eli10: str = ""


@dataclass
class ResearchResult:
    reports: list[ScientificReport]


class ScientificResearcher:
    """Deep scientific analysis for top pain points."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        analyzer_cfg = config.get("analyzer", {})
        self.model = analyzer_cfg.get("model", "claude-sonnet-4-20250514")
        self.temperature = analyzer_cfg.get("temperature", 0.3)
        self.max_retries = analyzer_cfg.get("max_retries", 3)
        self.client = anthropic.Anthropic()

    async def research(
        self,
        top_results: list[TrendResult],
        all_ingredients: list[Ingredient],
        progress_cb=None,
    ) -> ResearchResult:
        """Run deep scientific research for each top pain point."""
        reports: list[ScientificReport] = []

        for i, result in enumerate(top_results):
            pp = result.pain_point
            if progress_cb:
                progress_cb(
                    f"Deep research: '{pp.name}' ({i+1}/{len(top_results)})..."
                )

            report = self._research_pain_point(pp, all_ingredients)
            if report:
                reports.append(report)

        # Research synergies across all top pain points
        if progress_cb:
            progress_cb("Researching ingredient synergies...")
        synergies = self._research_synergies(top_results, all_ingredients)
        for report in reports:
            report.synergies = [
                s for s in synergies if s.pain_point == report.pain_point_name
            ]

        return ResearchResult(reports=reports)

    def _research_pain_point(
        self, pain_point, all_ingredients: list[Ingredient]
    ) -> ScientificReport | None:
        """Deep-dive research for one pain point."""
        ingredient_names = pain_point.supporting_ingredients
        ingredient_details = []
        for name in ingredient_names:
            for ing in all_ingredients:
                if ing.name == name:
                    detail = name
                    if ing.amount:
                        detail += f" ({ing.amount} {ing.unit or ''})"
                    ingredient_details.append(detail)
                    break
            else:
                ingredient_details.append(name)

        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    temperature=self.temperature,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"You are a scientific researcher specializing in "
                                f"supplement science. Provide a DEEP scientific analysis "
                                f"of how these ingredients address the pain point "
                                f"'{pain_point.name}'.\n\n"
                                f"Ingredients to analyze:\n"
                                + "\n".join(f"- {d}" for d in ingredient_details)
                                + "\n\n"
                                "For EACH ingredient, provide:\n"
                                "1. evidence_strength: 'strong', 'moderate', or 'weak'\n"
                                "2. mechanism: The biological mechanism of action\n"
                                "3. key_studies: 2-3 key studies with:\n"
                                "   - description: What the study found\n"
                                "   - dosage: Dosage used\n"
                                "   - duration: Study duration\n"
                                "   - effect_size: Magnitude of effect\n"
                                "4. contraindications: Any warnings or interactions\n"
                                "5. optimal_dosage: Recommended dosage based on research\n\n"
                                "Also provide:\n"
                                "- summary: 2-3 sentence overall assessment\n"
                                "- overall_evidence_strength: Combined strength rating\n"
                                "- pathway: THE PATHWAY — a 4-step chain showing how the "
                                "ingredient action leads to symptom resolution. Format as "
                                "4 short step descriptions: Step 1 (ingredient action) → "
                                "Step 2 (first biological effect) → Step 3 (downstream "
                                "effect) → Step 4 (symptom resolution). Return as a list "
                                "of 4 strings.\n"
                                "- eli10: An ELI10 (Explain Like I'm 10) analogy. Format: "
                                "\"Imagine your [body part] is like a [analogy]. When you "
                                "take [ingredient], it [simple action] which makes "
                                "[simple outcome].\" Make it vivid and memorable.\n\n"
                                "Return ONLY valid JSON:\n"
                                "```json\n"
                                "{\n"
                                '  "summary": "...",\n'
                                '  "overall_evidence_strength": "strong|moderate|weak",\n'
                                '  "pathway": ["Step 1: ...", "Step 2: ...", '
                                '"Step 3: ...", "Step 4: ..."],\n'
                                '  "eli10": "Imagine your ...",\n'
                                '  "ingredient_evidence": [\n'
                                "    {\n"
                                '      "ingredient_name": "...",\n'
                                '      "evidence_strength": "...",\n'
                                '      "mechanism": "...",\n'
                                '      "key_studies": [{"description": "...", '
                                '"dosage": "...", "duration": "...", '
                                '"effect_size": "..."}],\n'
                                '      "contraindications": ["..."],\n'
                                '      "optimal_dosage": "..."\n'
                                "    }\n"
                                "  ]\n"
                                "}\n"
                                "```"
                            ),
                        }
                    ],
                )

                text = response.content[0].text
                json_match = re.search(r"\{[\s\S]*\}", text)
                if not json_match:
                    continue

                data = json.loads(json_match.group())

                evidence_list = []
                for ev in data.get("ingredient_evidence", []):
                    studies = [
                        StudyReference(
                            description=s.get("description", ""),
                            dosage=s.get("dosage", ""),
                            duration=s.get("duration", ""),
                            effect_size=s.get("effect_size", ""),
                        )
                        for s in ev.get("key_studies", [])
                    ]
                    evidence_list.append(
                        IngredientEvidence(
                            ingredient_name=ev.get("ingredient_name", ""),
                            evidence_strength=ev.get("evidence_strength", "weak"),
                            mechanism=ev.get("mechanism", ""),
                            key_studies=studies,
                            contraindications=ev.get("contraindications", []),
                            optimal_dosage=ev.get("optimal_dosage", ""),
                        )
                    )

                return ScientificReport(
                    pain_point_name=pain_point.name,
                    summary=data.get("summary", ""),
                    overall_evidence_strength=data.get(
                        "overall_evidence_strength", "moderate"
                    ),
                    ingredient_evidence=evidence_list,
                    pathway=data.get("pathway", []),
                    eli10=data.get("eli10", ""),
                )

            except Exception as e:
                logger.warning(
                    f"Research attempt {attempt+1} failed for '{pain_point.name}': {e}"
                )

        return None

    def _research_synergies(
        self, top_results: list[TrendResult], all_ingredients: list[Ingredient]
    ) -> list[SynergyInfo]:
        """Research ingredient synergies for top pain points."""
        pain_points_info = []
        for r in top_results:
            pain_points_info.append({
                "pain_point": r.pain_point.name,
                "ingredients": r.pain_point.supporting_ingredients,
            })

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=self.temperature,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Analyze potential ingredient SYNERGIES for these "
                            "pain points. Which ingredients work BETTER TOGETHER "
                            "than alone for each condition?\n\n"
                            f"Data: {json.dumps(pain_points_info)}\n\n"
                            "For each synergy found, explain:\n"
                            "- Which ingredients synergize\n"
                            "- Which pain point they address together\n"
                            "- How the synergy works (mechanism)\n\n"
                            "Return ONLY valid JSON:\n"
                            "```json\n"
                            "[\n"
                            "  {\n"
                            '    "ingredients": ["ing1", "ing2"],\n'
                            '    "pain_point": "...",\n'
                            '    "synergy_description": "...",\n'
                            '    "mechanism": "..."\n'
                            "  }\n"
                            "]\n"
                            "```"
                        ),
                    }
                ],
            )

            text = response.content[0].text
            json_match = re.search(r"\[[\s\S]*\]", text)
            if json_match:
                items = json.loads(json_match.group())
                return [
                    SynergyInfo(
                        ingredients=s.get("ingredients", []),
                        pain_point=s.get("pain_point", ""),
                        synergy_description=s.get("synergy_description", ""),
                        mechanism=s.get("mechanism", ""),
                    )
                    for s in items
                ]
        except Exception as e:
            logger.warning(f"Synergy research failed: {e}")

        return []
