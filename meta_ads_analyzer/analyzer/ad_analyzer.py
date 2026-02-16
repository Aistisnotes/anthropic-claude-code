"""Single-ad analysis using Claude API.

Takes filtered AdContent and produces structured AdAnalysis with:
- Target customer profile
- Pain points, symptoms, root cause
- Mechanism and delivery mechanism
- Mass desire and big idea
- Copy quality scoring
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Optional

import anthropic

from meta_ads_analyzer.models import AdAnalysis, AdContent
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "ad_analysis.txt"


class AdAnalyzer:
    """Analyze individual ads using Claude API."""

    def __init__(self, config: dict[str, Any]):
        a_cfg = config.get("analyzer", {})
        self.model = a_cfg.get("model", "claude-sonnet-4-20250514")
        self.max_concurrent = a_cfg.get("max_concurrent", 3)
        self.temperature = a_cfg.get("temperature", 0.3)
        self.max_retries = a_cfg.get("max_retries", 3)
        self._client = anthropic.AsyncAnthropic()
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        if PROMPT_PATH.exists():
            return PROMPT_PATH.read_text()
        raise FileNotFoundError(f"Analysis prompt not found: {PROMPT_PATH}")

    async def analyze_batch(self, ads: list[AdContent]) -> dict[str, AdAnalysis | None]:
        """Analyze a batch of ads concurrently.

        Returns mapping of ad_id -> AdAnalysis (None if failed).
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: dict[str, AdAnalysis | None] = {}

        async def _analyze_one(ad: AdContent):
            async with semaphore:
                result = await self._analyze_single(ad)
                results[ad.ad_id] = result

        logger.info(f"Analyzing {len(ads)} ads with Claude ({self.model})")
        tasks = [_analyze_one(ad) for ad in ads]
        await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for v in results.values() if v is not None)
        logger.info(f"Successfully analyzed {success}/{len(ads)} ads")
        return results

    async def _analyze_single(self, ad: AdContent) -> Optional[AdAnalysis]:
        """Analyze a single ad with retries."""
        prompt = self._build_prompt(ad)

        for attempt in range(self.max_retries):
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    temperature=self.temperature,
                    messages=[{"role": "user", "content": prompt}],
                )

                text = response.content[0].text
                analysis = self._parse_response(ad, text)

                if analysis:
                    logger.info(
                        f"Analyzed ad {ad.ad_id}: confidence={analysis.analysis_confidence:.2f}, "
                        f"quality={analysis.copy_quality_score:.2f}"
                    )
                    return analysis

                logger.warning(f"Failed to parse response for ad {ad.ad_id}, attempt {attempt + 1}")

            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited, waiting {wait}s before retry")
                await asyncio.sleep(wait)
            except anthropic.APIError as e:
                logger.error(f"API error analyzing ad {ad.ad_id}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Unexpected error analyzing ad {ad.ad_id}: {e}")
                break

        return None

    def _build_prompt(self, ad: AdContent) -> str:
        """Build the analysis prompt from template and ad content."""
        prompt = self._prompt_template

        # Simple template replacement (Mustache-like)
        prompt = prompt.replace("{{brand}}", ad.brand or "Unknown")
        prompt = prompt.replace("{{ad_type}}", ad.ad_type.value)
        prompt = prompt.replace("{{headline}}", ad.headline or "N/A")

        # Conditional blocks
        if ad.transcript:
            prompt = re.sub(
                r"\{\{#if transcript\}\}(.*?)\{\{/if\}\}",
                lambda m: m.group(1).replace("{{transcript}}", ad.transcript),
                prompt,
                flags=re.DOTALL,
            )
        else:
            prompt = re.sub(
                r"\{\{#if transcript\}\}.*?\{\{/if\}\}", "", prompt, flags=re.DOTALL
            )

        if ad.primary_text:
            prompt = re.sub(
                r"\{\{#if primary_text\}\}(.*?)\{\{/if\}\}",
                lambda m: m.group(1).replace("{{primary_text}}", ad.primary_text),
                prompt,
                flags=re.DOTALL,
            )
        else:
            prompt = re.sub(
                r"\{\{#if primary_text\}\}.*?\{\{/if\}\}", "", prompt, flags=re.DOTALL
            )

        return prompt

    def _parse_response(self, ad: AdContent, response_text: str) -> Optional[AdAnalysis]:
        """Parse Claude's JSON response into AdAnalysis."""
        try:
            # Extract JSON from response (may be wrapped in markdown code block)
            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try parsing the entire response as JSON
                json_str = response_text.strip()

            data = json.loads(json_str)

            return AdAnalysis(
                ad_id=ad.ad_id,
                brand=ad.brand,
                target_customer_profile=data.get("target_customer_profile", ""),
                target_demographics=data.get("target_demographics", ""),
                target_psychographics=data.get("target_psychographics", ""),
                pain_points=data.get("pain_points", []),
                pain_point_symptoms=data.get("pain_point_symptoms", []),
                root_cause=data.get("root_cause", ""),
                mechanism=data.get("mechanism", ""),
                product_delivery_mechanism=data.get("product_delivery_mechanism", ""),
                mass_desire=data.get("mass_desire", ""),
                big_idea=data.get("big_idea", ""),
                ad_angle=data.get("ad_angle", ""),
                emotional_triggers=data.get("emotional_triggers", []),
                awareness_level=data.get("awareness_level", ""),
                sophistication_level=data.get("sophistication_level", ""),
                hook_type=data.get("hook_type", ""),
                cta_strategy=data.get("cta_strategy", ""),
                analysis_confidence=float(data.get("analysis_confidence", 0.0)),
                copy_quality_score=float(data.get("copy_quality_score", 0.0)),
                raw_llm_response=response_text,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse analysis response for {ad.ad_id}: {e}")
            return None
