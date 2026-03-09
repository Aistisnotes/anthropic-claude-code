"""Step 5: Root Cause + Mechanism Positioning.

For each top pain point, build DR framework positioning:
root cause, mechanism, avatar, pain points, mass desire, hooks.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .ingredient_extractor import Ingredient
from .scientific_researcher import ScientificReport
from .trends_validator import TrendResult

logger = logging.getLogger(__name__)


@dataclass
class PositioningDoc:
    pain_point_name: str
    root_cause_surface: str = ""
    root_cause_cellular: str = ""
    root_cause_molecular: str = ""
    mechanism: str = ""
    avatar_age: str = ""
    avatar_gender: str = ""
    avatar_lifestyle: str = ""
    avatar_tried_before: list[str] = field(default_factory=list)
    daily_symptoms: list[str] = field(default_factory=list)
    mass_desire: str = ""
    hooks: list[str] = field(default_factory=list)


@dataclass
class PositioningResult:
    docs: list[PositioningDoc]


class PositioningEngine:
    """Build root cause + mechanism positioning for top pain points."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        analyzer_cfg = config.get("analyzer", {})
        self.model = analyzer_cfg.get("model", "claude-sonnet-4-20250514")
        self.temperature = analyzer_cfg.get("temperature", 0.3)
        self.max_retries = analyzer_cfg.get("max_retries", 3)
        self.client = anthropic.Anthropic()

    async def build_positioning(
        self,
        top_results: list[TrendResult],
        science_reports: list[ScientificReport],
        all_ingredients: list[Ingredient],
        progress_cb=None,
    ) -> PositioningResult:
        """Build positioning doc for each top pain point."""
        docs: list[PositioningDoc] = []

        for i, result in enumerate(top_results):
            pp = result.pain_point
            if progress_cb:
                progress_cb(
                    f"Building positioning: '{pp.name}' ({i+1}/{len(top_results)})..."
                )

            # Find matching science report
            science = None
            for r in science_reports:
                if r.pain_point_name == pp.name:
                    science = r
                    break

            doc = self._build_single_positioning(pp, science, all_ingredients)
            if doc:
                docs.append(doc)

        return PositioningResult(docs=docs)

    def _build_single_positioning(
        self, pain_point, science_report, all_ingredients
    ) -> PositioningDoc | None:
        """Build DR framework positioning for one pain point."""
        # Build context from science report
        science_context = ""
        if science_report:
            science_context = f"\nScientific summary: {science_report.summary}\n"
            for ev in science_report.ingredient_evidence:
                science_context += (
                    f"- {ev.ingredient_name}: {ev.mechanism} "
                    f"(evidence: {ev.evidence_strength})\n"
                )

        ingredient_list = ", ".join(pain_point.supporting_ingredients)

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
                                f"You are a direct response marketing strategist "
                                f"specializing in health supplements. Build complete "
                                f"positioning for the pain point '{pain_point.name}'.\n\n"
                                f"Product ingredients addressing this: {ingredient_list}\n"
                                f"{science_context}\n\n"
                                f"Apply the DR FRAMEWORK:\n\n"
                                f"1. ROOT CAUSE (3 depth levels):\n"
                                f"   - Surface: What the person notices/experiences\n"
                                f"   - Cellular: What's happening at the cellular level\n"
                                f"   - Molecular: The deepest molecular/biochemical cause. "
                                f"Go UPSTREAM. Don't say 'inflammation' — say what CAUSES "
                                f"the inflammation. Be specific about pathways, enzymes, "
                                f"proteins.\n\n"
                                f"2. MECHANISM: How do the product's specific ingredients "
                                f"address this root cause? Explain the biological pathway. "
                                f"Not 'supports heart health' but specific actions like "
                                f"'S-allylcysteine inhibits calcium deposition in arterial "
                                f"walls by...'\n\n"
                                f"3. AVATAR:\n"
                                f"   - Age range and gender most affected\n"
                                f"   - Lifestyle characteristics\n"
                                f"   - What they've tried before that didn't work\n\n"
                                f"4. DAILY SYMPTOMS: 5-7 specific symptoms this person "
                                f"experiences daily\n\n"
                                f"5. MASS DESIRE: What transformation do they want? "
                                f"One powerful sentence.\n\n"
                                f"6. HOOKS: 5 attention-grabbing ad hooks based on the "
                                f"root cause + mechanism. These should be specific, "
                                f"provocative, and based on the molecular root cause. "
                                f"Pattern: reveal a hidden cause or mechanism.\n\n"
                                f"Return ONLY valid JSON:\n"
                                f"```json\n"
                                f"{{\n"
                                f'  "root_cause_surface": "...",\n'
                                f'  "root_cause_cellular": "...",\n'
                                f'  "root_cause_molecular": "...",\n'
                                f'  "mechanism": "...",\n'
                                f'  "avatar_age": "...",\n'
                                f'  "avatar_gender": "...",\n'
                                f'  "avatar_lifestyle": "...",\n'
                                f'  "avatar_tried_before": ["..."],\n'
                                f'  "daily_symptoms": ["..."],\n'
                                f'  "mass_desire": "...",\n'
                                f'  "hooks": ["..."]\n'
                                f"}}\n"
                                f"```"
                            ),
                        }
                    ],
                )

                text = response.content[0].text
                json_match = re.search(r"\{[\s\S]*\}", text)
                if not json_match:
                    continue

                data = json.loads(json_match.group())

                return PositioningDoc(
                    pain_point_name=pain_point.name,
                    root_cause_surface=data.get("root_cause_surface", ""),
                    root_cause_cellular=data.get("root_cause_cellular", ""),
                    root_cause_molecular=data.get("root_cause_molecular", ""),
                    mechanism=data.get("mechanism", ""),
                    avatar_age=data.get("avatar_age", ""),
                    avatar_gender=data.get("avatar_gender", ""),
                    avatar_lifestyle=data.get("avatar_lifestyle", ""),
                    avatar_tried_before=data.get("avatar_tried_before", []),
                    daily_symptoms=data.get("daily_symptoms", []),
                    mass_desire=data.get("mass_desire", ""),
                    hooks=data.get("hooks", []),
                )

            except Exception as e:
                logger.warning(
                    f"Positioning attempt {attempt+1} failed for "
                    f"'{pain_point.name}': {e}"
                )

        return None
