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
class Connection:
    """A multi-pain-point connection through shared mechanism."""
    name: str = ""
    chain: str = ""
    connected_pain_points: list[dict] = field(default_factory=list)
    shared_root_cause: str = ""
    why_treating_individually_fails: str = ""
    hook_sentence: str = ""
    ad_hooks: list[str] = field(default_factory=list)
    supporting_ingredients: list[str] = field(default_factory=list)
    score: float = 0.0
    # Full deep-dive fields
    root_cause_surface: str = ""
    root_cause_cellular: str = ""
    root_cause_molecular: str = ""
    mechanism: str = ""
    scientific_explanation: str = ""
    avatar_profiles: list[dict] = field(default_factory=list)
    daily_symptoms: list[str] = field(default_factory=list)
    mass_desire: str = ""
    ingredient_roles: list[dict] = field(default_factory=list)


@dataclass
class SaturatedLoophole:
    """A saturated pain point where the formula has a unique edge."""
    pain_point_name: str = ""
    tier: int = 0
    tier_label: str = ""
    ad_count: int = 0
    ingredient_coverage: float = 0.0
    standard_angle: str = ""
    your_angle: str = ""
    connection_name: str = ""
    connection_boost: str = ""
    why_it_works: str = ""
    hook_examples: list[str] = field(default_factory=list)


