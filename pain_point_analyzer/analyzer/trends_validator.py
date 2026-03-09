"""Step 3: Meta Ad Library Demand Validation.

For each pain point, generate broad keyword variants and query Meta Ad Library
for total active ad counts. Tier the pain points by market saturation and
select the top N opportunities (lowest saturation first).

Tiers:
  - Tier 1 LOOPHOLE: 0-2,000 active ads (green)
  - Tier 2 AVERAGE: 2,000-5,000 active ads (yellow)
  - Tier 3 HIGH SOPHISTICATION: 5,000-15,000 active ads (orange)
  - Tier 4 DO NOT TOUCH: 15,000+ active ads (red)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

import anthropic

from .pain_point_discovery import PainPoint

logger = logging.getLogger(__name__)

# ── Tier definitions ──────────────────────────────────────────────────────────
TIER_LOOPHOLE = 1
TIER_AVERAGE = 2
TIER_HIGH_SOPHISTICATION = 3
TIER_DO_NOT_TOUCH = 4

TIER_LABELS = {
    TIER_LOOPHOLE: "LOOPHOLE",
    TIER_AVERAGE: "AVERAGE",
    TIER_HIGH_SOPHISTICATION: "HIGH SOPHISTICATION",
    TIER_DO_NOT_TOUCH: "DO NOT TOUCH",
}

TIER_COLORS = {
    TIER_LOOPHOLE: "green",
    TIER_AVERAGE: "yellow",
    TIER_HIGH_SOPHISTICATION: "orange",
    TIER_DO_NOT_TOUCH: "red",
}


def _classify_tier(ad_count: int) -> int:
    """Classify an ad count into a market tier."""
    if ad_count < 2000:
        return TIER_LOOPHOLE
    elif ad_count < 5000:
        return TIER_AVERAGE
    elif ad_count < 15000:
        return TIER_HIGH_SOPHISTICATION
    else:
        return TIER_DO_NOT_TOUCH


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class KeywordScore:
    keyword: str
    score: int  # total active ad count from Meta Ad Library
    variant_type: str  # broad, symptom, clinical


@dataclass
class TrendResult:
    pain_point: PainPoint
    keywords: list[KeywordScore]
    best_keyword: str
    best_score: int  # highest ad count across keyword variants
    tier: int = TIER_LOOPHOLE
    tier_label: str = ""
    tier_color: str = "green"

    def __post_init__(self):
        self.tier = _classify_tier(self.best_score)
        self.tier_label = TIER_LABELS[self.tier]
        self.tier_color = TIER_COLORS[self.tier]


@dataclass
class ValidationResult:
    all_results: list[TrendResult]  # all pain points with scores
    top_results: list[TrendResult]  # top N by opportunity (lower ads = better)


# ── Ad count scraper ──────────────────────────────────────────────────────────
async def _get_ad_count(keyword: str, headless: bool = True) -> int:
    """Search Meta Ad Library for a keyword and return the total ad count.

    Extracts the count from the results header text like
    "Showing results for 12,345 ads" or similar patterns Meta uses.
    """
    from playwright.async_api import async_playwright

    url = (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country=US"
        f"&q={quote_plus(keyword)}"
    )

    ad_count = 0

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(3)

                # Dismiss cookie/login dialogs
                for selector in [
                    'button[data-cookiebanner="accept_button"]',
                    'button:has-text("Allow all cookies")',
                    'button:has-text("Accept All")',
                    'button:has-text("Allow essential and optional cookies")',
                    'button:has-text("Decline optional cookies")',
                    '[aria-label="Close"]',
                ]:
                    btn = page.locator(selector)
                    if await btn.count() > 0:
                        await btn.first.click()
                        await asyncio.sleep(1)
                        break

                await asyncio.sleep(2)

                # Extract ad count from the page
                # Meta typically shows something like:
                #   "Showing results for 12,345 ads about..."
                #   "12,345 results"
                #   or a count in the page header area
                ad_count = await page.evaluate(
                    r"""
                    () => {
                        const bodyText = document.body.innerText || '';

                        // Pattern 1: "X results" or "Showing X results"
                        // Pattern 2: "About X ads" / "X ads"
                        // Pattern 3: "Showing results for X ads"
                        const patterns = [
                            /(?:showing\s+)?(?:results?\s+for\s+)?(\d[\d,]+)\s+(?:ads?|results?)/i,
                            /(?:about\s+)?(\d[\d,]+)\s+ads?/i,
                            /(\d[\d,]+)\s+(?:total\s+)?(?:active\s+)?(?:ads?|results?)/i,
                        ];

                        for (const pattern of patterns) {
                            const match = bodyText.match(pattern);
                            if (match) {
                                const numStr = match[1].replace(/,/g, '');
                                const num = parseInt(numStr, 10);
                                if (!isNaN(num) && num > 0) {
                                    return num;
                                }
                            }
                        }

                        // Fallback: count ad cards visible on page as a minimum estimate
                        // Each ad card typically has a link with /ads/library/?id=XXXXXX
                        const adLinks = document.querySelectorAll(
                            'a[href*="/ads/library/"]'
                        );
                        let adCardCount = 0;
                        for (const link of adLinks) {
                            const href = link.href || link.getAttribute('href') || '';
                            if (/(?:id=|library\/)\d{10,}/.test(href)) {
                                adCardCount++;
                            }
                        }
                        // Deduplicate (multiple links per card)
                        const uniqueIds = new Set();
                        for (const link of adLinks) {
                            const href = link.href || link.getAttribute('href') || '';
                            const m = href.match(/(?:id=|library\/)(\d{10,})/);
                            if (m) uniqueIds.add(m[1]);
                        }
                        return uniqueIds.size;
                    }
                    """
                )

                logger.info(f"Meta Ad Library: '{keyword}' → {ad_count} ads")

            finally:
                await context.close()
                await browser.close()

    except Exception as e:
        logger.warning(f"Meta Ad Library scrape failed for '{keyword}': {e}")

    return ad_count or 0


class TrendsValidator:
    """Validate pain point demand via Meta Ad Library ad counts."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.top_n = config.get("pipeline", {}).get("top_pain_points", 3)
        self.model = config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514")
        self.headless = config.get("scraper", {}).get("headless", True)
        self.client = anthropic.Anthropic()

    async def validate(
        self, pain_points: list[PainPoint], progress_cb=None
    ) -> ValidationResult:
        """Query Meta Ad Library for all pain points, rank by opportunity."""
        max_queries = self.config.get("trends", {}).get("max_pain_points", 15)
        query_points = pain_points[:max_queries]

        if len(pain_points) > max_queries:
            logger.info(
                f"Capping demand queries to top {max_queries} pain points "
                f"(skipping {len(pain_points) - max_queries} lower-priority ones)"
            )

        # Generate broad keyword variants
        if progress_cb:
            progress_cb("Generating broad search keywords...")
        keyword_map = self._generate_keywords(query_points)

        results: list[TrendResult] = []

        for i, pp in enumerate(query_points):
            if progress_cb:
                progress_cb(
                    f"Checking Meta Ad Library for '{pp.name}' "
                    f"({i+1}/{len(query_points)})..."
                )

            keywords = keyword_map.get(pp.name, [])
            if not keywords:
                keywords = [pp.name.lower()]

            scored: list[KeywordScore] = []
            for j, kw in enumerate(keywords):
                variant_type = ["broad", "symptom", "clinical"][j] if j < 3 else "other"
                count = await _get_ad_count(kw, headless=self.headless)
                scored.append(KeywordScore(kw, count, variant_type))
                # Small pause between queries to avoid rate limiting
                if j < len(keywords) - 1:
                    await asyncio.sleep(2)

            best = max(scored, key=lambda x: x.score)
            results.append(
                TrendResult(
                    pain_point=pp,
                    keywords=scored,
                    best_keyword=best.keyword,
                    best_score=best.score,
                )
            )

        # Add skipped pain points with score 0
        for pp in pain_points[max_queries:]:
            results.append(
                TrendResult(
                    pain_point=pp,
                    keywords=[KeywordScore(pp.name.lower(), 0, "unknown")],
                    best_keyword=pp.name.lower(),
                    best_score=0,
                )
            )

        # Sort by opportunity: Tier 1 first, then Tier 2, etc.
        # Within same tier, lower ad count = more underserved = better
        results.sort(key=lambda x: (x.tier, x.best_score))

        # Select top N — prioritize Tier 1, then Tier 2
        top = results[: self.top_n]

        return ValidationResult(all_results=results, top_results=top)

    def _generate_keywords(
        self, pain_points: list[PainPoint]
    ) -> dict[str, list[str]]:
        """Use Claude to generate 2-3 BROAD keyword variants per pain point.

        These should be the words that appear in ad copy, headlines, and
        landing pages of ANY brand targeting this pain point — not niche
        supplement keywords.
        """
        pp_names = [pp.name for pp in pain_points]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "For each health pain point below, generate 2-3 BROAD keyword "
                        "variants that advertisers would use in Facebook/Meta ads targeting "
                        "this problem.\n\n"
                        "RULES:\n"
                        "- Use BROAD, common keywords — not niche supplement terms\n"
                        "- Think about what appears in ad copy, headlines, and landing "
                        "pages of ANY brand (supplements, devices, services) targeting "
                        "this pain point\n"
                        "- We want the TOTAL market picture, not filtered to supplements\n"
                        "- Keep keywords short (1-3 words)\n\n"
                        "EXAMPLES:\n"
                        "- High blood pressure → [\"high blood pressure\", \"blood pressure\", \"hypertension\"]\n"
                        "- Joint pain → [\"joint pain\", \"knee pain\", \"joint health\"]\n"
                        "- Gut health → [\"gut health\", \"bloating\", \"digestive health\"]\n\n"
                        f"Pain points: {json.dumps(pp_names)}\n\n"
                        "Return ONLY valid JSON:\n"
                        "```json\n"
                        "{\n"
                        '  "pain_point_name": ["keyword1", "keyword2", "keyword3"]\n'
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
            result[pp.name] = [name_lower, f"{name_lower} health"]
        return result
