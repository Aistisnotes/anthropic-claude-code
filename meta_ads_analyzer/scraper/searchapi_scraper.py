"""Meta Ads Library scraper using SearchAPI.io.

Replaces Playwright-based scraping with SearchAPI.io's meta_ad_library engine.
SearchAPI scrapes Meta's Ad Library on their servers and returns clean JSON,
eliminating IP bans, removing browser dependency, and improving reliability.

API key must be set as environment variable: SEARCHAPI_KEY
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any, Optional

import httpx

from meta_ads_analyzer.models import AdType, ScrapedAd
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

SEARCHAPI_BASE_URL = "https://www.searchapi.io/api/v1/search"
RATE_LIMIT_DELAY = 2.0  # seconds between requests


def _get_api_key() -> str | None:
    """Get SearchAPI key from environment."""
    return os.environ.get("SEARCHAPI_KEY")


def _map_display_format(display_format: str | None) -> AdType:
    """Map SearchAPI display_format to our AdType enum."""
    if not display_format:
        return AdType.UNKNOWN
    fmt = display_format.upper()
    if "VIDEO" in fmt:
        return AdType.VIDEO
    elif "IMAGE" in fmt or "PHOTO" in fmt:
        return AdType.STATIC
    elif "CAROUSEL" in fmt or "MULTI" in fmt:
        return AdType.CAROUSEL
    return AdType.UNKNOWN


def _extract_media_url(snapshot: dict) -> tuple[str | None, str | None]:
    """Extract the best media URL and thumbnail from a snapshot.

    Returns:
        (media_url, thumbnail_url)
    """
    media_url = None
    thumbnail_url = None

    # Video: prefer HD URL
    videos = snapshot.get("videos") or []
    if videos:
        video = videos[0]
        media_url = video.get("video_hd_url") or video.get("video_sd_url") or video.get("video_url")
        thumbnail_url = video.get("video_preview_image_url")

    # Image fallback
    if not media_url:
        images = snapshot.get("images") or []
        if images:
            img = images[0]
            media_url = img.get("original_image_url") or img.get("resized_image_url")

    return media_url, thumbnail_url


def _snapshot_to_scraped_ad(ad_data: dict, position: int = 0) -> ScrapedAd:
    """Convert a SearchAPI ad object to our ScrapedAd model."""
    snapshot = ad_data.get("snapshot") or {}
    body = snapshot.get("body") or {}

    # Ad ID
    ad_id = str(ad_data.get("ad_archive_id") or "")
    if not ad_id:
        # Generate deterministic ID from content
        content = f"{snapshot.get('page_name', '')}{(body.get('text') or '')[:200]}"
        ad_id = hashlib.sha256(content.encode()).hexdigest()[:16]

    # Display format → AdType
    display_format = snapshot.get("display_format")
    ad_type = _map_display_format(display_format)

    # Media URLs
    media_url, thumbnail_url = _extract_media_url(snapshot)

    # Primary text (ad copy)
    primary_text = body.get("text") or ""

    # Page info
    page_name = snapshot.get("page_name") or ad_data.get("page_name") or "Unknown"
    page_id = str(snapshot.get("page_id") or ad_data.get("page_id") or "")
    if not page_id:
        page_id = None

    # CTA and link
    cta_text = snapshot.get("cta_text") or ""
    link_url = snapshot.get("link_url") or ""
    caption = snapshot.get("caption") or ""

    # Headline / title
    headline = snapshot.get("title") or ""

    # Date
    started_running = ad_data.get("start_date") or ""

    # Platforms
    platforms = []
    publisher_platforms = ad_data.get("publisher_platforms") or []
    for p in publisher_platforms:
        if isinstance(p, str):
            platforms.append(p.lower())

    return ScrapedAd(
        ad_id=ad_id,
        page_name=page_name,
        page_id=page_id,
        ad_type=ad_type,
        primary_text=primary_text if primary_text else None,
        headline=headline if headline else None,
        cta_text=cta_text if cta_text else None,
        link_url=link_url if link_url else None,
        media_url=media_url,
        thumbnail_url=thumbnail_url,
        started_running=started_running if started_running else None,
        platforms=platforms,
        scrape_position=position,
    )


class SearchAPIScraper:
    """Scrape Meta Ad Library via SearchAPI.io REST API."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.scraper_cfg = config.get("scraper", {})
        self.max_ads = self.scraper_cfg.get("max_ads", 100)
        self.filters = self.scraper_cfg.get("filters", {})
        self.api_key = _get_api_key()
        # Page IDs discovered during page_search (for compatibility with Playwright scraper)
        self._found_page_ids: list[str] = []

    @property
    def found_page_ids(self) -> list[str]:
        """Page IDs discovered during the most recent scrape() call."""
        return list(self._found_page_ids)

    async def scrape(
        self,
        query: str,
        page_id: str | None = None,
        expected_page_name: str | None = None,
        sort_by_impressions: bool = False,
    ) -> list[ScrapedAd]:
        """Scrape ads matching the query from Meta Ads Library via SearchAPI.

        Args:
            query: Search keyword or brand name
            page_id: Optional Facebook page ID for brand-specific search
            expected_page_name: When set, filter results to this page_name
            sort_by_impressions: Ignored — SearchAPI always sorts by impressions
        """
        if not self.api_key:
            raise ValueError(
                "SEARCHAPI_KEY environment variable not set. "
                "Set it to use SearchAPI.io scraping."
            )

        self._found_page_ids = []

        if page_id:
            logger.info(f"SearchAPI: scraping page_id={page_id} (max {self.max_ads} ads)")
            return await self._scrape_by_page_id(page_id, expected_page_name)
        else:
            logger.info(f"SearchAPI: scraping query='{query}' (max {self.max_ads} ads)")
            return await self._scrape_by_keyword(query)

    async def _make_request(self, params: dict) -> dict:
        """Make a single SearchAPI request with error handling."""
        params["api_key"] = self.api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(SEARCHAPI_BASE_URL, params=params)
            resp.raise_for_status()
            return resp.json()

    async def _scrape_by_keyword(self, keyword: str) -> list[ScrapedAd]:
        """Search Meta Ad Library by keyword with pagination."""
        country = self.filters.get("country", "US").lower()
        status = self.filters.get("status", "active")
        media_type = self.filters.get("media_type", "all")

        params = {
            "engine": "meta_ad_library",
            "q": keyword,
            "country": country,
            "active_status": status,
            "ad_type": "all",
            "media_type": media_type,
            "sort": "impressions_high_to_low",
        }

        ads: list[ScrapedAd] = []
        seen_ids: set[str] = set()
        next_page_token: str | None = None
        page_num = 0

        while len(ads) < self.max_ads:
            if next_page_token:
                params["next_page_token"] = next_page_token

            try:
                data = await self._make_request(params)
            except httpx.HTTPStatusError as e:
                logger.error(f"SearchAPI HTTP error: {e.response.status_code} - {e.response.text[:200]}")
                break
            except Exception as e:
                logger.error(f"SearchAPI request failed: {e}")
                break

            page_num += 1
            raw_ads = data.get("ads") or []

            if not raw_ads:
                logger.info(f"SearchAPI: no more ads on page {page_num}")
                break

            # Log total results on first page
            if page_num == 1:
                total = data.get("search_information", {}).get("total_results", "?")
                logger.info(f"SearchAPI: '{keyword}' → {total} total results")

            for raw_ad in raw_ads:
                ad = _snapshot_to_scraped_ad(raw_ad, position=len(ads))
                if ad.ad_id not in seen_ids:
                    seen_ids.add(ad.ad_id)
                    ads.append(ad)
                    # Collect page_ids for compatibility
                    if ad.page_id and ad.page_id not in self._found_page_ids:
                        self._found_page_ids.append(ad.page_id)
                    if len(ads) >= self.max_ads:
                        break

            # Check for next page
            next_page_token = data.get("pagination", {}).get("next_page_token")
            if not next_page_token:
                logger.info(f"SearchAPI: no more pages after page {page_num}")
                break

            # Rate limiting
            await asyncio.sleep(RATE_LIMIT_DELAY)

        logger.info(f"SearchAPI: scraped {len(ads)} ads for keyword '{keyword}'")
        return ads

    async def _scrape_by_page_id(
        self,
        page_id: str,
        expected_page_name: str | None = None,
    ) -> list[ScrapedAd]:
        """Search Meta Ad Library by page_id with pagination."""
        country = self.filters.get("country", "US").lower()
        status = self.filters.get("status", "active")
        media_type = self.filters.get("media_type", "all")

        params = {
            "engine": "meta_ad_library",
            "page_id": page_id,
            "country": country,
            "active_status": status,
            "ad_type": "all",
            "media_type": media_type,
            "sort": "impressions_high_to_low",
        }

        ads: list[ScrapedAd] = []
        seen_ids: set[str] = set()
        next_page_token: str | None = None
        page_num = 0

        while len(ads) < self.max_ads:
            if next_page_token:
                params["next_page_token"] = next_page_token

            try:
                data = await self._make_request(params)
            except httpx.HTTPStatusError as e:
                logger.error(f"SearchAPI HTTP error: {e.response.status_code} - {e.response.text[:200]}")
                break
            except Exception as e:
                logger.error(f"SearchAPI request failed: {e}")
                break

            page_num += 1
            raw_ads = data.get("ads") or []

            if not raw_ads:
                break

            if page_num == 1:
                total = data.get("search_information", {}).get("total_results", "?")
                logger.info(f"SearchAPI: page_id={page_id} → {total} total results")

            for raw_ad in raw_ads:
                ad = _snapshot_to_scraped_ad(raw_ad, position=len(ads))

                # Filter by expected page name if set
                if expected_page_name and ad.page_name != expected_page_name:
                    continue

                if ad.ad_id not in seen_ids:
                    seen_ids.add(ad.ad_id)
                    ads.append(ad)
                    if len(ads) >= self.max_ads:
                        break

            next_page_token = data.get("pagination", {}).get("next_page_token")
            if not next_page_token:
                break

            await asyncio.sleep(RATE_LIMIT_DELAY)

        # Store the page_id we searched
        if page_id not in self._found_page_ids:
            self._found_page_ids.append(page_id)

        logger.info(f"SearchAPI: scraped {len(ads)} ads for page_id={page_id}")
        return ads

    async def find_page_id(self, brand_name: str) -> str | None:
        """Find a Facebook page ID from a brand name using page search.

        Args:
            brand_name: Brand name to search for

        Returns:
            page_id string, or None if not found
        """
        if not self.api_key:
            return None

        params = {
            "engine": "meta_ad_library_page_search",
            "q": brand_name,
            "country": self.filters.get("country", "US").lower(),
        }

        try:
            data = await self._make_request(params)
            pages = data.get("pages") or data.get("results") or []
            if pages:
                # Return the first matching page
                page = pages[0]
                page_id = str(page.get("page_id") or page.get("id") or "")
                if page_id:
                    logger.info(f"SearchAPI: found page_id={page_id} for '{brand_name}'")
                    return page_id
        except Exception as e:
            logger.warning(f"SearchAPI page search failed for '{brand_name}': {e}")

        return None


async def get_ad_count_searchapi(keyword: str) -> int:
    """Get total ad count for a keyword via SearchAPI (single request, no pagination).

    Used by pain_point_analyzer for demand validation.

    Args:
        keyword: Search keyword

    Returns:
        Total ad count, or 0 if unavailable
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("SEARCHAPI_KEY not set — cannot get ad count")
        return 0

    params = {
        "engine": "meta_ad_library",
        "q": keyword,
        "country": "us",
        "active_status": "active",
        "ad_type": "all",
        "api_key": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(SEARCHAPI_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        total = data.get("search_information", {}).get("total_results", 0)
        if isinstance(total, str):
            total = int(total.replace(",", ""))
        logger.info(f"SearchAPI ad count: '{keyword}' → {total}")
        return total
    except Exception as e:
        logger.warning(f"SearchAPI ad count failed for '{keyword}': {e}")
        return 0


def is_searchapi_available() -> bool:
    """Check if SearchAPI.io is configured (API key set)."""
    return bool(_get_api_key())
