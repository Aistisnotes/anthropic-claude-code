"""Audio transcription using Whisper, optimized for Apple Silicon via MLX.

Supports both mlx-whisper (Apple Silicon optimized) and standard openai-whisper.
For Mac Studio M3 Max with 96GB RAM, mlx-whisper with large-v3 model is recommended.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from meta_ads_analyzer.models import DownloadedMedia, Transcript, TranscriptSegment
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class WhisperTranscriber:
    """Transcribe video/audio files using Whisper."""

    def __init__(self, config: dict[str, Any]):
        t_cfg = config.get("transcriber", {})
        self.model_size = t_cfg.get("model_size", "large-v3")
        self.use_mlx = t_cfg.get("use_mlx", True)
        self.language = t_cfg.get("language", "") or None
        self.max_concurrent = t_cfg.get("max_concurrent", 2)
        self.min_confidence = t_cfg.get("min_confidence", 0.5)
        self._model = None
        self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent)

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._model is not None:
            return

        if self.use_mlx:
            try:
                import mlx_whisper

                logger.info(
                    f"Loading MLX Whisper model: mlx-community/whisper-{self.model_size}-mlx"
                )
                # mlx_whisper uses model paths, not model objects
                self._model = f"mlx-community/whisper-{self.model_size}-mlx"
                self._backend = "mlx"
                logger.info("MLX Whisper model ready (Apple Silicon optimized)")
                return
            except ImportError:
                logger.warning("mlx-whisper not available, falling back to openai-whisper")

        try:
            import whisper

            logger.info(f"Loading OpenAI Whisper model: {self.model_size}")
            self._model = whisper.load_model(self.model_size)
            self._backend = "openai"
            logger.info("OpenAI Whisper model loaded")
        except ImportError:
            raise RuntimeError(
                "No whisper backend available. Install mlx-whisper (Apple Silicon) "
                "or openai-whisper."
            )

    async def transcribe_batch(
        self, media_files: list[DownloadedMedia]
    ) -> dict[str, Transcript | None]:
        """Transcribe a batch of media files.

        Returns mapping of ad_id -> Transcript (None if failed).
        """
        self._load_model()

        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: dict[str, Transcript | None] = {}

        async def _transcribe_one(media: DownloadedMedia):
            async with semaphore:
                result = await self._transcribe_file(media)
                results[media.ad_id] = result

        video_files = [
            m for m in media_files
            if m.mime_type and m.mime_type.startswith("video/")
        ]

        logger.info(f"Transcribing {len(video_files)} video files")
        tasks = [_transcribe_one(m) for m in video_files]
        await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for v in results.values() if v is not None)
        logger.info(f"Transcribed {success}/{len(video_files)} files")
        return results

    async def _transcribe_file(
        self, media: DownloadedMedia
    ) -> Optional[Transcript]:
        """Transcribe a single media file."""
        if not media.file_path.exists():
            logger.warning(f"File not found: {media.file_path}")
            return None

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self._executor, self._run_whisper, str(media.file_path)
            )

            if result is None:
                return None

            segments = []
            avg_confidence = 0.0

            if "segments" in result:
                confidences = []
                for seg in result["segments"]:
                    segments.append(
                        TranscriptSegment(
                            start=seg.get("start", 0.0),
                            end=seg.get("end", 0.0),
                            text=seg.get("text", "").strip(),
                        )
                    )
                    # no_speech_prob is inverse of confidence
                    no_speech = seg.get("no_speech_prob", 0.5)
                    confidences.append(1.0 - no_speech)

                if confidences:
                    avg_confidence = sum(confidences) / len(confidences)

            text = result.get("text", "").strip()
            word_count = len(text.split()) if text else 0

            transcript = Transcript(
                ad_id=media.ad_id,
                text=text,
                language=result.get("language", "en"),
                confidence=avg_confidence,
                word_count=word_count,
                segments=segments,
            )

            logger.info(
                f"Transcribed {media.ad_id}: {word_count} words, "
                f"confidence={avg_confidence:.2f}"
            )
            return transcript

        except Exception as e:
            logger.error(f"Transcription failed for {media.ad_id}: {e}")
            return None

    def _run_whisper(self, file_path: str) -> Optional[dict]:
        """Run whisper inference (blocking, called in executor)."""
        try:
            if self._backend == "mlx":
                import mlx_whisper

                result = mlx_whisper.transcribe(
                    file_path,
                    path_or_hf_repo=self._model,
                    language=self.language,
                    verbose=False,
                )
                return result

            else:
                # openai-whisper
                result = self._model.transcribe(
                    file_path,
                    language=self.language,
                    verbose=False,
                )
                return result

        except Exception as e:
            logger.error(f"Whisper inference error: {e}")
            return None
