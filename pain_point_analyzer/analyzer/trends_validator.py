"""Step 3: Meta Ad Library Demand Validation.

For each pain point, generate broad keyword variants and query Meta Ad Library
for total active ad counts. Tier the pain points by market saturation and
select the top N opportunities (lowest saturation first).

Tiers:
  - Tier 1 OPEN: 1-5,000 active ads (green)
  - Tier 2 SOLID: 5,000-15,000 active ads (yellow)
  - Tier 3 SATURATED: 15,000-50,000 active ads (orange)
  - Tier 4 SUPER SATURATED: 50,000+ active ads (red)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import anthropic

from .pain_point_discovery import PainPoint

logger = logging.getLogger(__name__)

# ── Tier definitions ──────────────────────────────────────────────────────────
TIER_UNKNOWN = 0
TIER_OPEN = 1
TIER_SOLID = 2
TIER_SATURATED = 3
TIER_SUPER_SATURATED = 4

TIER_LABELS = {
    TIER_UNKNOWN: "UNKNOWN",
    TIER_OPEN: "OPEN",
    TIER_SOLID: "SOLID",
    TIER_SATURATED: "SATURATED",
    TIER_SUPER_SATURATED: "SUPER SATURATED",
}

TIER_COLORS = {
    TIER_UNKNOWN: "gray",
    TIER_OPEN: "green",
    TIER_SOLID: "yellow",
    TIER_SATURATED: "orange",
    TIER_SUPER_SATURATED: "red",
}

SCRAPER_ERROR = -2  # Sentinel: scraper returned 0, likely a failure


# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent.parent / "output"
CACHE_FILE = CACHE_DIR / "keyword_cache.json"
CACHE_TTL_DAYS = 14


def _load_cache() -> dict:
    """Load the keyword cache from disk."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict) -> None:
    """Save the keyword cache to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, indent=2, default=str), encoding="utf-8"
    )


def _get_cached(pain_point_name: str) -> dict | None:
    """Return cached data for a pain point if valid (within TTL)."""
    cache = _load_cache()
    key = pain_point_name.lower().strip()
    if key not in cache:
        return None
    entry = cache[key]
    try:
        last_checked = datetime.fromisoformat(entry["last_checked"])
        if datetime.utcnow() - last_checked < timedelta(days=CACHE_TTL_DAYS):
            return entry
    except (KeyError, ValueError):
        pass
    return None


def _set_cached(pain_point_name: str, ad_count: int, keywords_checked: list[str]) -> None:
    """Save a pain point result to cache."""
    cache = _load_cache()
    key = pain_point_name.lower().strip()
    now = datetime.utcnow()
    cache[key] = {
        "ad_count": ad_count,
        "keywords_checked": keywords_checked,
        "last_checked": now.isoformat(),
        "expires": (now + timedelta(days=CACHE_TTL_DAYS)).isoformat(),
    }
    _save_cache(cache)


def clear_cache() -> None:
    """Clear the entire keyword cache."""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()


def _classify_tier(ad_count: int) -> int:
    """Classify an ad count into a market tier.

    Tiers:
      Tier 1 OPEN: 1-5,000 active ads
      Tier 2 SOLID: 5,000-15,000 active ads
      Tier 3 SATURATED: 15,000-50,000 active ads
      Tier 4 SUPER SATURATED: 50,000+ active ads

    CRITICAL: 0 or negative ad count means the scraper failed, NOT that
    there's no competition.  We must never classify 0 as a real tier.
    """
    if ad_count <= 0:
        return TIER_UNKNOWN
    if ad_count <= 5000:
        return TIER_OPEN
    elif ad_count <= 15000:
        return TIER_SOLID
    elif ad_count < 50000:
        return TIER_SATURATED
    else:
        # Meta caps at 50k — treat 50,000 or "50,000+" as SUPER SATURATED
        return TIER_SUPER_SATURATED


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
    tier: int = TIER_OPEN
    tier_label: str = ""
    tier_color: str = "green"
    from_cache: bool = False
    cache_date: str = ""
    skipped: bool = False
    skip_reason: str = ""

    def __post_init__(self):
        self.tier = _classify_tier(self.best_score)
        self.tier_label = TIER_LABELS[self.tier]
        self.tier_color = TIER_COLORS[self.tier]


@dataclass
class ValidationResult:
    all_results: list[TrendResult]  # all pain points with scores
    top_results: list[TrendResult]  # top N by opportunity (lower ads = better)
    meta_reachable: bool = True  # whether Meta Ad Library was reachable


# ── Ad count scraper ──────────────────────────────────────────────────────────
async def _get_ad_count(keyword: str, headless: bool = True) -> int:
    """Search Meta Ad Library for a keyword and return the total ad count.

    Uses multiple strategies:
    1. Extract from embedded JSON data in script tags (most reliable)
    2. Parse the visible "X results" / "X ads" text from the page
    3. Count visible ad card links as a minimum floor
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
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
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
                await page.goto(url, wait_until="networkidle", timeout=45000)
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
                    try:
                        btn = page.locator(selector)
                        if await btn.count() > 0:
                            await btn.first.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        pass

                # Wait for actual ad content to load
                for wait_selector in [
                    'div[role="article"]',
                    'a[href*="/ads/library/"]',
                    'text=/\\d+.*results/',
                    'text=/\\d+.*ads/',
                ]:
                    try:
                        await page.wait_for_selector(
                            wait_selector, timeout=8000
                        )
                        logger.debug(
                            f"Found content indicator: {wait_selector}"
                        )
                        break
                    except Exception:
                        continue

                await asyncio.sleep(5)

                # Debug: log page title and snippet
                page_title = await page.title()
                body_snippet = await page.evaluate(
                    "(document.body.innerText || '').substring(0, 300)"
                )
                logger.debug(
                    f"Page title: {page_title} | "
                    f"Body snippet: {body_snippet[:150]}"
                )

                # Strategy 1: Extract total_count from embedded JSON in script tags
                ad_count = await page.evaluate(
                    r"""
                    () => {
                        let bestCount = 0;

                        const scripts = document.querySelectorAll(
                            'script[type="application/json"], script[data-sjs]'
                        );
                        for (const script of scripts) {
                            const text = script.textContent || '';
                            const countPatterns = [
                                /"total_count"\s*:\s*(\d+)/g,
                                /"count"\s*:\s*(\d+)/g,
                                /"numResults"\s*:\s*(\d+)/g,
                                /"collated_total"\s*:\s*(\d+)/g,
                            ];
                            for (const pattern of countPatterns) {
                                let m;
                                while ((m = pattern.exec(text)) !== null) {
                                    const num = parseInt(m[1], 10);
                                    if (num > bestCount) {
                                        bestCount = num;
                                    }
                                }
                            }
                        }

                        if (bestCount > 0) return bestCount;

                        // Strategy 2: ALL script tags fallback
                        const allScripts = document.querySelectorAll('script');
                        for (const script of allScripts) {
                            const text = script.textContent || '';
                            if (text.length < 100) continue;
                            const m = text.match(/"total_count"\s*:\s*(\d+)/);
                            if (m) {
                                const num = parseInt(m[1], 10);
                                if (num > bestCount) bestCount = num;
                            }
                        }

                        if (bestCount > 0) return bestCount;

                        // Strategy 3: Parse visible page text
                        const body = document.body;
                        if (body) {
                            const bodyText = body.innerText || body.textContent || '';

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
                                    if (!isNaN(num) && num > bestCount) {
                                        bestCount = num;
                                    }
                                }
                            }
                        }

                        if (bestCount > 0) return bestCount;

                        // Strategy 4: Count unique ad card IDs as minimum floor
                        const adLinks = document.querySelectorAll(
                            'a[href*="/ads/library/"]'
                        );
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

                # If we got 0, log diagnostic info
                if ad_count == 0:
                    diag = await page.evaluate(
                        """() => {
                            const scripts = document.querySelectorAll('script');
                            const jsonScripts = document.querySelectorAll(
                                'script[type="application/json"], script[data-sjs]'
                            );
                            const html = document.documentElement.outerHTML || '';
                            return {
                                scriptCount: scripts.length,
                                jsonScriptCount: jsonScripts.length,
                                htmlLength: html.length,
                                hasLoginWall: !!(
                                    document.querySelector('#login_form') ||
                                    document.querySelector('[data-testid="royal_login_form"]') ||
                                    (document.body.innerText || '').includes('Log in')
                                ),
                                url: window.location.href,
                            };
                        }"""
                    )
                    logger.warning(
                        f"Meta Ad Library returned 0 for '{keyword}' — "
                        f"diagnostics: {diag}"
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
        scraper_cfg = config.get("scraper", {})
        self.delay_between_requests = scraper_cfg.get("delay_between_requests", 8)
        self.cooldown_between_brands = scraper_cfg.get("cooldown_between_brands", 30)
        self.max_requests_per_session = scraper_cfg.get("max_requests_per_session", 20)
        self._session_request_count = 0
        self.client = anthropic.Anthropic()

    async def _check_facebook_reachable(self) -> bool:
        """Quick check if facebook.com is reachable (not blocked by proxy).

        Uses a test keyword 'supplement' as a pre-flight check.
        """
        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                page = await browser.new_page()
                resp = await page.goto(
                    "https://www.facebook.com/ads/library/"
                    "?active_status=active&ad_type=all&country=US"
                    "&q=supplement",
                    wait_until="commit",
                    timeout=15000,
                )
                status = resp.status if resp else 0
                html_len = len(await page.content())
                await browser.close()
                if status == 407 or html_len == 0:
                    return False
                if status == 403:
                    logger.warning(
                        "Meta Ad Library returned 403 — possible IP ban"
                    )
                    return False
                return True
        except Exception as e:
            logger.warning(f"Meta Ad Library pre-flight check failed: {e}")
            return False

    async def validate(
        self,
        pain_points: list[PainPoint],
        progress_cb=None,
        max_to_search: int = 20,
        include_single_ingredient: bool = False,
    ) -> ValidationResult:
        """Query Meta Ad Library for pain points, rank by opportunity.

        Args:
            pain_points: All discovered pain points
            progress_cb: Progress callback
            max_to_search: Maximum pain points to search on Meta Ad Library
            include_single_ingredient: Whether to include single-ingredient pain points
        """

        # ── Smart prioritization (Change 6) ──────────────────────────────
        # Determine which pain points to actually search
        total_ingredients = set()
        for pp in pain_points:
            total_ingredients.update(pp.supporting_ingredients)
        num_ingredients = len(total_ingredients)

        multi_ingredient = [pp for pp in pain_points if pp.ingredient_count >= 2]
        single_ingredient = [pp for pp in pain_points if pp.ingredient_count < 2]

        # Sort each group by ingredient count desc, then alphabetical
        multi_ingredient.sort(key=lambda pp: (-pp.ingredient_count, pp.name))
        single_ingredient.sort(key=lambda pp: (-pp.ingredient_count, pp.name))

        if num_ingredients >= 10:
            # Only search 2+ ingredient pain points
            search_points = multi_ingredient[:max_to_search]
            skipped_points = single_ingredient
            skip_reason = "Not validated — single ingredient support only"
        elif num_ingredients >= 4:
            # Prioritize 2+ ingredient, fill up to 10 minimum with single
            search_points = multi_ingredient[:max_to_search]
            if len(search_points) < 10:
                remaining = 10 - len(search_points)
                search_points += single_ingredient[:remaining]
                skipped_points = single_ingredient[remaining:]
            else:
                skipped_points = single_ingredient
            search_points = search_points[:max_to_search]
            skip_reason = "Not validated — single ingredient support only"
        else:
            # 1-3 ingredients: search all
            search_points = (multi_ingredient + single_ingredient)[:max_to_search]
            skipped_points = []
            skip_reason = ""

        # If user opted in to single-ingredient, include all
        if include_single_ingredient:
            search_points = (multi_ingredient + single_ingredient)[:max_to_search]
            skipped_points = (multi_ingredient + single_ingredient)[max_to_search:]
            skip_reason = "Not validated — search cap reached"

        skipped_count = len(skipped_points)
        searched_count = len(search_points)

        if progress_cb:
            if skipped_count > 0:
                progress_cb(
                    f"Found {len(pain_points)} pain points. "
                    f"Searching {searched_count} with multi-ingredient support "
                    f"({skipped_count} single-ingredient skipped)"
                )
            else:
                progress_cb(
                    f"Found {len(pain_points)} pain points. "
                    f"Searching {searched_count}..."
                )

        # ── Check cache first ─────────────────────────────────────────────
        to_search_fresh: list[PainPoint] = []
        cached_results: list[TrendResult] = []

        for pp in search_points:
            cached = _get_cached(pp.name)
            if cached:
                ad_count = cached["ad_count"]
                days_ago = (
                    datetime.utcnow() - datetime.fromisoformat(cached["last_checked"])
                ).days
                cache_date = datetime.fromisoformat(
                    cached["last_checked"]
                ).strftime("%b %d")
                if progress_cb:
                    progress_cb(
                        f"Using cached data for '{pp.name}' "
                        f"(checked {days_ago} days ago, {ad_count:,} ads)"
                    )
                cached_results.append(
                    TrendResult(
                        pain_point=pp,
                        keywords=[
                            KeywordScore(kw, ad_count, "cached")
                            for kw in cached.get("keywords_checked", [pp.name.lower()])
                        ],
                        best_keyword=cached.get("keywords_checked", [pp.name.lower()])[0],
                        best_score=ad_count,
                        from_cache=True,
                        cache_date=cache_date,
                    )
                )
            else:
                to_search_fresh.append(pp)

        # ── Pre-flight: check if Facebook is reachable ────────────────────
        meta_reachable = True
        if to_search_fresh:
            if progress_cb:
                progress_cb("Checking Meta Ad Library connectivity...")
            meta_reachable = await self._check_facebook_reachable()
            if not meta_reachable:
                logger.warning(
                    "Meta Ad Library unreachable (proxy/network block) — "
                    "skipping demand validation."
                )
                if progress_cb:
                    progress_cb(
                        "⚠️ Meta Ad Library is unreachable from this network. "
                        "Ad count validation will be skipped. "
                        "Try from a different network or wait and retry."
                    )

        # ── Query Meta Ad Library for fresh pain points ───────────────────
        fresh_results: list[TrendResult] = []

        if meta_reachable and to_search_fresh:
            # Generate broad keyword variants
            if progress_cb:
                progress_cb("Generating broad search keywords...")
            keyword_map = self._generate_keywords(to_search_fresh)

            for i, pp in enumerate(to_search_fresh):
                # Session request cap
                if self._session_request_count >= self.max_requests_per_session:
                    logger.warning(
                        f"Hit session request cap ({self.max_requests_per_session}). "
                        f"Skipping remaining pain points to avoid IP ban."
                    )
                    if progress_cb:
                        progress_cb(
                            f"Request cap reached ({self.max_requests_per_session}) — "
                            f"skipping remaining queries"
                        )
                    for remaining_pp in to_search_fresh[i:]:
                        fresh_results.append(
                            TrendResult(
                                pain_point=remaining_pp,
                                keywords=[KeywordScore(remaining_pp.name.lower(), -1, "capped")],
                                best_keyword=remaining_pp.name.lower(),
                                best_score=-1,
                                tier=TIER_UNKNOWN,
                                tier_label=TIER_LABELS[TIER_UNKNOWN],
                                tier_color=TIER_COLORS[TIER_UNKNOWN],
                            )
                        )
                    break

                # 15-second delay + random 5-15s jitter between pain points
                if i > 0:
                    cooldown = 15 + random.uniform(5, 15)
                    logger.info(
                        f"Rate limit: {cooldown:.0f}s cooldown before pain point "
                        f"'{pp.name}' ({i+1}/{len(to_search_fresh)})"
                    )
                    if progress_cb:
                        progress_cb(
                            f"Rate limit cooldown ({cooldown:.0f}s) before "
                            f"'{pp.name}' ({i+1}/{len(to_search_fresh)})..."
                        )
                    await asyncio.sleep(cooldown)

                if progress_cb:
                    progress_cb(
                        f"Checking Meta Ad Library for '{pp.name}' "
                        f"({i+1}/{len(to_search_fresh)})..."
                    )

                keywords = keyword_map.get(pp.name, [])
                if not keywords:
                    keywords = [pp.name.lower()]

                scored: list[KeywordScore] = []
                for j, kw in enumerate(keywords):
                    if self._session_request_count >= self.max_requests_per_session:
                        break

                    variant_type = ["broad", "symptom", "clinical"][j] if j < 3 else "other"
                    count = await _get_ad_count(kw, headless=self.headless)
                    self._session_request_count += 1

                    # Retry once with 30s delay if count is 0
                    if count == 0:
                        logger.warning(
                            f"Got 0 ads for '{kw}' — retrying in 30s "
                            f"(broad keywords should never be 0)"
                        )
                        await asyncio.sleep(30)
                        count = await _get_ad_count(kw, headless=self.headless)
                        self._session_request_count += 1
                        if count == 0:
                            logger.warning(
                                f"Still 0 ads for '{kw}' after retry — "
                                f"marking as could not retrieve"
                            )
                            count = SCRAPER_ERROR

                    scored.append(KeywordScore(kw, count, variant_type))

                    # 15s delay + 5-15s jitter between keyword requests
                    if j < len(keywords) - 1:
                        delay = 15 + random.uniform(5, 15)
                        logger.info(f"Rate limit: {delay:.1f}s delay before next keyword")
                        await asyncio.sleep(delay)

                # Check if ALL keywords returned errors
                all_failed = all(ks.score <= 0 for ks in scored) if scored else True
                best = max(scored, key=lambda x: x.score) if scored else KeywordScore(pp.name.lower(), SCRAPER_ERROR, "unknown")

                if all_failed:
                    logger.warning(
                        f"ALL keyword variants for '{pp.name}' returned 0/error — "
                        f"Meta Ad Library may be unreachable for these keywords"
                    )
                    best_score = SCRAPER_ERROR
                else:
                    best_score = best.score
                    # Cache successful results
                    keywords_checked = [ks.keyword for ks in scored]
                    _set_cached(pp.name, best_score, keywords_checked)

                fresh_results.append(
                    TrendResult(
                        pain_point=pp,
                        keywords=scored,
                        best_keyword=best.keyword,
                        best_score=best_score,
                    )
                )
        elif not meta_reachable:
            # Meta unreachable — mark all fresh pain points
            for pp in to_search_fresh:
                fresh_results.append(
                    TrendResult(
                        pain_point=pp,
                        keywords=[KeywordScore(pp.name.lower(), -1, "unreachable")],
                        best_keyword=pp.name.lower(),
                        best_score=-1,
                        tier=TIER_UNKNOWN,
                        tier_label="Unavailable",
                        tier_color="gray",
                    )
                )

        # ── Combine cached + fresh results ────────────────────────────────
        results = cached_results + fresh_results

        # Add skipped pain points
        for pp in skipped_points:
            # Check cache for skipped ones too
            cached = _get_cached(pp.name)
            if cached:
                ad_count = cached["ad_count"]
                cache_date = datetime.fromisoformat(
                    cached["last_checked"]
                ).strftime("%b %d")
                results.append(
                    TrendResult(
                        pain_point=pp,
                        keywords=[KeywordScore(pp.name.lower(), ad_count, "cached")],
                        best_keyword=pp.name.lower(),
                        best_score=ad_count,
                        from_cache=True,
                        cache_date=cache_date,
                        skipped=True,
                        skip_reason=skip_reason,
                    )
                )
            else:
                results.append(
                    TrendResult(
                        pain_point=pp,
                        keywords=[KeywordScore(pp.name.lower(), 0, "skipped")],
                        best_keyword=pp.name.lower(),
                        best_score=0,
                        skipped=True,
                        skip_reason=skip_reason,
                    )
                )

        # Sort by opportunity: Tier 1 first, then Tier 2, etc.
        # Within same tier, lower ad count = more underserved = better
        results.sort(key=lambda x: (x.tier, x.best_score))

        # Select top N — prioritize Tier 1, then Tier 2
        # Never classify as a tier based on failed data
        eligible_top = [
            r for r in results
            if r.best_score > 0 and not r.skipped
        ]
        top = eligible_top[: self.top_n]

        # If we don't have enough eligible, fill from remaining non-skipped
        if len(top) < self.top_n:
            remaining = [r for r in results if r not in top and not r.skipped]
            top += remaining[: self.top_n - len(top)]

        return ValidationResult(
            all_results=results,
            top_results=top,
            meta_reachable=meta_reachable,
        )

    def _generate_keywords(
        self, pain_points: list[PainPoint]
    ) -> dict[str, list[str]]:
        """Use Claude to generate 2-3 BROAD keyword variants per pain point."""
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