@dataclass
class PositioningResult:
    docs: list[PositioningDoc]
    connections: list[Connection] = field(default_factory=list)
    saturated_loopholes: list[SaturatedLoophole] = field(default_factory=list)


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

    def generate_connections(
        self,
        all_trend_results: list[TrendResult],
        all_ingredients: list[Ingredient],
        science_reports: list["ScientificReport"],
        progress_cb=None,
    ) -> list[Connection]:
        """Find multi-pain-point connections through shared ingredient mechanisms."""
        if progress_cb:
            progress_cb("Finding multi-pain-point connections...")

        # Step 1: Group pain points by supporting ingredients
        ingredient_to_pps: dict[str, list[dict]] = {}
        for tr in all_trend_results:
            pp = tr.pain_point
            for ing_name in pp.supporting_ingredients:
                if ing_name not in ingredient_to_pps:
                    ingredient_to_pps[ing_name] = []
                ingredient_to_pps[ing_name].append({
                    "name": pp.name,
                    "tier": tr.tier,
                    "tier_label": tr.tier_label,
                    "ad_count": tr.best_score,
                    "supporting_ingredients": pp.supporting_ingredients,
                })

        # Step 2: Find clusters where 3+ pain points share 2+ ingredients
        pp_pairs: dict[tuple, set] = {}  # (pp1, pp2) -> shared ingredients
        all_pp_names = list({
            pp_info["name"]
            for pps in ingredient_to_pps.values()
            for pp_info in pps
        })

        pp_info_map = {}
        for tr in all_trend_results:
            pp_info_map[tr.pain_point.name] = {
                "name": tr.pain_point.name,
                "tier": tr.tier,
                "tier_label": tr.tier_label,
                "ad_count": tr.best_score,
                "supporting_ingredients": tr.pain_point.supporting_ingredients,
            }

        for ing_name, pps in ingredient_to_pps.items():
            pp_names = [p["name"] for p in pps]
            for i in range(len(pp_names)):
                for j in range(i + 1, len(pp_names)):
                    key = tuple(sorted([pp_names[i], pp_names[j]]))
                    if key not in pp_pairs:
                        pp_pairs[key] = set()
                    pp_pairs[key].add(ing_name)

        # Build clusters: groups of 2-3+ pain points that share 2+ ingredients
        clusters = []
        visited = set()
        for (pp1, pp2), shared_ings in sorted(
            pp_pairs.items(), key=lambda x: len(x[1]), reverse=True
        ):
            if len(shared_ings) < 2:
                continue
            # Try to extend to a 3rd pain point
            cluster_pps = {pp1, pp2}
            for pp3 in all_pp_names:
                if pp3 in cluster_pps:
                    continue
                key1 = tuple(sorted([pp1, pp3]))
                key2 = tuple(sorted([pp2, pp3]))
                shared_with_1 = pp_pairs.get(key1, set())
                shared_with_2 = pp_pairs.get(key2, set())
                common = shared_ings & shared_with_1 & shared_with_2
                if len(common) >= 2:
                    cluster_pps.add(pp3)
                    shared_ings = common
                    if len(cluster_pps) >= 3:
                        break

            if len(cluster_pps) < 2:
                continue

            cluster_key = frozenset(cluster_pps)
            if cluster_key in visited:
                continue
            visited.add(cluster_key)

            clusters.append({
                "pain_points": [pp_info_map[n] for n in cluster_pps if n in pp_info_map],
                "shared_ingredients": list(shared_ings),
            })

        # Rank clusters
        def cluster_score(c):
            n_pps = len(c["pain_points"])
            n_ings = len(c["shared_ingredients"])
            total_ads = sum(p.get("ad_count", 0) for p in c["pain_points"])
            saturation_bonus = sum(
                1 for p in c["pain_points"] if p.get("tier", 0) >= 3
            )
            return n_pps * 3 + n_ings * 2 + saturation_bonus * 2 + total_ads / 10000

        clusters.sort(key=cluster_score, reverse=True)
        top_clusters = clusters[:5]

        # Step 3: Ask Claude for each cluster
        connections: list[Connection] = []
        ingredient_list_full = ", ".join(i.name for i in all_ingredients)

        # Build science context
        science_context = ""
        for sr in science_reports:
            science_context += f"\n{sr.pain_point_name}: {sr.summary}\n"
            for ev in sr.ingredient_evidence:
                science_context += f"  - {ev.ingredient_name}: {ev.mechanism}\n"

        for idx, cluster in enumerate(top_clusters):
            if progress_cb:
                progress_cb(
                    f"Generating connection {idx+1}/{len(top_clusters)}..."
                )

            pp_descriptions = "\n".join(
                f"- {p['name']} (Tier: {p.get('tier_label', 'unknown')}, "
                f"~{p.get('ad_count', 0):,} active ads)"
                for p in cluster["pain_points"]
            )
            shared_ings = ", ".join(cluster["shared_ingredients"])

            for attempt in range(self.max_retries):
                try:
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=8192,
                        temperature=self.temperature,
                        messages=[{
                            "role": "user",
                            "content": (
                                f"You are a direct response marketing strategist "
                                f"specializing in health supplements.\n\n"
                                f"A product has these ingredients: {ingredient_list_full}\n\n"
                                f"Scientific research found:\n{science_context}\n\n"
                                f"These pain points share the ingredients [{shared_ings}]:\n"
                                f"{pp_descriptions}\n\n"
                                f"This is a MULTI-PAIN-POINT CONNECTION — a 'super pain point' "
                                f"that's more powerful than any individual one because it "
                                f"explains multiple symptoms at once.\n\n"
                                f"Build a COMPLETE deep-dive for this connection:\n\n"
                                f"1. CONNECTION NAME: A memorable name (e.g. 'The Inflammation "
                                f"Cascade', 'The Cortisol Loop', 'The Gut-Brain Disconnect')\n\n"
                                f"2. CHAIN: The shared mechanism chain showing how ONE pathway "
                                f"causes ALL these symptoms (use → arrows)\n\n"
                                f"3. ROOT CAUSE (3 depth levels):\n"
                                f"   - Surface: What the person notices across ALL connected symptoms\n"
                                f"   - Cellular: What's happening at the cellular level that connects them\n"
                                f"   - Molecular: The deepest upstream molecular cause. Be specific "
                                f"about pathways, enzymes, proteins.\n\n"
                                f"4. MECHANISM: How the shared ingredients address this root cause. "
                                f"Specific biological actions, not generic claims.\n\n"
                                f"5. SCIENTIFIC EXPLANATION: 2-3 sentences explaining the shared "
                                f"pathway and why these symptoms are connected biologically.\n\n"
                                f"6. SHARED ROOT CAUSE: The one root cause nobody else is connecting.\n\n"
                                f"7. WHY TREATING INDIVIDUALLY FAILS: Why addressing each symptom "
                                f"alone doesn't work — they share a root cause.\n\n"
                                f"8. AVATAR PROFILES: 3-5 distinct people who suffer from MULTIPLE "
                                f"of these connected symptoms. Each profile: specific habit → "
                                f"how it triggers the shared root cause → which symptoms they get → "
                                f"why previous solutions failed.\n\n"
                                f"9. DAILY SYMPTOMS: 5-7 specific symptoms spanning ALL connected "
                                f"pain points that this person experiences daily.\n\n"
                                f"10. MASS DESIRE: One powerful emotional, identity-level sentence. "
                                f"NOT clinical. What would this person say they want at a dinner party?\n\n"
                                f"11. HOOK SENTENCE: One powerful 'everything is connected' hook.\n\n"
                                f"12. AD HOOKS: 5 attention-grabbing hooks using the connection angle.\n\n"
                                f"13. INGREDIENT ROLES: For each shared ingredient, explain its "
                                f"specific role in the connection chain.\n\n"
                                f"Return ONLY valid JSON:\n"
                                f"```json\n"
                                f'{{\n'
                                f'  "connection_name": "...",\n'
                                f'  "chain": "... → ... → ... → Symptom 1 + Symptom 2 + Symptom 3",\n'
                                f'  "root_cause_surface": "...",\n'
                                f'  "root_cause_cellular": "...",\n'
                                f'  "root_cause_molecular": "...",\n'
                                f'  "mechanism": "...",\n'
                                f'  "scientific_explanation": "...",\n'
                                f'  "shared_root_cause": "...",\n'
                                f'  "why_treating_individually_fails": "...",\n'
                                f'  "avatar_profiles": [\n'
                                f'    {{"habit": "specific long-term habit", '
                                f'"root_cause_connection": "how it triggers the shared cause", '
                                f'"connected_symptoms": "which symptoms they get", '
                                f'"why_solutions_failed": "why previous attempts failed"}}\n'
                                f'  ],\n'
                                f'  "daily_symptoms": ["symptom spanning multiple pain points", ...],\n'
                                f'  "mass_desire": "...",\n'
                                f'  "hook_sentence": "...",\n'
                                f'  "ad_hooks": ["hook 1", "hook 2", "hook 3", "hook 4", "hook 5"],\n'
                                f'  "ingredient_roles": [\n'
                                f'    {{"ingredient": "name", "role": "its role in the chain"}}\n'
                                f'  ]\n'
                                f'}}\n'
                                f"```"
                            ),
                        }],
                    )

                    text = response.content[0].text
                    json_match = re.search(r"\{[\s\S]*\}", text)
                    if not json_match:
                        continue

                    data = json.loads(json_match.group())

                    conn = Connection(
                        name=data.get("connection_name", f"Connection {idx+1}"),
                        chain=data.get("chain", ""),
                        connected_pain_points=cluster["pain_points"],
                        shared_root_cause=data.get("shared_root_cause", ""),
                        why_treating_individually_fails=data.get(
                            "why_treating_individually_fails", ""
                        ),
                        hook_sentence=data.get("hook_sentence", ""),
                        ad_hooks=data.get("ad_hooks", []),
                        supporting_ingredients=cluster["shared_ingredients"],
                        score=cluster_score(cluster),
                        root_cause_surface=data.get("root_cause_surface", ""),
                        root_cause_cellular=data.get("root_cause_cellular", ""),
                        root_cause_molecular=data.get("root_cause_molecular", ""),
                        mechanism=data.get("mechanism", ""),
                        scientific_explanation=data.get("scientific_explanation", ""),
                        avatar_profiles=data.get("avatar_profiles", []),
                        daily_symptoms=data.get("daily_symptoms", []),
                        mass_desire=data.get("mass_desire", ""),
                        ingredient_roles=data.get("ingredient_roles", []),
                    )
                    connections.append(conn)
                    break

                except Exception as e:
                    logger.warning(
                        f"Connection generation attempt {attempt+1} "
                        f"failed: {e}"
                    )

        return connections

    def generate_saturated_loopholes(
        self,
        all_trend_results: list[TrendResult],
        all_ingredients: list[Ingredient],
        connections: list[Connection],
        progress_cb=None,
    ) -> tuple[list[SaturatedLoophole], dict]:
        """Find loopholes in saturated markets where the formula has an edge.

        Returns (loopholes, metadata) where metadata contains info about
        saturated pain points found and threshold used.
        """
        if progress_cb:
            progress_cb("Scanning for saturated market loopholes...")

        total_ingredients = len(all_ingredients)
        if total_ingredients == 0:
            return [], {"total_saturated": 0, "threshold_used": 0.60}

        # Count total saturated pain points
        saturated_pps = [
            tr for tr in all_trend_results if tr.tier >= 3
        ]
        total_saturated = len(saturated_pps)

        # Try 60% threshold first
        candidates = []
        for tr in saturated_pps:
            pp = tr.pain_point
            coverage = len(pp.supporting_ingredients) / total_ingredients
            if coverage >= 0.60:
                candidates.append({
                    "trend_result": tr,
                    "coverage": coverage,
                })

        threshold_used = 0.60

        # If fewer than 3, retry at 50%
        if len(candidates) < 3:
            candidates = []
            for tr in saturated_pps:
                pp = tr.pain_point
                coverage = len(pp.supporting_ingredients) / total_ingredients
                if coverage >= 0.50:
                    candidates.append({
                        "trend_result": tr,
                        "coverage": coverage,
                    })
            threshold_used = 0.50

        metadata = {
            "total_saturated": total_saturated,
            "threshold_used": threshold_used,
            "candidates_found": len(candidates),
        }

        if not candidates:
            return [], metadata

        # Check which candidates are part of a Connection
        connection_map: dict[str, Connection] = {}
        for conn in connections:
            for cpp in conn.connected_pain_points:
                connection_map[cpp["name"]] = conn

        # Sort by coverage descending, limit to 3
        candidates.sort(key=lambda c: c["coverage"], reverse=True)
        candidates = candidates[:3]

        loopholes: list[SaturatedLoophole] = []
        ingredient_list_full = ", ".join(i.name for i in all_ingredients)

        for idx, cand in enumerate(candidates):
            tr = cand["trend_result"]
            pp = tr.pain_point
            coverage = cand["coverage"]
            conn = connection_map.get(pp.name)

            if progress_cb:
                progress_cb(
                    f"Analyzing loophole {idx+1}/{len(candidates)}: "
                    f"'{pp.name}'..."
                )

            connection_context = ""
            if conn:
                connection_context = (
                    f"\nThis pain point is part of the '{conn.name}' connection, "
                    f"which links it to {', '.join(c['name'] for c in conn.connected_pain_points)}. "
                    f"Shared mechanism: {conn.chain}\n"
                    f"Use this broader story as part of the unique angle.\n"
                )

            for attempt in range(self.max_retries):
                try:
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=4096,
                        temperature=self.temperature,
                        messages=[{
                            "role": "user",
                            "content": (
                                f"You are a direct response marketing strategist.\n\n"
                                f"The pain point '{pp.name}' is SATURATED ({tr.best_score:,} "
                                f"active ads, tier: {tr.tier_label}). But this product's "
                                f"formula covers {coverage:.0%} of its ingredients for "
                                f"this pain point.\n\n"
                                f"Product ingredients: {ingredient_list_full}\n"
                                f"Ingredients supporting this pain point: "
                                f"{', '.join(pp.supporting_ingredients)}\n"
                                f"{connection_context}\n"
                                f"Find the LOOPHOLE — the unique angle that lets this "
                                f"product compete despite saturation.\n\n"
                                f"Return ONLY valid JSON:\n"
                                f"```json\n"
                                f'{{\n'
                                f'  "standard_angle": "What most competitors say about this pain point",\n'
                                f'  "your_angle": "The deeper, unique angle based on ingredient mechanisms",\n'
                                f'  "why_it_works": "Why this works despite saturation — 2-3 sentences",\n'
                                f'  "hook_examples": ["hook 1", "hook 2", "hook 3"]\n'
                                f'}}\n'
                                f"```"
                            ),
                        }],
                    )

                    text = response.content[0].text
                    json_match = re.search(r"\{[\s\S]*\}", text)
                    if not json_match:
                        continue

                    data = json.loads(json_match.group())

                    conn_boost = ""
                    conn_name = ""
                    if conn:
                        conn_name = conn.name
                        other_pps = [
                            c["name"] for c in conn.connected_pain_points
                            if c["name"] != pp.name
                        ]
                        conn_boost = (
                            f"This loophole is strengthened by the "
                            f"{conn.name} — your mechanism also addresses "
                            f"{', '.join(other_pps)}, giving you a broader "
                            f"story competitors can't match."
                        )

                    loophole = SaturatedLoophole(
                        pain_point_name=pp.name,
                        tier=tr.tier,
                        tier_label=tr.tier_label,
                        ad_count=tr.best_score,
                        ingredient_coverage=coverage,
                        standard_angle=data.get("standard_angle", ""),
                        your_angle=data.get("your_angle", ""),
                        connection_name=conn_name,
                        connection_boost=conn_boost,
                        why_it_works=data.get("why_it_works", ""),
                        hook_examples=data.get("hook_examples", []),
                    )
                    loopholes.append(loophole)
                    break

                except Exception as e:
                    logger.warning(
                        f"Loophole generation attempt {attempt+1} "
                        f"failed for '{pp.name}': {e}"
                    )

        # Rank: those with connections rank higher
        loopholes.sort(
            key=lambda l: (1 if l.connection_name else 0, l.ingredient_coverage),
            reverse=True,
        )
        return loopholes, metadata
