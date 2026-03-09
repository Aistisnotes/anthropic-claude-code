"""Step 3: Google Trends Validation.

For each pain point, generate keyword variants and query Google Trends.
Rank by search volume and select the top N pain points.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import anthropic

from .pain_point_discovery import PainPoint

logger = logging.getLogger(__name__)


@dataclass
class KeywordScore:
    keyword: str
    score: int  # Google Trends relative interest (0-100)
    variant_type: str  # clinical, plain_english, symptom, question


@dataclass
class TrendResult:
    pain_point: PainPoint
    keywords: list[KeywordScore]
    best_keyword: str
    best_score: int


@dataclass
class ValidationResult:
    all_results: list[TrendResult]  # all pain points with scores
    top_results: list[TrendResult]  # top N by volume


class TrendsValidator:
    """Validate pain point demand via Google Trends."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        trends_cfg = config.get("trends", {})
        self.geo = trends_cfg.get("geo", "US")
        self.timeframe = trends_cfg.get("timeframe", "today 5-y")
        self.api_pause = trends_cfg.get("api_pause", 2.0)
        self.top_n = config.get("pipeline", {}).get("top_pain_points", 3)
        self.model = config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514")
        self.client = anthropic.Anthropic()

    async def validate(
        self, pain_points: list[PainPoint], progress_cb=None
    ) -> ValidationResult:
        """Query Google Trends for all pain points, rank by volume."""
        # Generate keywords for all pain points
        if progress_cb:
            progress_cb("Generating search keywords...")
        keyword_map = self._generate_keywords(pain_points)

        results: list[TrendResult] = []

        for i, pp in enumerate(pain_points):
            if progress_cb:
                progress_cb(
                    f"Checking trends for '{pp.name}' ({i+1}/{len(pain_points)})..."
                )

            keywords = keyword_map.get(pp.name, [])
            if not keywords:
                continue

            scored = self._query_trends(keywords)
            if scored:
                best = max(scored, key=lambda x: x.score)
                results.append(
                    TrendResult(
                        pain_point=pp,
                        keywords=scored,
                        best_keyword=best.keyword,
                        best_score=best.score,
                    )
                )
            else:
                # No trends data — assign score 0
                results.append(
                    TrendResult(
                        pain_point=pp,
                        keywords=[
                            KeywordScore(kw, 0, "unknown") for kw in keywords
                        ],
                        best_keyword=keywords[0] if keywords else pp.name,
                        best_score=0,
                    )
                )

        # Sort by best score descending
        results.sort(key=lambda x: x.best_score, reverse=True)

        # Select top N
        top = results[: self.top_n]

        return ValidationResult(all_results=results, top_results=top)

    def _generate_keywords(
        self, pain_points: list[PainPoint]
    ) -> dict[str, list[str]]:
        """Use Claude to generate search keyword variants for each pain point."""
        pp_names = [pp.name for pp in pain_points]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "For each health pain point below, generate 4 Google search "
                        "keyword variants that a normal person would type:\n\n"
                        "1. Clinical/medical term + 'supplement' (e.g., 'hypertension supplement')\n"
                        "2. Plain English version + 'supplement' (e.g., 'high blood pressure supplement')\n"
                        "3. Symptom-based (e.g., 'lower blood pressure naturally')\n"
                        "4. Question-based (e.g., 'how to reduce blood pressure')\n\n"
                        "IMPORTANT: Use generalized, straightforward keywords. "
                        "Not niche long-tails. Think about what a normal person "
                        "would type into Google. Keep keywords short and natural.\n\n"
                        f"Pain points: {json.dumps(pp_names)}\n\n"
                        "Return ONLY valid JSON:\n"
                        "```json\n"
                        "{\n"
                        '  "pain_point_name": ["keyword1", "keyword2", "keyword3", "keyword4"]\n'
                        "}\n"
                        "```"
                    ),
                }
            ],
        )

        try:
            text = response.content[0].text
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.error(f"Failed to parse keyword generation response: {e}")

        # Fallback: simple keyword generation
        result = {}
        for pp in pain_points:
            name_lower = pp.name.lower()
            result[pp.name] = [
                f"{name_lower} supplement",
                f"{name_lower} natural remedy",
                f"how to improve {name_lower}",
                f"{name_lower} treatment",
            ]
        return result

    def _query_trends(self, keywords: list[str]) -> list[KeywordScore]:
        """Query Google Trends for a batch of keywords."""
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US", tz=360)
        except ImportError:
            logger.warning("pytrends not installed, using fallback scoring")
            return self._fallback_scoring(keywords)
        except Exception as e:
            logger.warning(f"pytrends init failed: {e}, using fallback")
            return self._fallback_scoring(keywords)

        results = []
        variant_types = ["clinical", "plain_english", "symptom", "question"]

        # pytrends can compare up to 5 keywords at once
        batch_size = 5
        for batch_start in range(0, len(keywords), batch_size):
            batch = keywords[batch_start : batch_start + batch_size]

            try:
                pytrends.build_payload(
                    batch,
                    cat=0,
                    timeframe=self.timeframe,
                    geo=self.geo,
                )
                interest = pytrends.interest_over_time()

                if interest.empty:
                    for j, kw in enumerate(batch):
                        idx = batch_start + j
                        vtype = variant_types[idx] if idx < len(variant_types) else "other"
                        results.append(KeywordScore(kw, 0, vtype))
                else:
                    for j, kw in enumerate(batch):
                        idx = batch_start + j
                        vtype = variant_types[idx] if idx < len(variant_types) else "other"
                        if kw in interest.columns:
                            avg_score = int(interest[kw].mean())
                            results.append(KeywordScore(kw, avg_score, vtype))
                        else:
                            results.append(KeywordScore(kw, 0, vtype))

                time.sleep(self.api_pause)

            except Exception as e:
                logger.warning(f"Trends query failed for batch {batch}: {e}")
                for j, kw in enumerate(batch):
                    idx = batch_start + j
                    vtype = variant_types[idx] if idx < len(variant_types) else "other"
                    results.append(KeywordScore(kw, 0, vtype))

        return results

    def _fallback_scoring(self, keywords: list[str]) -> list[KeywordScore]:
        """Use Claude to estimate relative search volume when pytrends fails."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Estimate the relative Google search volume (0-100 scale) "
                        "for each of these health-related keywords in the US. "
                        "100 = highest volume, 0 = almost no searches.\n\n"
                        f"Keywords: {json.dumps(keywords)}\n\n"
                        "Return ONLY valid JSON:\n"
                        "```json\n"
                        '{"keyword": score, "keyword2": score}\n'
                        "```"
                    ),
                }
            ],
        )

        variant_types = ["clinical", "plain_english", "symptom", "question"]
        try:
            text = response.content[0].text
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                scores = json.loads(json_match.group())
                return [
                    KeywordScore(
                        kw,
                        scores.get(kw, 0),
                        variant_types[i] if i < len(variant_types) else "other",
                    )
                    for i, kw in enumerate(keywords)
                ]
        except Exception:
            pass

        return [
            KeywordScore(kw, 0, variant_types[i] if i < len(variant_types) else "other")
            for i, kw in enumerate(keywords)
        ]
