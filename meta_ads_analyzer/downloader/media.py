"""Download video and image media from scraped ad URLs.

Uses yt-dlp for video downloads (handles Facebook's video CDN) and
aiohttp for direct image/asset downloads.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Optional

import aiohttp

from meta_ads_analyzer.models import AdType, DownloadedMedia, ScrapedAd
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class MediaDownloader:
    """Download media files from scraped ads."""

    def __init__(self, config: dict[str, Any]):
        dl_cfg = config.get("downloader", {})
        self.max_concurrent = dl_cfg.get("max_concurrent", 5)
        self.timeout = dl_cfg.get("timeout", 120)
        self.max_file_size_mb = dl_cfg.get("max_file_size_mb", 500)
        self.output_dir = Path(dl_cfg.get("output_dir", "output/downloads"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def download_ads(
        self, ads: list[ScrapedAd], run_id: str
    ) -> dict[str, DownloadedMedia | None]:
        """Download media for a batch of ads.

        Returns mapping of ad_id -> DownloadedMedia (None if download failed).
        """
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: dict[str, DownloadedMedia | None] = {}

        async def _download_one(ad: ScrapedAd):
            async with semaphore:
                result = await self._download_ad_media(ad, run_dir)
                results[ad.ad_id] = result

        tasks = [_download_one(ad) for ad in ads if ad.media_url]
        await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(
            f"Downloaded {success_count}/{len(ads)} media files for run {run_id}"
        )
        return results

    async def _download_ad_media(
        self, ad: ScrapedAd, run_dir: Path
    ) -> Optional[DownloadedMedia]:
        """Download media for a single ad."""
        if not ad.media_url:
            return None

        try:
            if ad.ad_type == AdType.VIDEO:
                return await self._download_video(ad, run_dir)
            else:
                return await self._download_image(ad, run_dir)
        except Exception as e:
            logger.warning(f"Failed to download media for ad {ad.ad_id}: {e}")
            return None

    async def _download_video(
        self, ad: ScrapedAd, run_dir: Path
    ) -> Optional[DownloadedMedia]:
        """Download video using yt-dlp (handles Facebook CDN well)."""
        output_path = run_dir / f"{ad.ad_id}.mp4"

        if output_path.exists():
            logger.info(f"Video already downloaded: {ad.ad_id}")
            return self._make_media_result(ad.ad_id, output_path)

        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-progress",
            "-f", "best[ext=mp4]/best",
            "--max-filesize", f"{self.max_file_size_mb}M",
            "-o", str(output_path),
            ad.media_url,
        ]

        logger.info(f"Downloading video for ad {ad.ad_id}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            if proc.returncode != 0:
                # Fallback: try direct HTTP download
                logger.warning(
                    f"yt-dlp failed for {ad.ad_id}, trying direct download"
                )
                return await self._download_direct(ad.ad_id, ad.media_url, run_dir, ".mp4")

            if output_path.exists():
                return self._make_media_result(ad.ad_id, output_path)

            # yt-dlp may have added extension, find the file
            for f in run_dir.glob(f"{ad.ad_id}.*"):
                return self._make_media_result(ad.ad_id, f)

            return None

        except asyncio.TimeoutError:
            logger.warning(f"Download timeout for ad {ad.ad_id}")
            return None

    async def _download_image(
        self, ad: ScrapedAd, run_dir: Path
    ) -> Optional[DownloadedMedia]:
        """Download static image via HTTP."""
        return await self._download_direct(
            ad.ad_id, ad.media_url, run_dir, ".jpg"
        )

    async def _download_direct(
        self, ad_id: str, url: str, run_dir: Path, ext: str
    ) -> Optional[DownloadedMedia]:
        """Direct HTTP download for media files."""
        output_path = run_dir / f"{ad_id}{ext}"

        if output_path.exists():
            return self._make_media_result(ad_id, output_path)

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"HTTP {resp.status} downloading {ad_id}"
                        )
                        return None

                    # Check content length
                    cl = resp.content_length
                    if cl and cl > self.max_file_size_mb * 1024 * 1024:
                        logger.warning(f"File too large for {ad_id}: {cl} bytes")
                        return None

                    content = await resp.read()
                    output_path.write_bytes(content)
                    return self._make_media_result(ad_id, output_path)

        except Exception as e:
            logger.warning(f"Direct download failed for {ad_id}: {e}")
            return None

    @staticmethod
    def _make_media_result(ad_id: str, path: Path) -> DownloadedMedia:
        stat = path.stat()
        # Detect duration for video files using ffprobe if available
        duration = None
        if path.suffix in (".mp4", ".webm", ".mov"):
            try:
                result = subprocess.run(
                    [
                        "ffprobe", "-v", "quiet",
                        "-show_entries", "format=duration",
                        "-of", "csv=p=0",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    duration = float(result.stdout.strip())
            except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
                pass

        return DownloadedMedia(
            ad_id=ad_id,
            file_path=path,
            file_size_bytes=stat.st_size,
            duration_seconds=duration,
            mime_type=_ext_to_mime(path.suffix),
        )


def _ext_to_mime(ext: str) -> str:
    mapping = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mapping.get(ext.lower(), "application/octet-stream")
