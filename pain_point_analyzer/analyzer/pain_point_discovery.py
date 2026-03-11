"""Step 2: Pain Point Discovery.

For each ingredient, identify all health conditions / pain points it is
scientifically linked to.  Then combine across all ingredients, find overlaps,
and rank by number of supporting ingredients.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import anthropic

from .ingredient_extractor import Ingredient

logger = logging.getLogger(__name__)

CANCER_KEYWORDS = [
    "cancer", "tumor", "carcinoma", "oncology", "malignant",
    "chemotherapy", "metastasis", "leukemia", "lymphoma",
]

# Discovery cache
DISCOVERY_CACHE_FILE = (
    Path(__file__).parent.parent / "output" / "discovery_cache.json"
)
DISCOVERY_CACHE_TTL_DAYS = 14


def _make_cache_key(ingredients: list[Ingredient]) -> str:
    """Create a deterministic cache key from sorted ingredient names."""
    sorted_names = sorted(ing.name.lower().strip() for ing in ingredients)
    key_str = "|".join(sorted_names)
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def _load_discovery_cache() -> dict:
    """Load the discovery cache from disk."""
    if DISCOVERY_CACHE_FILE.exists():
        try:
            return json.loads(DISCOVERY_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_discovery_cache(cache: dict) -> None:
    """Save the discovery cache to disk."""
    DISCOVERY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_CACHE_FILE.write_text(
        json.dumps(cache, indent=2, default=str), encoding="utf-8"
    )


def clear_discovery_cache() -> None:
    """Clear the entire discovery cache."""
    if DISCOVERY_CACHE_FILE.exists():
        DISCOVERY_CACHE_FILE.unlink()


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
    from_cache: bool = False
    cache_date: str = ""


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
        # Check discovery cache first
        cache_key = _make_cache_key(ingredients)
        cache = _load_discovery_cache()
        cached_entry = cache.get(cache_key)

        if cached_entry:
            expires_str = cached_entry.get("expires", "")
            try:
                expires_dt = datetime.fromisoformat(expires_str)
                if datetime.utcnow() < expires_dt:
                    # Cache hit — use cached pain points
                    cache_date = cached_entry.get("last_generated", "")
                    if progress_cb:
                        progress_cb(
                            f"Using cached pain point discovery "
                            f"(generated {cache_date[:10]})"
                        )
                    logger.info(
                        f"Discovery cache hit for {len(ingredients)} ingredients "
                        f"(generated {cache_date})"
                    )

                    pain_points = [
                        PainPoint(
                            name=pp["name"],
                            description=pp.get("description", ""),
                            supporting_ingredients=pp["supporting_ingredients"],
                            ingredient_count=len(pp["supporting_ingredients"]),
                            category=pp.get("category", ""),
                        )
                        for pp in cached_entry["pain_points"]
                    ]
                    ingredient_pain_map = cached_entry.get(
                        "ingredient_pain_map", {}
                    )
                    return DiscoveryResult(
                        pain_points=pain_points,
                        ingredient_pain_map=ingredient_pain_map,
                        from_cache=True,
                        cache_date=cache_date[:10] if cache_date else "",
                    )
            except (ValueError, TypeError):
                pass  # Expired or bad date — run fresh

        if progress_cb:
            progress_cb("Running fresh pain point discovery...")
        logger.info(
            f"Discovery cache miss — running fresh for {len(ingredients)} ingredients"
        )

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

        # Filter out cancer-related pain points
        pre_filter_count = len(ranked)
        ranked = [
            pp for pp in ranked
            if not any(
                kw in pp["name"].lower() or kw in pp.get("description", "").lower()
                for kw in CANCER_KEYWORDS
            )
        ]
        filtered_count = pre_filter_count - len(ranked)
        if filtered_count > 0:
            logger.info(f"Filtered out {filtered_count} cancer-related pain points")

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

        # Save to discovery cache
        now = datetime.utcnow()
        cache[cache_key] = {
            "ingredients": sorted(ing.name for ing in ingredients),
            "pain_points": [
                {
                    "name": pp.name,
                    "description": pp.description,
                    "supporting_ingredients": pp.supporting_ingredients,
                    "category": pp.category,
                }
                for pp in pain_points
            ],
            "ingredient_pain_map": ingredient_pain_map,
            "last_generated": now.isoformat(),
            "expires": (now + timedelta(days=DISCOVERY_CACHE_TTL_DAYS)).isoformat(),
        }
        _save_discovery_cache(cache)
        logger.info(f"Discovery results cached for {len(ingredients)} ingredients")

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
                                f"IMPORTANT: Do NOT include any cancer-related pain points. "
                                f"Cancer claims are non-compliant on Meta advertising platforms.\n\n"
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
