"""Deep component extraction from ad scripts/briefs using Claude.

Extracts structured JSON with pain points, symptoms, root cause chains,
mechanisms, avatars, hooks, emotional triggers, and more.
Uses claude-sonnet-4-20250514 with asyncio.Semaphore(5) for parallel processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

import anthropic

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are an expert direct-response copywriting analyst. Extract structured components from this ad script/brief.

SCRIPT/BRIEF:
{script_text}

AD METADATA:
- Ad Name: {ad_name}
- Status: {status}
- Spend: {spend}
- ROAS: {roas}

Extract into this EXACT JSON structure. Be specific and concrete — no generic descriptions.

CRITICAL RULES:
- For avatars: NOT "Women over 40 who are health conscious". YES: specific behavior → biological impact → root cause connection → why previous solutions failed.
- For root_cause.chain: Use arrow notation showing the full biological chain (e.g., "alcohol consumption → lymphatic vessel inflammation → renal lymphatic clogging → reduced kidney filtration → toxin buildup")
- For hooks: Extract the FULL TEXT of each hook variant
- For symptoms: List specific symptoms mentioned, not categories
- If something is not present in the script, use null or empty list — do NOT invent

Return ONLY valid JSON, no markdown fences:
{
  "hooks": ["hook 1 full text", "hook 2 full text"],
  "body_copy_summary": "2-3 sentence summary of the body copy",
  "pain_point": "specific pain point targeted",
  "symptoms": ["specific symptom 1", "specific symptom 2"],
  "root_cause": {
    "depth": "surface | cellular | molecular",
    "chain": "cause → effect → effect → effect chain"
  },
  "mechanism": {
    "ump": "unique mechanism of problem — what's causing the issue",
    "ums": "unique mechanism of solution — how the product fixes it"
  },
  "avatar": {
    "behavior": "specific behavior or habit of the target",
    "impact": "how that behavior creates biological impact",
    "root_cause_connection": "how it connects to the root cause",
    "why_previous_failed": "why other solutions don't work for this avatar"
  },
  "ad_format": "UGC | AI | VSL | Long Form Static | Short Form Video | Image | Carousel",
  "awareness_level": "unaware | problem_aware | solution_aware | product_aware | most_aware",
  "emotional_triggers": ["specific emotion 1", "specific emotion 2"],
  "language_patterns": ["specific pattern like first-person organ personification", "pattern 2"],
  "lead_type": "story | problem-solution | testimonial | educational | fear | curiosity | news",
  "cta_type": "learn_more | shop_now | sign_up | watch_video | get_offer",
  "hook_type": "first-person | question | statistic | fear | curiosity | authority | testimonial | news"
}"""

# Semaphore for parallel extraction (max 5 concurrent)
_semaphore = asyncio.Semaphore(5)


async def extract_components(
    script_text: str,
    ad_name: str = "",
    status: str = "",
    spend: float = 0.0,
    roas: float = 0.0,
    api_key: Optional[str] = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Extract structured components from a single ad script using Claude.

    Args:
        script_text: The full ad script or brief text.
        ad_name: Name/ID of the ad.
        status: Win/loss/untested status.
        spend: Total spend amount.
        roas: Return on ad spend.
        api_key: Anthropic API key (defaults to env var).
        max_retries: Number of retries on rate limit.

    Returns:
        Extracted component dict matching the JSON schema above.
    """
    if not script_text or not script_text.strip():
        return _empty_extraction()

    client = anthropic.AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    prompt = EXTRACTION_PROMPT.format(
        script_text=script_text[:8000],  # Limit to avoid token overflow
        ad_name=ad_name,
        status=status,
        spend=f"${spend:,.2f}" if spend else "Unknown",
        roas=f"{roas:.2f}x" if roas else "Unknown",
    )

    for attempt in range(max_retries):
        try:
            async with _semaphore:
                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2000,
                    temperature=0.1,
                    messages=[{"role": "user", "content": prompt}],
                )

            text = response.content[0].text.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()

            parsed = json.loads(text)
            return _normalize_extraction(parsed)

        except anthropic.RateLimitError:
            wait = 2 ** (attempt + 1)
            logger.warning(f"Rate limited on {ad_name}, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for {ad_name}: {e}")
            return _empty_extraction()
        except Exception as e:
            logger.error(f"Extraction failed for {ad_name}: {e}")
            return _empty_extraction()

    logger.error(f"Max retries exceeded for {ad_name}")
    return _empty_extraction()


async def extract_batch(
    ads: list[dict[str, Any]],
    api_key: Optional[str] = None,
    progress_callback=None,
) -> list[dict[str, Any]]:
    """Extract components from multiple ads in parallel.

    Args:
        ads: List of ad dicts, each with keys: script_text, ad_name, status, spend, roas.
        api_key: Anthropic API key.
        progress_callback: Optional callable(completed, total) for progress updates.

    Returns:
        List of extraction dicts in the same order as input.
    """
    completed = 0
    total = len(ads)

    async def _extract_one(ad: dict) -> dict:
        nonlocal completed
        result = await extract_components(
            script_text=ad.get("script_text", ""),
            ad_name=ad.get("ad_name", ""),
            status=ad.get("status", ""),
            spend=ad.get("spend", 0.0),
            roas=ad.get("roas", 0.0),
            api_key=api_key,
        )
        completed += 1
        if progress_callback:
            progress_callback(completed, total)
        return result

    tasks = [_extract_one(ad) for ad in ads]
    return await asyncio.gather(*tasks)


def _normalize_extraction(data: dict) -> dict:
    """Normalize extracted data to ensure consistent structure."""
    return {
        "hooks": data.get("hooks") or [],
        "body_copy_summary": data.get("body_copy_summary") or "",
        "pain_point": data.get("pain_point") or "",
        "symptoms": data.get("symptoms") or [],
        "root_cause": {
            "depth": (data.get("root_cause") or {}).get("depth") or "",
            "chain": (data.get("root_cause") or {}).get("chain") or "",
        },
        "mechanism": {
            "ump": (data.get("mechanism") or {}).get("ump") or "",
            "ums": (data.get("mechanism") or {}).get("ums") or "",
        },
        "avatar": {
            "behavior": (data.get("avatar") or {}).get("behavior") or "",
            "impact": (data.get("avatar") or {}).get("impact") or "",
            "root_cause_connection": (data.get("avatar") or {}).get("root_cause_connection") or "",
            "why_previous_failed": (data.get("avatar") or {}).get("why_previous_failed") or "",
        },
        "ad_format": data.get("ad_format") or "",
        "awareness_level": data.get("awareness_level") or "",
        "emotional_triggers": data.get("emotional_triggers") or [],
        "language_patterns": data.get("language_patterns") or [],
        "lead_type": data.get("lead_type") or "",
        "cta_type": data.get("cta_type") or "",
        "hook_type": data.get("hook_type") or "",
    }


def _empty_extraction() -> dict:
    """Return an empty extraction with the correct schema."""
    return {
        "hooks": [],
        "body_copy_summary": "",
        "pain_point": "",
        "symptoms": [],
        "root_cause": {"depth": "", "chain": ""},
        "mechanism": {"ump": "", "ums": ""},
        "avatar": {
            "behavior": "",
            "impact": "",
            "root_cause_connection": "",
            "why_previous_failed": "",
        },
        "ad_format": "",
        "awareness_level": "",
        "emotional_triggers": [],
        "language_patterns": [],
        "lead_type": "",
        "cta_type": "",
        "hook_type": "",
    }
