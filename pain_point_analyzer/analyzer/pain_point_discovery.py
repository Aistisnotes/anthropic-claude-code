"""Step 2: Pain Point Discovery.

For each ingredient, identify all health conditions / pain points it is
scientifically linked to.  Then combine across all ingredients, find overlaps,
and rank by number of supporting ingredients.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .ingredient_extractor import Ingredient

logger = logging.getLogger(__name__)


@dataclass
class PainPoint:
    name: str
    description: str = ""
    supporting_ingredients: list[str] = field(default_factory=list)
    ingredient_count: int = 0
    category: str = ""  # e.g., cardiovascular, immune, digestive


@dataclass
class DiscoveryResult:
    pain_points: list[PainPoint]
    ingredient_pain_map: dict[str, list[str]]  # ingredient → pain points


class PainPointDiscovery:
    """Discover pain points linked to product ingredients via Claude API."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        analyzer_cfg = config.get("analyzer", {})
        self.model = analyzer_cfg.get("model", "claude-sonnet-4-20250514")
        self.temperature = analyzer_cfg.get("temperature", 0.3)
        self.max_retries = analyzer_cfg.get("max_retries", 3)
        self.client = anthropic.Anthropic()

    async def discover(
        self, ingredients: list[Ingredient], progress_cb=None
    ) -> DiscoveryResult:
        """Discover pain points for all ingredients, combine, and rank."""
        ingredient_pain_map: dict[str, list[str]] = {}
        all_pain_details: dict[str, dict] = {}  # pain_name → details

        for i, ingredient in enumerate(ingredients):
            if progress_cb:
                progress_cb(
                    f"Researching {ingredient.name} ({i+1}/{len(ingredients)})..."
                )

            pain_points = self._research_ingredient(ingredient)
            ingredient_pain_map[ingredient.name] = []

            for pp in pain_points:
                name = pp["name"]
                ingredient_pain_map[ingredient.name].append(name)

                if name in all_pain_details:
                    all_pain_details[name]["supporting_ingredients"].append(
                        ingredient.name
                    )
                else:
                    all_pain_details[name] = {
                        "name": name,
                        "description": pp.get("description", ""),
                        "category": pp.get("category", ""),
                        "supporting_ingredients": [ingredient.name],
                    }

        # Build ranked list
        ranked = sorted(
            all_pain_details.values(),
            key=lambda x: len(x["supporting_ingredients"]),
            reverse=True,
        )

        pain_points = [
            PainPoint(
                name=pp["name"],
                description=pp["description"],
                supporting_ingredients=pp["supporting_ingredients"],
                ingredient_count=len(pp["supporting_ingredients"]),
                category=pp.get("category", ""),
            )
            for pp in ranked
        ]

        return DiscoveryResult(
            pain_points=pain_points,
            ingredient_pain_map=ingredient_pain_map,
        )

    def _research_ingredient(self, ingredient: Ingredient) -> list[dict]:
        """Use Claude to identify pain points for a single ingredient."""
        amount_str = ""
        if ingredient.amount:
            amount_str = f" (dosage: {ingredient.amount} {ingredient.unit or ''})"

        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    temperature=self.temperature,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"You are a supplement science researcher. "
                                f"For the ingredient '{ingredient.name}'{amount_str}, "
                                f"identify ALL health conditions and pain points this "
                                f"ingredient is scientifically linked to.\n\n"
                                f"Consider:\n"
                                f"- Conditions with published clinical evidence\n"
                                f"- Traditional/historical uses with some scientific backing\n"
                                f"- Biological mechanisms that suggest benefit\n\n"
                                f"For each pain point, provide:\n"
                                f"- name: Short, clear name (e.g., 'High Blood Pressure')\n"
                                f"- description: One sentence explaining the link\n"
                                f"- category: Health category (cardiovascular, immune, "
                                f"digestive, cognitive, metabolic, inflammatory, "
                                f"musculoskeletal, hormonal, skin, respiratory, etc.)\n\n"
                                f"Return ONLY valid JSON:\n"
                                f"```json\n"
                                f'[{{"name": "...", "description": "...", "category": "..."}}]\n'
                                f"```"
                            ),
                        }
                    ],
                )

                text = response.content[0].text
                json_match = re.search(r"\[[\s\S]*\]", text)
                if json_match:
                    items = json.loads(json_match.group())
                    logger.info(
                        f"'{ingredient.name}': found {len(items)} pain points"
                    )
                    return items

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt+1} failed for '{ingredient.name}': {e}"
                )

        return []
