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
    # Legacy simple avatar fields (backward compat)
    avatar_age: str = ""
    avatar_gender: str = ""
    avatar_lifestyle: str = ""
    avatar_tried_before: list[str] = field(default_factory=list)
    # Rich narrative avatar fields
    avatar_narrative: str = ""
    avatar_habit_history: str = ""
    avatar_root_cause_connection: str = ""
    avatar_failed_solutions: list[str] = field(default_factory=list)
    avatar_urgency_trigger: str = ""
    avatar_profiles: list[dict] = field(default_factory=list)
    daily_symptoms: list[str] = field(default_factory=list)
    mass_desire: str = ""
    hooks: list[str] = field(default_factory=list)
    # Multi-layer connection (tier 3-4 only)
    multi_layer_connection: dict = field(default_factory=dict)


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

            tier = result.tier if hasattr(result, 'tier') else 0
            doc = self._build_single_positioning(pp, science, all_ingredients, tier=tier)
            if doc:
                docs.append(doc)

        return PositioningResult(docs=docs)

    def _build_single_positioning(
        self, pain_point, science_report, all_ingredients, tier: int = 0
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
                                f"3. AVATAR — THIS IS CRITICAL. Do NOT write a generic "
                                f"demographic profile. Write a SPECIFIC person with:\n"
                                f"   - A specific behavior or habit they've had for years "
                                f"(e.g. 'drinking 2-3 cups of coffee daily for 15-20 years')\n"
                                f"   - WHY that habit connects to the root cause "
                                f"(e.g. 'chronic caffeine intake depletes adrenal cortisol "
                                f"rhythm, which means their body can't produce natural "
                                f"morning energy anymore')\n"
                                f"   - How that creates the symptom chain leading to the "
                                f"pain point\n"
                                f"   - What they've specifically tried that FAILED and WHY "
                                f"it failed — connect each failure to the root cause, not "
                                f"just a list of things\n"
                                f"   - A life situation that makes this problem urgent NOW\n\n"
                                f"   BAD avatar: 'Age: 28-45, Both genders, high-stress "
                                f"professionals, tried B-vitamins and meditation apps'\n"
                                f"   GOOD avatar: 'Women over 45 who've been drinking 2-3 "
                                f"cups of coffee daily for 15-20 years. Two decades of "
                                f"caffeine has depleted their adrenal cortisol rhythm, "
                                f"which means their body can't produce natural morning "
                                f"energy anymore. They've tried B-vitamins (doesn't work "
                                f"because the issue isn't vitamin deficiency — it's adrenal "
                                f"burnout from chronic stimulant use). They've tried "
                                f"sleeping more (doesn't work because their cortisol curve "
                                f"is inverted — high at night, low in morning). The coffee "
                                f"that used to give them energy is now the reason they "
                                f"have none.'\n\n"
                                f"   The avatar's HABITS connect to the ROOT CAUSE which "
                                f"connects to WHY NOTHING ELSE WORKED. It's a story, not "
                                f"a demographic profile.\n\n"
                                f"   AVATAR PROFILES: Generate 3-5 distinct avatar profiles. "
                                f"Each profile is a DIFFERENT person with a DIFFERENT "
                                f"specific habit, a DIFFERENT root cause connection, and "
                                f"a DIFFERENT reason why previous solutions failed. "
                                f"Each profile should be 2-3 sentences showing: "
                                f"specific habit → root cause connection → why previous "
                                f"solutions failed for THIS person.\n\n"
                                f"4. DAILY SYMPTOMS: 5-7 specific symptoms this person "
                                f"experiences daily\n\n"
                                f"5. MASS DESIRE — THIS IS CRITICAL:\n"
                                f"   Mass desire must be an EMOTIONAL, IDENTITY-LEVEL "
                                f"outcome — how the person wants to FEEL and be SEEN. "
                                f"NOT a clinical measurement or biological target.\n"
                                f"   Think: what would this person say they want if you "
                                f"asked them at a dinner party, not in a doctor's office.\n\n"
                                f"   BAD mass desire examples (too clinical/specific):\n"
                                f"   - 'Achieve systolic blood pressure readings below "
                                f"130mmHg within 90 days'\n"
                                f"   - 'Restore nitric oxide production to support "
                                f"endothelial function'\n"
                                f"   - 'Reduce inflammatory cytokine levels in arterial "
                                f"walls'\n\n"
                                f"   GOOD mass desire examples (emotional/identity):\n"
                                f"   - 'Feel like yourself again — energized, confident, "
                                f"not worried every time you check your numbers'\n"
                                f"   - 'Stop dreading every doctor's visit and finally "
                                f"hear \"your numbers look great\"'\n"
                                f"   - 'Look in the mirror and see someone who's thriving, "
                                f"not just surviving'\n"
                                f"   - 'Feel comfortable in your own body again — no more "
                                f"hiding, no more bloating, no more avoiding the beach'\n\n"
                                f"   The mass desire is the emotional state and identity "
                                f"shift the person craves. It should make someone reading "
                                f"it think 'YES, that's exactly what I want.'\n"
                                f"   Write ONE powerful sentence.\n\n"
                                f"6. HOOKS: 5 attention-grabbing ad hooks based on the "
                                f"root cause + mechanism. These should be specific, "
                                f"provocative, and based on the molecular root cause. "
                                f"Pattern: reveal a hidden cause or mechanism.\n\n"
                                + (
                                    f"7. MULTI-LAYER CONNECTION (THIS MARKET IS SATURATED "
                                    f"— you MUST provide a deeper angle):\n"
                                    f"   This pain point has 15,000+ active ads. Competitors "
                                    f"only talk about the obvious Layer 1 effect. You need "
                                    f"to go deeper:\n"
                                    f"   - Layer 1: The obvious effect everyone talks about\n"
                                    f"   - Layer 2: The deeper biological consequence\n"
                                    f"   - Layer 3: The specific, surprising outcome most "
                                    f"people don't know about\n"
                                    f"   - Why this is new: What competitors miss\n"
                                    f"   - A 'new hope' hook sentence\n"
                                    f"   - 3 hook examples using the multi-layer angle\n\n"
                                    if tier >= 3 else ""
                                )
                                + f"Return ONLY valid JSON:\n"
                                f"```json\n"
                                f"{{\n"
                                f'  "root_cause_surface": "...",\n'
                                f'  "root_cause_cellular": "...",\n'
                                f'  "root_cause_molecular": "...",\n'
                                f'  "mechanism": "...",\n'
                                f'  "avatar_narrative": "Full 3-5 sentence story of this '
                                f'specific person, their habit, root cause connection, '
                                f'and why nothing else worked",\n'
                                f'  "avatar_habit_history": "The specific long-term habit '
                                f'or behavior (e.g. drinking coffee daily for 15+ years)",\n'
                                f'  "avatar_root_cause_connection": "How that habit caused '
                                f'the root cause at the molecular level",\n'
                                f'  "avatar_failed_solutions": [\n'
                                f'    "Solution X — why it failed (connected to root cause)",\n'
                                f'    "Solution Y — why it failed (connected to root cause)"\n'
                                f'  ],\n'
                                f'  "avatar_urgency_trigger": "Life situation making this '
                                f'urgent now",\n'
                                f'  "avatar_profiles": [\n'
                                f'    {{"habit": "specific long-term habit", '
                                f'"root_cause_connection": "how it caused the problem", '
                                f'"why_solutions_failed": "why previous attempts failed"}}\n'
                                f'  ],\n'
                                f'  "daily_symptoms": ["..."],\n'
                                f'  "mass_desire": "...",\n'
                                f'  "hooks": ["..."]\n'
                                + (
                                    f',  "multi_layer_connection": {{\n'
                                    f'    "layer1": "obvious effect",\n'
                                    f'    "layer2": "deeper biological consequence",\n'
                                    f'    "layer3": "specific surprising outcome",\n'
                                    f'    "why_new": "what competitors miss",\n'
                                    f'    "new_hope_hook": "one sentence new hope hook",\n'
                                    f'    "hook_examples": ["hook 1", "hook 2", "hook 3"]\n'
                                    f'  }}\n'
                                    if tier >= 3 else ""
                                )
                                + f"}}\n"
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
                    avatar_narrative=data.get("avatar_narrative", ""),
                    avatar_habit_history=data.get("avatar_habit_history", ""),
                    avatar_root_cause_connection=data.get("avatar_root_cause_connection", ""),
                    avatar_failed_solutions=data.get("avatar_failed_solutions", []),
                    avatar_urgency_trigger=data.get("avatar_urgency_trigger", ""),
                    avatar_profiles=data.get("avatar_profiles", []),
                    daily_symptoms=data.get("daily_symptoms", []),
                    mass_desire=data.get("mass_desire", ""),
                    hooks=data.get("hooks", []),
                    multi_layer_connection=data.get("multi_layer_connection", {}),
                )

            except Exception as e:
                logger.warning(
                    f"Positioning attempt {attempt+1} failed for "
                    f"'{pain_point.name}': {e}"
                )

        return None
