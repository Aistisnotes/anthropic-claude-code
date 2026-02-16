"""Meta Ads Library scraper using Playwright.

Scrapes ads from https://www.facebook.com/ads/library/ using browser automation.
Supports searching by keyword or page URL, with configurable filters.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

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
        self._browser: Browser | None = None

    async def scrape(self, query: str) -> list[ScrapedAd]:
        """Scrape ads matching the query from Meta Ads Library.

        Args:
            query: Search keyword or advertiser page URL/name.

        Returns:
            List of scraped ads up to max_ads.
        """
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
        # Build the URL with search params
        url = self._build_search_url(query)
        logger.info(f"Navigating to: {url}")

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)  # Let JS render

        # Handle cookie consent if present
        await self._dismiss_dialogs(page)

        # Wait for ad cards to appear
        await self._wait_for_ads(page)

        # Scroll and collect ads
        ads: list[ScrapedAd] = []
        seen_ids: set[str] = set()
        scroll_attempts = 0

        while len(ads) < self.max_ads and scroll_attempts < self.max_scroll_attempts:
            # Extract visible ad cards
            new_ads = await self._extract_ad_cards(page)

            for ad in new_ads:
                if ad.ad_id not in seen_ids:
                    seen_ids.add(ad.ad_id)
                    ads.append(ad)
                    if len(ads) >= self.max_ads:
                        break

            if len(ads) >= self.max_ads:
                break

            # Scroll down to load more
            prev_count = len(ads)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(self.scroll_pause)
            scroll_attempts += 1

            # Check if we've loaded new content
            new_ads_after_scroll = await self._extract_ad_cards(page)
            new_count = sum(1 for a in new_ads_after_scroll if a.ad_id not in seen_ids)
            if new_count == 0:
                # Try clicking "See more" button if available
                see_more = page.locator(
                    'div[role="button"]:has-text("See more results")'
                )
                if await see_more.count() > 0:
                    await see_more.first.click()
                    await asyncio.sleep(self.scroll_pause)
                else:
                    logger.info(
                        f"No more ads to load after {scroll_attempts} scrolls. "
                        f"Got {len(ads)} ads."
                    )
                    break

            logger.info(
                f"Scroll {scroll_attempts}: {len(ads)} ads collected "
                f"(+{len(ads) - prev_count} new)"
            )

        return ads[: self.max_ads]

    def _build_search_url(self, query: str) -> str:
        """Build Meta Ads Library search URL with filters."""
        country = self.filters.get("country", "US")
        ad_type = self.filters.get("ad_type", "all")
        status = self.filters.get("status", "active")
        media_type = self.filters.get("media_type", "all")

        # Meta Ads Library URL structure
        base = f"https://www.facebook.com/ads/library/?active_status={status}"
        base += f"&ad_type={ad_type}"
        base += f"&country={country}"
        base += f"&q={query}"

        if media_type != "all":
            base += f"&media_type={media_type}"

        return base

    async def _dismiss_dialogs(self, page: Page) -> None:
        """Dismiss cookie consent and other dialog popups."""
        try:
            # Cookie consent buttons
            for selector in [
                'button[data-cookiebanner="accept_button"]',
                'button:has-text("Allow all cookies")',
                'button:has-text("Accept All")',
                'button:has-text("Allow essential and optional cookies")',
            ]:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.first.click()
                    await asyncio.sleep(1)
                    break
        except Exception:
            pass  # Dialog may not appear

    async def _wait_for_ads(self, page: Page) -> None:
        """Wait for ad card elements to appear on the page."""
        try:
            # The ads library renders ad cards in specific containers
            await page.wait_for_selector(
                'div[class*="xrvj5dj"], div[class*="_7jvw"], div[role="article"]',
                timeout=15000,
            )
        except Exception:
            logger.warning("Timeout waiting for ad cards. Page may be empty or blocked.")

    async def _extract_ad_cards(self, page: Page) -> list[ScrapedAd]:
        """Extract ad data from all visible ad card elements."""
        ads = []

        # Use JavaScript to extract ad card data from the DOM
        raw_ads = await page.evaluate(
            """
            () => {
                const ads = [];
                // Meta Ads Library renders ads in specific container divs
                // The structure varies but typically each ad is in a card-like container
                const adContainers = document.querySelectorAll(
                    'div[class*="xrvj5dj"], div[class*="_7jvw"], div[role="article"]'
                );

                for (const container of adContainers) {
                    try {
                        const ad = {};

                        // Extract ad ID from links or data attributes
                        const links = container.querySelectorAll('a[href*="ads/library"]');
                        for (const link of links) {
                            const match = link.href.match(/id=(\d+)/);
                            if (match) {
                                ad.ad_id = match[1];
                                break;
                            }
                        }

                        // Page name - usually in a bold/strong element or specific link
                        const pageLink = container.querySelector(
                            'a[href*="facebook.com/"] span, ' +
                            'a[href*="facebook.com/"]:not([href*="ads/library"])'
                        );
                        if (pageLink) {
                            ad.page_name = pageLink.textContent.trim();
                        }

                        // Primary text / ad body
                        const textElements = container.querySelectorAll(
                            'div[class*="x1iorvi4"], div[class*="_4ik4"], ' +
                            'div[style*="white-space"]'
                        );
                        if (textElements.length > 0) {
                            ad.primary_text = textElements[0].textContent.trim();
                        }

                        // Media detection
                        const video = container.querySelector('video');
                        const img = container.querySelector(
                            'img[class*="x1lliihq"], img[class*="_7jvy"]'
                        );

                        if (video) {
                            ad.ad_type = 'video';
                            ad.media_url = video.src || video.querySelector('source')?.src;
                        } else if (img) {
                            ad.ad_type = 'static';
                            ad.media_url = img.src;
                        }

                        // Headline
                        const headline = container.querySelector(
                            'div[class*="x8t9es0"], span[class*="x1lliihq"]'
                        );
                        if (headline) {
                            ad.headline = headline.textContent.trim();
                        }

                        // CTA
                        const cta = container.querySelector(
                            'div[class*="x1i10hfl"][role="button"], ' +
                            'a[class*="x1i10hfl"]'
                        );
                        if (cta) {
                            ad.cta_text = cta.textContent.trim();
                        }

                        // Link URL
                        const outLink = container.querySelector(
                            'a[href]:not([href*="facebook.com"])'
                        );
                        if (outLink) {
                            ad.link_url = outLink.href;
                        }

                        // Date started
                        const dateText = container.textContent.match(
                            /Started running on (.+?)(?:\\.|$)/
                        );
                        if (dateText) {
                            ad.started_running = dateText[1].trim();
                        }

                        // Platforms
                        ad.platforms = [];
                        for (const platform of [
                            'Facebook', 'Instagram', 'Messenger', 'Audience Network'
                        ]) {
                            if (container.textContent.includes(platform)) {
                                ad.platforms.push(platform.toLowerCase());
                            }
                        }

                        if (ad.ad_id || ad.primary_text || ad.media_url) {
                            ads.push(ad);
                        }
                    } catch (e) {
                        // Skip broken cards
                    }
                }
                return ads;
            }
            """
        )

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

    @staticmethod
    def _generate_id(raw: dict) -> str:
        """Generate a deterministic ID from ad content when no ID is available."""
        content = f"{raw.get('page_name', '')}{raw.get('primary_text', '')[:200]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
