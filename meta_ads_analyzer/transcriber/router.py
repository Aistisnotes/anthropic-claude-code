"""Transcription backend router.

Selects backend based on config [transcription].backend and OPENAI_API_KEY env var.
Falls back to local Whisper if API key is missing or API calls fail.
"""

from __future__ import annotations

import os
from typing import Any

from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


def make_transcriber(config: dict[str, Any]):
    """Return the appropriate transcriber based on config and environment.

    Priority:
    1. If backend = "openai_api" AND OPENAI_API_KEY is set → OpenAITranscriber
    2. If backend = "openai_api" AND key not set → warn, fall back to local
    3. If backend = "local_mlx" or "local_whisper" → WhisperTranscriber
    """
    backend = config.get("transcription", {}).get("backend", "local_mlx")

    if backend == "openai_api":
        if os.environ.get("OPENAI_API_KEY"):
            logger.info("Transcription backend: openai_api (whisper-1) with local fallback")
            return FallbackTranscriber(config)
        else:
            logger.warning(
                "Transcription backend 'openai_api' requested but OPENAI_API_KEY is not set. "
                "Falling back to local Whisper."
            )

    # local_mlx, local_whisper, or fallback
    from meta_ads_analyzer.transcriber.whisper import WhisperTranscriber
    backend_label = "local_mlx" if config.get("transcriber", {}).get("use_mlx", True) else "local_whisper"
    logger.info(f"Transcription backend: {backend_label}")
    return WhisperTranscriber(config)


class FallbackTranscriber:
    """Wraps OpenAITranscriber with per-file fallback to local Whisper on failure."""

    def __init__(self, config: dict[str, Any]):
        from meta_ads_analyzer.transcriber.openai_transcriber import OpenAITranscriber
        from meta_ads_analyzer.transcriber.whisper import WhisperTranscriber
        self._api = OpenAITranscriber(config)
        self._local = WhisperTranscriber(config)
        self._config = config

    async def transcribe_batch(self, media_files):
        """Attempt API transcription; fall back per-file to local on failure."""
        from meta_ads_analyzer.models import DownloadedMedia

        api_results = await self._api.transcribe_batch(media_files)

        # Identify files where API returned None — retry with local
        failed = [m for m in media_files if api_results.get(m.ad_id) is None]
        if failed:
            logger.info(
                f"{len(failed)} file(s) failed API transcription — "
                f"retrying with local Whisper"
            )
            local_results = await self._local.transcribe_batch(failed)
            api_results.update(local_results)

        return api_results
