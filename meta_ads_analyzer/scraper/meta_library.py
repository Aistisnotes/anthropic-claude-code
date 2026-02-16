"""Meta Ads Library scraper using Playwright.

Scrapes ads from https://www.facebook.com/ads/library/ using browser automation.
Uses structural DOM patterns (not brittle class names) to find ad cards.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import Browser, Page, async_playwright

from meta_ads_analyzer.models import AdType, ScrapedAd
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

ADS_LIBRARY_URL = "https://www.facebook.com/ads/library/"


class MetaAdsScraper:
    """Scrape ads from Meta Ads Library."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.scraper_cfg = config.get("scraper", {})
        self.max_ads = self.scraper_cfg.get("max_ads", 100)
        self.headless = self.scraper_cfg.get("headless", True)
        self.scroll_pause = self.scraper_cfg.get("scroll_pause", 2.0)
        self.max_scroll_attempts = self.scraper_cfg.get("max_scroll_attempts", 50)
        self.filters = self.scraper_cfg.get("filters", {})
        self.debug_dir: Path | None = None
        self._browser: Browser | None = None

    async def scrape(self, query: str) -> list[ScrapedAd]:
        """Scrape ads matching the query from Meta Ads Library."""
        logger.info(f"Starting scrape for query: {query} (max {self.max_ads} ads)")

        async with async_playwright() as p:
            self._browser = await p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                ads = await self._scrape_ads(page, query)
                logger.info(f"Scraped {len(ads)} ads for query: {query}")
                return ads
            finally:
                await context.close()
                await self._browser.close()

    async def _scrape_ads(self, page: Page, query: str) -> list[ScrapedAd]:
        """Navigate to ads library, apply filters, and extract ad cards."""
        url = self._build_search_url(query)
        logger.info(f"Navigating to: {url}")

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        # Handle cookie consent / login dialogs
        await self._dismiss_dialogs(page)
        await asyncio.sleep(1)

        # Take debug screenshot of initial page state
        await self._debug_screenshot(page, "01_initial_load")

        # Discover ad container selector dynamically
        container_selector = await self._discover_ad_selector(page)
        if not container_selector:
            logger.error("Could not find ad containers on page. Meta may have changed layout.")
            await self._debug_screenshot(page, "ERROR_no_ads_found")
            return []

        logger.info(f"Using ad container selector: {container_selector}")

        # Scroll and collect ads
        ads: list[ScrapedAd] = []
        seen_ids: set[str] = set()
        scroll_attempts = 0
        stale_rounds = 0

        while len(ads) < self.max_ads and scroll_attempts < self.max_scroll_attempts:
            new_ads = await self._extract_ad_cards(page, container_selector)

            added_this_round = 0
            for ad in new_ads:
                if ad.ad_id not in seen_ids:
                    seen_ids.add(ad.ad_id)
                    ads.append(ad)
                    added_this_round += 1
                    if len(ads) >= self.max_ads:
                        break

            if len(ads) >= self.max_ads:
                break

            # Scroll down
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(self.scroll_pause)
            scroll_attempts += 1

            # Check for new content after scroll
            post_scroll_ads = await self._extract_ad_cards(page, container_selector)
            new_count = sum(1 for a in post_scroll_ads if a.ad_id not in seen_ids)

            if new_count == 0:
                # Try multiple "see more" / "load more" button patterns
                clicked = await self._try_load_more(page)
                if clicked:
                    await asyncio.sleep(self.scroll_pause + 1)
                    stale_rounds = 0
                else:
                    stale_rounds += 1
                    if stale_rounds >= 3:
                        logger.info(
                            f"No more ads after {scroll_attempts} scrolls. "
                            f"Got {len(ads)} ads."
                        )
                        break
                    # Sometimes content takes extra time - do a longer wait
                    await asyncio.sleep(2)
            else:
                stale_rounds = 0

            if scroll_attempts % 5 == 0:
                logger.info(
                    f"Scroll {scroll_attempts}: {len(ads)} ads collected "
                    f"(+{added_this_round} this round)"
                )

        await self._debug_screenshot(page, "final_state")
        return ads[: self.max_ads]

    def _build_search_url(self, query: str) -> str:
        """Build Meta Ads Library search URL with filters."""
        country = self.filters.get("country", "US")
        ad_type = self.filters.get("ad_type", "all")
        status = self.filters.get("status", "active")
        media_type = self.filters.get("media_type", "all")

        encoded_query = quote_plus(query)

        base = f"https://www.facebook.com/ads/library/?active_status={status}"
        base += f"&ad_type={ad_type}"
        base += f"&country={country}"
        base += f"&q={encoded_query}"

        if media_type != "all":
            base += f"&media_type={media_type}"

        return base

    async def _dismiss_dialogs(self, page: Page) -> None:
        """Dismiss cookie consent and other dialog popups."""
        try:
            for selector in [
                'button[data-cookiebanner="accept_button"]',
                'button:has-text("Allow all cookies")',
                'button:has-text("Accept All")',
                'button:has-text("Allow essential and optional cookies")',
                'button:has-text("Only allow essential cookies")',
                'button:has-text("Decline optional cookies")',
                '[aria-label="Close"]',
                '[aria-label="Dismiss"]',
            ]:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.first.click()
                    await asyncio.sleep(1)
                    logger.info(f"Dismissed dialog: {selector}")
                    break
        except Exception:
            pass

    async def _discover_ad_selector(self, page: Page) -> str | None:
        """Dynamically discover the CSS selector for ad card containers.

        Instead of relying on brittle auto-generated class names, this probes
        the DOM structure to find the repeating ad card pattern.
        """
        # Strategy: the Meta Ads Library renders a list of ad "cards". We find
        # them by looking for structural patterns, not class names.
        selector = await page.evaluate(
            r"""
            () => {
                // Strategy 1: look for divs containing ad library links with numeric IDs
                // Each ad card may have a link like /ads/library/?id=XXXX or /ads/library/XXXX
                // Filter out navigation links (logo, report, API) that also match /ads/library/
                const adLinks = [...document.querySelectorAll('a[href*="/ads/library/"]')].filter(a => {
                    const href = a.href || a.getAttribute('href') || '';
                    return /(?:id=|library\/)\d{10,}/.test(href);
                });
                console.log('[meta_ads] Strategy 1: ' + adLinks.length + ' ad links with numeric IDs');
                if (adLinks.length > 0) {
                    // Walk up from the link to find the common card container.
                    // The card container is typically 2-4 levels up from the link.
                    // We find the level where sibling containers also have ad links.
                    let el = adLinks[0];
                    for (let depth = 0; depth < 8; depth++) {
                        el = el.parentElement;
                        if (!el) break;

                        // Check if this element's siblings also contain ad links
                        const parent = el.parentElement;
                        if (!parent) continue;

                        const siblings = parent.children;
                        let siblingsWithAds = 0;
                        for (const sib of siblings) {
                            const sibLink = sib.querySelector('a[href*="/ads/library/"]');
                            if (sibLink) {
                                const href = sibLink.href || sibLink.getAttribute('href') || '';
                                if (/(?:id=|library\/)\d{10,}/.test(href)) {
                                    siblingsWithAds++;
                                }
                            }
                        }

                        // If 2+ siblings have ad links, this is the card level
                        if (siblingsWithAds >= 2 || (siblingsWithAds >= 1 && adLinks.length === 1)) {
                            // Build a selector for this container type
                            const tag = el.tagName.toLowerCase();
                            const role = el.getAttribute('role');
                            if (role) {
                                return `${tag}[role="${role}"]`;
                            }
                            // Use the parent as context + child position pattern
                            const parentRole = parent.getAttribute('role');
                            if (parentRole) {
                                return `${parent.tagName.toLowerCase()}[role="${parentRole}"] > ${tag}`;
                            }
                            // Fallback: use a class if it looks stable (no random chars)
                            const cls = el.className;
                            if (cls && typeof cls === 'string') {
                                // Use the first class that looks non-obfuscated (>4 chars, no digits)
                                const classes = cls.split(/\s+/);
                                for (const c of classes) {
                                    if (c.length > 4 && !/\d/.test(c) && /^[a-zA-Z_-]+$/.test(c)) {
                                        return `.${c}`;
                                    }
                                }
                            }
                            // Could not build CSS selector — fall through to Strategy 2/3
                            // instead of returning a fragile walk-up marker
                            console.log('[meta_ads] Strategy 1: found card level at depth ' + depth + ' but no usable CSS selector, falling through');
                        }
                    }
                }

                // Strategy 2: look for role="article" (sometimes used for ad cards)
                const articles = document.querySelectorAll('[role="article"]');
                if (articles.length > 0) {
                    return '[role="article"]';
                }

                // Strategy 3: look for the search results container and its children
                // The ad library typically has a results section with repeated card divs
                const resultsDivs = document.querySelectorAll('div[class]');
                let bestCandidate = null;
                let bestCount = 0;

                for (const div of resultsDivs) {
                    const children = div.children;
                    if (children.length < 2) continue;

                    // Count children that look like ad cards (contain text + media)
                    let cardLike = 0;
                    for (const child of children) {
                        const hasText = child.textContent.length > 50;
                        const hasMedia = child.querySelector('video, img');
                        const hasLink = child.querySelector('a[href]');
                        if (hasText && (hasMedia || hasLink)) {
                            cardLike++;
                        }
                    }

                    if (cardLike > bestCount && cardLike >= 2) {
                        bestCount = cardLike;
                        // Return a way to identify these children
                        const role = div.getAttribute('role');
                        if (role) {
                            bestCandidate = `[role="${role}"] > div`;
                        } else {
                            bestCandidate = `STRUCTURAL:${cardLike}`;
                        }
                    }
                }

                if (bestCandidate) {
                    console.log('[meta_ads] Strategy 3: found ' + bestCount + ' card-like children');
                    return bestCandidate;
                }

                // Strategy 4 (last resort): if we found any ad-like links earlier,
                // use walk-up extraction as the final fallback
                if (adLinks.length > 0) {
                    console.log('[meta_ads] Strategy 4: falling back to AD_LINK_WALK with ' + adLinks.length + ' links');
                    return 'AD_LINK_WALK';
                }

                return null;
            }
            """
        )

        if not selector:
            return None

        if selector == "AD_LINK_WALK":
            logger.debug("Selector discovery returning __AD_LINK_WALK__ (last-resort fallback)")
            return "__AD_LINK_WALK__"

        if selector.startswith("STRUCTURAL:"):
            # Found cards structurally but can't make a CSS selector - use JS extraction
            logger.debug(
                f"Selector discovery returning __STRUCTURAL__ (found {selector.split(':')[1]} card-like children)"
            )
            return "__STRUCTURAL__"

        return selector

    async def _extract_ad_cards(
        self, page: Page, container_selector: str
    ) -> list[ScrapedAd]:
        """Extract ad data from all visible ad card elements."""
        raw_ads = await page.evaluate(
            r"""
            (selector) => {
                const ads = [];

                // Helper: find ad containers based on selector type
                let containers;
                if (selector === '__STRUCTURAL__') {
                    // Re-run Strategy 3 heuristic: find parent div with most
                    // card-like children (text>50 + media/link). No dependency
                    // on ad library links.
                    const resultsDivs = document.querySelectorAll('div[class]');
                    let bestParent = null;
                    let bestCount = 0;
                    for (const div of resultsDivs) {
                        const children = div.children;
                        if (children.length < 2) continue;
                        let cardLike = 0;
                        for (const child of children) {
                            const hasText = child.textContent.length > 50;
                            const hasMedia = child.querySelector('video, img');
                            const hasLink = child.querySelector('a[href]');
                            if (hasText && (hasMedia || hasLink)) {
                                cardLike++;
                            }
                        }
                        if (cardLike > bestCount && cardLike >= 2) {
                            bestCount = cardLike;
                            bestParent = div;
                        }
                    }
                    containers = [];
                    if (bestParent) {
                        for (const child of bestParent.children) {
                            const hasText = child.textContent.length > 50;
                            const hasMedia = child.querySelector('video, img');
                            const hasLink = child.querySelector('a[href]');
                            if (hasText && (hasMedia || hasLink)) {
                                containers.push(child);
                            }
                        }
                    }
                    console.log('[meta_ads] __STRUCTURAL__ extraction: bestCount=' + bestCount + ', containers=' + containers.length);
                } else if (selector === '__AD_LINK_WALK__') {
                    // Fallback: find all ad links and walk up to card boundary
                    const adLinks = document.querySelectorAll(
                        'a[href*="/ads/library/"]'
                    );
                    const seen = new Set();
                    containers = [];
                    for (const link of adLinks) {
                        // Walk up to find card-level container (stop at ~6 levels)
                        let el = link;
                        for (let i = 0; i < 6; i++) {
                            if (!el.parentElement) break;
                            el = el.parentElement;
                            // Heuristic: card containers are typically >200px tall
                            // and contain both text and media
                            const rect = el.getBoundingClientRect();
                            if (rect.height > 200 && rect.width > 300) {
                                const hasMedia = el.querySelector('video, img');
                                if (hasMedia) {
                                    const key = String(rect.top) + ':' + String(rect.left);
                                    if (!seen.has(key)) {
                                        seen.add(key);
                                        containers.push(el);
                                    }
                                    break;
                                }
                            }
                        }
                    }
                    console.log('[meta_ads] __AD_LINK_WALK__ extraction: adLinks=' + adLinks.length + ', containers=' + containers.length);
                } else {
                    containers = document.querySelectorAll(selector);
                }

                for (const container of containers) {
                    try {
                        const ad = {};

                        // ── Extract ad ID ──
                        // Look in all links for the ad library ID pattern
                        const allLinks = container.querySelectorAll('a[href]');
                        for (const link of allLinks) {
                            const href = link.href || link.getAttribute('href') || '';
                            // Match both /ads/library/?id=XXX and /ads/library/XXX
                            const match = href.match(/(?:id=|library\/)(\d{10,})/);
                            if (match) {
                                ad.ad_id = match[1];
                                break;
                            }
                        }

                        // ── Page name ──
                        // Usually the first prominent link text that isn't "Ad Library"
                        const candidateLinks = container.querySelectorAll('a[href*="facebook.com"]');
                        for (const link of candidateLinks) {
                            const href = link.href || link.getAttribute('href') || '';
                            if (href.includes('/ads/library')) continue;
                            const text = (link.textContent || '').trim();
                            if (text && text.length > 1 && text.length < 100) {
                                ad.page_name = text;
                                break;
                            }
                        }

                        // ── Primary text / ad body ──
                        // Get the longest text block in the container that looks like ad copy
                        const allDivs = container.querySelectorAll('div, span, p');
                        let longestText = '';
                        for (const el of allDivs) {
                            // Skip elements that are just containers
                            if (el.children.length > 5) continue;
                            const text = (el.textContent || '').trim();
                            // Look for ad copy (longer text that isn't just a label)
                            if (text.length > longestText.length && text.length > 20) {
                                // Verify this isn't a parent of the whole card
                                if (el.offsetHeight && el.offsetHeight < 500) {
                                    longestText = text;
                                }
                            }
                        }
                        // Also try finding divs with style="white-space: pre-wrap" or similar
                        const preWrap = container.querySelector(
                            'div[style*="white-space"], div[style*="-webkit-line-clamp"]'
                        );
                        if (preWrap) {
                            const text = preWrap.textContent.trim();
                            if (text.length > (longestText.length * 0.5)) {
                                longestText = text;
                            }
                        }
                        if (longestText) {
                            ad.primary_text = longestText;
                        }

                        // ── Media detection ──
                        const video = container.querySelector('video');
                        if (video) {
                            ad.ad_type = 'video';
                            ad.media_url = video.src
                                || (video.querySelector('source') || {}).src
                                || video.getAttribute('src');
                        } else {
                            // Look for the main ad image (skip tiny icons/avatars)
                            const images = container.querySelectorAll('img');
                            let bestImg = null;
                            let bestArea = 0;
                            for (const img of images) {
                                const w = img.naturalWidth || img.width || 0;
                                const h = img.naturalHeight || img.height || 0;
                                const area = w * h;
                                // Skip small images (icons, profile pics)
                                if (area > bestArea && (w > 100 || h > 100)) {
                                    bestArea = area;
                                    bestImg = img;
                                }
                            }
                            if (bestImg) {
                                ad.ad_type = 'static';
                                ad.media_url = bestImg.src;
                            }
                        }

                        // ── Headline ──
                        // Look for short bold/strong text that isn't the page name
                        const bolds = container.querySelectorAll(
                            'strong, b, [style*="font-weight: bold"], [style*="font-weight:bold"], [style*="font-weight: 700"]'
                        );
                        for (const b of bolds) {
                            const text = b.textContent.trim();
                            if (text && text.length > 3 && text.length < 150 && text !== ad.page_name) {
                                ad.headline = text;
                                break;
                            }
                        }

                        // ── CTA ──
                        const ctaButtons = container.querySelectorAll(
                            '[role="button"], a[href]:not([href*="facebook.com"])'
                        );
                        for (const btn of ctaButtons) {
                            const text = btn.textContent.trim();
                            if (text && text.length < 30 && /^(Shop|Learn|Sign|Get|Buy|Subscribe|Download|Watch|Apply|Book|Try|Start|Order|Claim|See)/i.test(text)) {
                                ad.cta_text = text;
                                break;
                            }
                        }

                        // ── Link URL ──
                        for (const link of allLinks) {
                            const href = link.href || link.getAttribute('href') || '';
                            if (href && !href.includes('facebook.com') && !href.includes('instagram.com') && href.startsWith('http')) {
                                ad.link_url = href;
                                break;
                            }
                        }

                        // ── Date started ──
                        const cardText = container.textContent || '';
                        const dateMatch = cardText.match(
                            /[Ss]tarted running on\s+(.+?)(?:\.|·|\n|$)/
                        );
                        if (dateMatch) {
                            ad.started_running = dateMatch[1].trim();
                        }

                        // ── Platforms ──
                        ad.platforms = [];
                        for (const platform of [
                            'Facebook', 'Instagram', 'Messenger', 'Audience Network'
                        ]) {
                            if (cardText.includes(platform)) {
                                ad.platforms.push(platform.toLowerCase());
                            }
                        }

                        // Only include if we got meaningful data
                        if (ad.ad_id || ad.primary_text || ad.media_url) {
                            ads.push(ad);
                        }
                    } catch (e) {
                        // Skip broken cards
                    }
                }
                return ads;
            }
            """,
            container_selector,
        )

        logger.debug(f"_extract_ad_cards: selector={container_selector}, raw_ads={len(raw_ads)}")
        if len(raw_ads) == 0:
            logger.warning(
                f"0 raw ads extracted with selector '{container_selector}'. "
                "Page may have changed layout or content may not have loaded."
            )

        ads = []
        for raw in raw_ads:
            ad_id = raw.get("ad_id") or self._generate_id(raw)
            ad_type_str = raw.get("ad_type", "unknown")

            try:
                ad_type = AdType(ad_type_str)
            except ValueError:
                ad_type = AdType.UNKNOWN

            ads.append(
                ScrapedAd(
                    ad_id=ad_id,
                    page_name=raw.get("page_name", "Unknown"),
                    ad_type=ad_type,
                    primary_text=raw.get("primary_text"),
                    headline=raw.get("headline"),
                    cta_text=raw.get("cta_text"),
                    link_url=raw.get("link_url"),
                    media_url=raw.get("media_url"),
                    started_running=raw.get("started_running"),
                    platforms=raw.get("platforms", []),
                )
            )

        return ads

    async def _try_load_more(self, page: Page) -> bool:
        """Try various patterns to load more results."""
        # Pattern 1: "See more" / "See more results" buttons
        for text in ["See more results", "See more", "Show more", "Load more"]:
            locator = page.locator(f'div[role="button"]:has-text("{text}")')
            if await locator.count() > 0:
                try:
                    await locator.first.click()
                    logger.info(f"Clicked '{text}' button")
                    return True
                except Exception:
                    pass

            # Also try <a> and <button> elements
            for tag in ["button", "a"]:
                locator = page.locator(f'{tag}:has-text("{text}")')
                if await locator.count() > 0:
                    try:
                        await locator.first.click()
                        logger.info(f"Clicked '{text}' ({tag}) button")
                        return True
                    except Exception:
                        pass

        # Pattern 2: aria-label based buttons
        for label in ["Load more", "See more", "Show more results"]:
            locator = page.locator(f'[aria-label*="{label}"]')
            if await locator.count() > 0:
                try:
                    await locator.first.click()
                    logger.info(f"Clicked aria-label '{label}' button")
                    return True
                except Exception:
                    pass

        return False

    async def _debug_screenshot(self, page: Page, name: str) -> None:
        """Save a debug screenshot if debug_dir is set."""
        if not self.debug_dir:
            return
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            path = self.debug_dir / f"{name}.png"
            await page.screenshot(path=str(path), full_page=True)
            logger.info(f"Debug screenshot: {path}")
        except Exception as e:
            logger.warning(f"Failed to save screenshot: {e}")

    @staticmethod
    def _generate_id(raw: dict) -> str:
        """Generate a deterministic ID from ad content when no ID is available."""
        content = f"{raw.get('page_name', '')}{raw.get('primary_text', '')[:200]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
