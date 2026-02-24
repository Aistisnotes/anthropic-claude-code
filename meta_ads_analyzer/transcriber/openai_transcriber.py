"""Transcription via OpenAI Whisper API.

Uses the /v1/audio/transcriptions endpoint with whisper-1 model.
Default confidence is 0.95 (API does not return per-segment confidence).
Files > 25 MB are compressed to MP3 before sending.
Supports up to 5 concurrent requests with exponential backoff on rate limits.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from meta_ads_analyzer.models import DownloadedMedia, Transcript, TranscriptSegment
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

# OpenAI file size limit in bytes
_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB
_API_CONFIDENCE = 0.95  # Whisper API doesn't return confidence scores


class OpenAITranscriber:
    """Transcribe audio/video via OpenAI Whisper API."""

    def __init__(self, config: dict[str, Any]):
        t_cfg = config.get("transcription", {})
        self.model = t_cfg.get("openai_model", "whisper-1")
        self.max_concurrent = t_cfg.get("openai_max_concurrent", 5)
        self.language = config.get("transcriber", {}).get("language") or None

    async def transcribe_batch(
        self, media_files: list[DownloadedMedia]
    ) -> dict[str, Transcript | None]:
        """Transcribe a batch of media files via OpenAI API.

        Returns mapping of ad_id -> Transcript (None if failed).
        """
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: dict[str, Transcript | None] = {}

        video_files = [
            m for m in media_files
            if m.mime_type and m.mime_type.startswith("video/")
        ]

        logger.info(f"Transcribing {len(video_files)} files via OpenAI Whisper API")

        async def _transcribe_one(media: DownloadedMedia):
            async with semaphore:
                result = await self._transcribe_file(client, media)
                results[media.ad_id] = result

        await asyncio.gather(*[_transcribe_one(m) for m in video_files], return_exceptions=True)

        success = sum(1 for v in results.values() if v is not None)
        logger.info(f"Transcribed {success}/{len(video_files)} files via OpenAI API")
        return results

    async def _transcribe_file(
        self, client: Any, media: DownloadedMedia
    ) -> Optional[Transcript]:
        """Transcribe a single file with retry on rate limits."""
        if not media.file_path.exists():
            logger.warning(f"File not found: {media.file_path}")
            return None

        file_path = media.file_path
        compressed_path: Optional[Path] = None

        try:
            # Compress if over 25 MB
            if file_path.stat().st_size > _MAX_FILE_BYTES:
                compressed_path = await self._compress_audio(file_path)
                if compressed_path is None:
                    logger.warning(f"Compression failed for {media.ad_id}, skipping")
                    return None
                file_path = compressed_path

            t0 = time.monotonic()
            text = await self._call_api_with_retry(client, file_path)
            elapsed = time.monotonic() - t0

            if text is None:
                return None

            word_count = len(text.split()) if text else 0
            logger.info(
                f"Transcribed {media.ad_id}: {word_count} words, "
                f"confidence={_API_CONFIDENCE:.2f}, backend=openai_api, time={elapsed:.1f}s"
            )

            return Transcript(
                ad_id=media.ad_id,
                text=text,
                language=self.language or "en",
                confidence=_API_CONFIDENCE,
                word_count=word_count,
                segments=[],
            )

        except Exception as e:
            logger.error(f"OpenAI transcription failed for {media.ad_id}: {e}")
            return None
        finally:
            if compressed_path and compressed_path.exists():
                compressed_path.unlink(missing_ok=True)

    async def _call_api_with_retry(
        self, client: Any, file_path: Path
    ) -> Optional[str]:
        """Call API with exponential backoff on rate limits (3 attempts)."""
        from openai import RateLimitError

        for attempt in range(3):
            try:
                with open(file_path, "rb") as f:
                    response = await client.audio.transcriptions.create(
                        model=self.model,
                        file=f,
                        language=self.language,
                        response_format="text",
                    )
                return response if isinstance(response, str) else str(response)

            except RateLimitError:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                logger.warning(
                    f"OpenAI rate limit hit (attempt {attempt + 1}/3), "
                    f"retrying in {wait}s"
                )
                if attempt < 2:
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI rate limit: max retries exceeded")
                    return None

            except Exception as e:
                logger.error(f"OpenAI API error on attempt {attempt + 1}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return None

        return None

    async def _compress_audio(self, file_path: Path) -> Optional[Path]:
        """Compress audio to MP3 at 64kbps mono to get under 25 MB limit."""
        out_path = file_path.with_suffix(".compressed.mp3")
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(file_path),
                "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
                str(out_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0 and out_path.exists():
                size_mb = out_path.stat().st_size / 1024 / 1024
                logger.info(f"Compressed {file_path.name} to {size_mb:.1f} MB MP3")
                return out_path
            logger.error(f"ffmpeg compression failed for {file_path}")
            return None
        except Exception as e:
            logger.error(f"Compression error: {e}")
            return None
