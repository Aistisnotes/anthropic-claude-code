"""Step 5: Root Cause + Mechanism Positioning.

For each top pain point, build DR framework positioning:
root cause, mechanism, avatars, pain points, mass desire, hooks,
ingredient pathways, and multi-layer connections for saturated markets.
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
class AvatarProfile:
    description: str  # 2-3 sentence profile


@dataclass
class IngredientPathway:
    ingredient: str
    root_cause: str
    resolution: str
    mass_desire: str
    chain: str  # "A → B → C → D" display string


@dataclass
class MultiLayerConnection:
    full_chain: str  # "Ingredient → Layer 1 → Layer 2 → Layer 3"
    why_new_angle: str
    new_hope_hook: str
    hooks: list[str] = field(default_factory=list)


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
    # Multiple avatar profiles (CHANGE 3)
    avatar_profiles: list[AvatarProfile] = field(default_factory=list)
    daily_symptoms: list[str] = field(default_factory=list)
    mass_desire: str = ""
    hooks: list[str] = field(default_factory=list)
    # Ingredient pathways (CHANGE 6)
    ingredient_pathways: list[IngredientPathway] = field(default_factory=list)
    # Multi-layer connection for saturated markets (CHANGE 8)
    multi_layer: MultiLayerConnection | None = None


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

            doc = self._build_single_positioning(
                pp, science, all_ingredients, result.tier, result.best_score
            )
            if doc:
                docs.append(doc)

        return PositioningResult(docs=docs)

    def _build_single_positioning(
        self, pain_point, science_report, all_ingredients, tier: int, ad_count: int
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

        # Build multi-layer instruction for saturated markets
        multi_layer_instruction = ""
        if tier >= 3:
            multi_layer_instruction = (
                f"\n7. MULTI-LAYER CONNECTION (this pain point has {ad_count:,} "
                f"active ads — it's {'super saturated' if tier == 4 else 'saturated'}). "
                f"Find a DEEPER connection:\n"
                f"   a) Start with the ingredient's PRIMARY mechanism\n"
                f"   b) Trace that mechanism to a SECONDARY system it affects\n"
                f"   c) Trace that secondary effect to a SPECIFIC symptom cluster\n"
                f"   d) This creates a NEW ANGLE competitors aren't talking about\n"
                f"   Output:\n"
                f'   - "multi_layer_chain": "Ingredient → Layer 1 → Layer 2 → Layer 3"\n'
                f'   - "multi_layer_why_new": "Why this angle is different"\n'
                f'   - "multi_layer_new_hope": "One sentence that makes someone think '
                f"'wait, I haven't tried THIS approach'\"\n"
                f'   - "multi_layer_hooks": ["3 hooks using this angle"]\n'
            )
            multi_layer_json = (
                '  "multi_layer_chain": "...",\n'
                '  "multi_layer_why_new": "...",\n'
                '  "multi_layer_new_hope": "...",\n'
                '  "multi_layer_hooks": ["..."],\n'
            )
        else:
            multi_layer_json = ""

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
                                f"3. AVATARS — Generate 3-5 DISTINCT avatar profiles. "
                                f"Each avatar is a SPECIFIC person, not a demographic. "
                                f"Each profile should be 2-3 sentences describing:\n"
                                f"   - A specific person with a specific habit/life situation\n"
                                f"   - How that habit connects to the root cause\n"
                                f"   - Why nothing else worked for them specifically\n\n"
                                f"   Example avatars for 'bloating':\n"
                                f"   1. Women 45+ who've been drinking wine 3-4 nights a "
                                f"week for 20 years. The alcohol disrupted bile production "
                                f"which means fat sits undigested causing chronic bloating. "
                                f"Probiotics didn't work because the problem isn't gut "
                                f"bacteria — it's liver function.\n"
                                f"   2. Desk workers 35-50 who sit 10+ hours daily. "
                                f"Sedentary posture compresses the lymphatic system which "
                                f"slows fluid drainage. Exercise and water intake didn't "
                                f"fix it because the compression happens during work hours, "
                                f"not gym hours.\n"
                                f"   3. Chronic dieters 30-45 who've done 5+ restrictive "
                                f"diets. Repeated calorie restriction downregulated thyroid "
                                f"output which slowed gut motility. More fiber made it worse "
                                f"because the gut can't move what's already backed up.\n\n"
                                f"   Each avatar must: name a specific HABIT or LIFE PATTERN, "
                                f"connect it to the ROOT CAUSE, and explain WHY their previous "
                                f"solution attempts failed.\n\n"
                                f"4. DAILY SYMPTOMS: 5-7 specific symptoms this person "
                                f"experiences daily. These must be PHYSICAL SENSATIONS and "
                                f"DAILY LIFE IMPACTS, not clinical terms.\n"
                                f"   BAD: 'elevated systolic pressure', 'endothelial "
                                f"dysfunction', 'inflammatory markers'\n"
                                f"   GOOD: 'waking up with a puffy face every morning', "
                                f"'that heavy feeling in your legs by 3pm', 'brain fog so "
                                f"bad you re-read the same email 3 times', 'dreading "
                                f"stepping on the scale', 'avoiding mirrors because you "
                                f"don't recognize yourself'\n"
                                f"   Symptoms should be things the person would say to a "
                                f"friend, not to a doctor.\n\n"
                                f"5. MASS DESIRE — THIS IS CRITICAL:\n"
                                f"   Mass desire must be an EMOTIONAL, IDENTITY-LEVEL "
                                f"outcome — how the person wants to FEEL and be SEEN. "
                                f"NOT a clinical measurement or biological target.\n"
                                f"   Think: what would this person say they want if you "
                                f"asked them at a dinner party, not in a doctor's office.\n\n"
                                f"   BAD: 'Achieve systolic blood pressure readings below "
                                f"130mmHg within 90 days'\n"
                                f"   GOOD: 'Feel like yourself again — energized, confident, "
                                f"not worried every time you check your numbers'\n"
                                f"   Write ONE powerful sentence.\n\n"
                                f"6. INGREDIENT PATHWAYS: For each key ingredient (1-2 "
                                f"pathways total), show a clear A→B→C→D chain:\n"
                                f"   [Ingredient] → [Root Cause it addresses] → "
                                f"[Pain Point Resolution] → [Mass Desire]\n"
                                f"   Example: 'S-allylcysteine → dissolves arterial calcium "
                                f"deposits → blood pressure normalizes → stop dreading "
                                f"every doctor visit'\n"
                                f"   Keep each pathway to one clear line.\n\n"
                                f"{multi_layer_instruction}"
                                f"\n8. HOOKS: 5 attention-grabbing ad hooks based on the "
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
                                f'  "avatar_profiles": [\n'
                                f'    "Profile 1: 2-3 sentences...",\n'
                                f'    "Profile 2: 2-3 sentences...",\n'
                                f'    "Profile 3: 2-3 sentences..."\n'
                                f'  ],\n'
                                f'  "daily_symptoms": ["symptom in plain language", ...],\n'
                                f'  "mass_desire": "...",\n'
                                f'  "ingredient_pathways": [\n'
                                f'    {{\n'
                                f'      "ingredient": "...",\n'
                                f'      "root_cause": "...",\n'
                                f'      "resolution": "...",\n'
                                f'      "mass_desire": "...",\n'
                                f'      "chain": "A → B → C → D"\n'
                                f"    }}\n"
                                f"  ],\n"
                                f"{multi_layer_json}"
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

                # Parse avatar profiles
                avatar_profiles = []
                for profile in data.get("avatar_profiles", []):
                    if isinstance(profile, str):
                        avatar_profiles.append(AvatarProfile(description=profile))
                    elif isinstance(profile, dict):
                        avatar_profiles.append(
                            AvatarProfile(
                                description=profile.get("description", str(profile))
                            )
                        )

                # Parse ingredient pathways
                pathways = []
                for pw in data.get("ingredient_pathways", []):
                    if isinstance(pw, dict):
                        pathways.append(
                            IngredientPathway(
                                ingredient=pw.get("ingredient", ""),
                                root_cause=pw.get("root_cause", ""),
                                resolution=pw.get("resolution", ""),
                                mass_desire=pw.get("mass_desire", ""),
                                chain=pw.get("chain", ""),
                            )
                        )

                # Parse multi-layer connection (only for tier 3-4)
                multi_layer = None
                if tier >= 3 and data.get("multi_layer_chain"):
                    multi_layer = MultiLayerConnection(
                        full_chain=data.get("multi_layer_chain", ""),
                        why_new_angle=data.get("multi_layer_why_new", ""),
                        new_hope_hook=data.get("multi_layer_new_hope", ""),
                        hooks=data.get("multi_layer_hooks", []),
                    )

                return PositioningDoc(
                    pain_point_name=pain_point.name,
                    root_cause_surface=data.get("root_cause_surface", ""),
                    root_cause_cellular=data.get("root_cause_cellular", ""),
                    root_cause_molecular=data.get("root_cause_molecular", ""),
                    mechanism=data.get("mechanism", ""),
                    avatar_narrative=data.get("avatar_narrative", ""),
                    avatar_profiles=avatar_profiles,
                    daily_symptoms=data.get("daily_symptoms", []),
                    mass_desire=data.get("mass_desire", ""),
                    hooks=data.get("hooks", []),
                    ingredient_pathways=pathways,
                    multi_layer=multi_layer,
                )

            except Exception as e:
                logger.warning(
                    f"Positioning attempt {attempt+1} failed for "
                    f"'{pain_point.name}': {e}"
                )

        return None
