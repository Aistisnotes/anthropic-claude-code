"""Claude-powered extraction of strategic components from ad scripts/copy.

Extracts structured dimensions from ad creative text:
- Pain points
- Root causes (with depth level)
- Mechanisms
- Avatars
- Awareness levels
- Ad formats/styles
- Hook types
- Emotional triggers
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import anthropic


EXTRACTION_PROMPT = """You are an expert direct response copywriter analyzing ad creative scripts.

Extract the following strategic components from this ad script/copy. Be specific and precise — use the EXACT language from the ad, not generic descriptions.

AD NAME: {ad_name}
AD SCRIPT/COPY:
{ad_text}

Extract these components as JSON:

```json
{{
  "pain_point": "The specific problem the ad targets (e.g., 'kidney stones', 'thyroid slowdown', 'crepey skin on arms')",
  "pain_point_category": "Broad category (e.g., 'Kidney', 'Thyroid', 'Skin', 'Weight', 'Energy', 'Cholesterol')",
  "root_cause": "What the ad claims causes the problem (e.g., 'renal lymphatic clogging', 'toxin buildup')",
  "root_cause_depth": "surface | moderate | deep | molecular",
  "mechanism": "How the product/solution works (e.g., 'drainage compound targets vessel walls')",
  "mechanism_depth": "claim-only | process-level | cellular | molecular",
  "avatar": "Who the ad speaks to (e.g., 'Women 45+ who drink wine weekly')",
  "avatar_category": "Broad avatar group (e.g., 'Wine drinkers', 'Busy moms', 'Seniors')",
  "awareness_level": "unaware | problem_aware | solution_aware | product_aware | most_aware",
  "hook_type": "Type of hook used (e.g., 'first-person organ personification', 'question hook', 'shocking stat')",
  "hook_text": "The actual hook text from the ad (first 1-2 sentences)",
  "emotional_triggers": ["fear", "shame", "hope", "curiosity"],
  "ad_format": "UGC | Talking Head | Long Form Static | Video Sales Letter | Short Static | Carousel | Unknown",
  "key_claims": ["Specific claims made in the ad"],
  "cta_type": "Type of call to action"
}}
```

RULES:
- Use EXACT language from the ad, not generic descriptions
- If a component is not clearly present, use "not specified"
- root_cause_depth: "surface" = vague ("toxins"), "moderate" = named system, "deep" = specific pathway, "molecular" = cellular/molecular detail
- Be specific about pain_point_category — use the organ/system name, not "health"

Return ONLY valid JSON."""


async def extract_script_components(
    ad_name: str,
    ad_text: str,
    model: str = "claude-sonnet-4-20250514",
) -> dict[str, Any]:
    """Extract strategic components from a single ad script using Claude.

    Args:
        ad_name: Name/ID of the ad
        ad_text: Full ad script or copy text
        model: Claude model to use

    Returns:
        Dict with extracted components
    """
    if not ad_text or len(ad_text.strip()) < 20:
        return _empty_extraction(ad_name)

    prompt = EXTRACTION_PROMPT.format(ad_name=ad_name, ad_text=ad_text[:3000])

    client = anthropic.AsyncAnthropic()
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        return _parse_extraction(text, ad_name)

    except Exception as e:
        return _empty_extraction(ad_name, error=str(e))


async def extract_batch(
    ads: list[dict[str, str]],
    model: str = "claude-sonnet-4-20250514",
    max_concurrent: int = 5,
) -> list[dict[str, Any]]:
    """Extract components from multiple ads concurrently.

    Args:
        ads: List of dicts with 'name' and 'text' keys
        model: Claude model to use
        max_concurrent: Max concurrent API calls

    Returns:
        List of extraction results
    """
    import asyncio

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _extract_one(ad: dict) -> dict:
        async with semaphore:
            result = await extract_script_components(
                ad["name"], ad.get("text", ""), model
            )
            return result

    tasks = [_extract_one(ad) for ad in ads]
    return await asyncio.gather(*tasks)


def _parse_extraction(text: str, ad_name: str) -> dict[str, Any]:
    """Parse Claude's extraction response."""
    try:
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = text.strip()

        data = json.loads(json_str)
        data["ad_name"] = ad_name
        data["extraction_success"] = True
        return data

    except (json.JSONDecodeError, KeyError) as e:
        return _empty_extraction(ad_name, error=f"Parse error: {e}")


def _empty_extraction(ad_name: str, error: Optional[str] = None) -> dict[str, Any]:
    """Return empty extraction result."""
    return {
        "ad_name": ad_name,
        "extraction_success": False,
        "error": error,
        "pain_point": "not specified",
        "pain_point_category": "Unknown",
        "root_cause": "not specified",
        "root_cause_depth": "surface",
        "mechanism": "not specified",
        "mechanism_depth": "claim-only",
        "avatar": "not specified",
        "avatar_category": "Unknown",
        "awareness_level": "problem_aware",
        "hook_type": "Unknown",
        "hook_text": "",
        "emotional_triggers": [],
        "ad_format": "Unknown",
        "key_claims": [],
        "cta_type": "not specified",
    }
