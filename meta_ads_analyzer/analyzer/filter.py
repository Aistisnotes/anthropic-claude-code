"""Ad classification and filtering pipeline.

Determines which ads qualify for analysis based on:
- Video ads: included if EITHER (a) transcript meets quality threshold OR (b) OCR text extraction >= 50 words
- Static ads with primary copy >= 500 words: included (only long-form have strategic depth)
- Static ads with primary copy < 500 words: skipped
- Duplicate detection via content similarity
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from meta_ads_analyzer.models import (
    AdContent,
    AdStatus,
    AdType,
    DownloadedMedia,
    FilterReason,
    ScrapedAd,
    Transcript,
)
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class AdFilter:
    """Filter and classify ads for analysis."""

    def __init__(self, config: dict[str, Any]):
        f_cfg = config.get("filter", {})
        self.min_static_copy_words = f_cfg.get("min_static_copy_words", 500)
        self.min_transcript_confidence = f_cfg.get("min_transcript_confidence", 0.4)
        self.min_video_text_words = f_cfg.get("min_video_text_words", 50)
        self.skip_duplicates = f_cfg.get("skip_duplicates", True)
        self._seen_hashes: set[str] = set()
        self.config = config

    def process_ads(
        self,
        scraped_ads: list[ScrapedAd],
        downloads: dict[str, DownloadedMedia | None],
        transcripts: dict[str, Transcript | None],
        brand: str,
    ) -> list[AdContent]:
        """Process scraped ads through filtering pipeline.

        Returns list of AdContent objects with status indicating whether
        they passed filtering or were filtered out (with reason).
        """
        results: list[AdContent] = []
        included = 0
        filtered = 0

        for ad in scraped_ads:
            content = self._process_single(ad, downloads, transcripts, brand)
            results.append(content)

            if content.status == AdStatus.FILTERED_OUT:
                filtered += 1
            else:
                included += 1

        logger.info(
            f"Filtering complete: {included} included, {filtered} filtered out "
            f"of {len(scraped_ads)} total"
        )
        return results

    def _process_single(
        self,
        ad: ScrapedAd,
        downloads: dict[str, DownloadedMedia | None],
        transcripts: dict[str, Transcript | None],
        brand: str,
    ) -> AdContent:
        """Process a single ad through the filter pipeline."""
        download = downloads.get(ad.ad_id)
        transcript = transcripts.get(ad.ad_id)

        # Determine ad type
        ad_type = ad.ad_type
        if ad_type == AdType.UNKNOWN:
            if download and download.mime_type and download.mime_type.startswith("video/"):
                ad_type = AdType.VIDEO
            elif download:
                ad_type = AdType.STATIC

        # Build content object
        content = AdContent(
            ad_id=ad.ad_id,
            brand=brand,
            ad_type=ad_type,
            primary_text=ad.primary_text,
            headline=ad.headline,
            media_path=download.file_path if download else None,
            scrape_position=ad.scrape_position,
        )

        # --- VIDEO ADS ---
        if ad_type == AdType.VIDEO:
            if not download:
                content.status = AdStatus.FILTERED_OUT
                content.filter_reason = FilterReason.DOWNLOAD_FAILED
                logger.debug(f"Ad {ad.ad_id}: filtered (video download failed)")
                return content

            # Check for voiceover transcript
            has_transcript = (
                transcript
                and transcript.confidence >= self.min_transcript_confidence
                and transcript.word_count >= 20  # Meaningful voiceover
            )

            # If no good transcript, try OCR text extraction from video frames
            video_text_overlay = None
            video_text_word_count = 0

            if not has_transcript:
                from meta_ads_analyzer.extractor.video_text import VideoTextExtractor
                extractor = VideoTextExtractor(self.config)
                video_text_overlay = extractor.extract_text_from_video(download.file_path)

                if video_text_overlay:
                    video_text_word_count = len(video_text_overlay.split())
                    content.video_text_overlay = video_text_overlay

            has_video_text = video_text_word_count >= self.min_video_text_words

            # Video passes if it has EITHER transcript OR video text overlays
            if has_transcript:
                content.transcript = transcript.text
                content.transcript_confidence = transcript.confidence
                content.word_count = transcript.word_count
                content.status = AdStatus.TRANSCRIBED
                logger.debug(
                    f"Ad {ad.ad_id}: included (video with voiceover, "
                    f"{transcript.word_count} words, confidence={transcript.confidence:.2f})"
                )
            elif has_video_text:
                content.word_count = video_text_word_count
                content.status = AdStatus.DOWNLOADED
                logger.info(
                    f"Ad {ad.ad_id}: included (video with text overlays, {video_text_word_count} words extracted via OCR)"
                )
            else:
                content.status = AdStatus.FILTERED_OUT
                content.filter_reason = FilterReason.LOW_QUALITY_TRANSCRIPT
                logger.debug(
                    f"Ad {ad.ad_id}: filtered (video has neither voiceover nor text overlays)"
                )
                return content

        # --- STATIC ADS ---
        elif ad_type == AdType.STATIC:
            primary_text = ad.primary_text or ""
            word_count = len(primary_text.split())
            content.word_count = word_count

            if word_count < self.min_static_copy_words:
                content.status = AdStatus.FILTERED_OUT
                content.filter_reason = FilterReason.SHORT_COPY
                logger.debug(
                    f"Ad {ad.ad_id}: filtered (static, {word_count} words "
                    f"< {self.min_static_copy_words})"
                )
                return content

            content.status = AdStatus.DOWNLOADED

        # --- CAROUSEL / UNKNOWN ---
        else:
            # Include carousels/unknown if they have substantial text
            primary_text = ad.primary_text or ""
            word_count = len(primary_text.split())
            content.word_count = word_count

            if transcript:
                content.transcript = transcript.text
                content.transcript_confidence = transcript.confidence
                content.word_count = max(word_count, transcript.word_count)
                content.status = AdStatus.TRANSCRIBED
            elif word_count >= self.min_static_copy_words:
                content.status = AdStatus.DOWNLOADED
            else:
                content.status = AdStatus.FILTERED_OUT
                content.filter_reason = FilterReason.SHORT_COPY
                return content

        # --- DUPLICATE CHECK ---
        if self.skip_duplicates and content.status != AdStatus.FILTERED_OUT:
            content_hash = self._content_hash(content)
            if content_hash in self._seen_hashes:
                content.status = AdStatus.FILTERED_OUT
                content.filter_reason = FilterReason.DUPLICATE
                logger.debug(f"Ad {ad.ad_id}: filtered (duplicate)")
                return content
            self._seen_hashes.add(content_hash)

        return content

    @staticmethod
    def _content_hash(content: AdContent) -> str:
        """Generate hash of ad content for duplicate detection."""
        text = (content.transcript or content.primary_text or "")[:500]
        return hashlib.sha256(text.encode()).hexdigest()

    def reset(self) -> None:
        """Reset duplicate detection state between brands."""
        self._seen_hashes.clear()
