"""Extract text overlays from video ads using OCR.

Many beauty/DTC brands communicate entirely through text overlays on video
rather than voiceover. This module extracts on-screen text for analysis.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

try:
    import pytesseract
    from PIL import Image
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class VideoTextExtractor:
    """Extract text overlays from video frames using OCR."""

    def __init__(self, config: dict):
        self.config = config
        self.num_frames = config.get("extractor", {}).get("frames_per_video", 8)
        self.min_text_length = config.get("extractor", {}).get("min_frame_text_length", 3)

        if not PYTESSERACT_AVAILABLE:
            logger.warning(
                "pytesseract not available. Video text extraction will be skipped. "
                "Install with: pip install pytesseract"
            )

    def extract_text_from_video(self, video_path: Path) -> Optional[str]:
        """Extract text overlays from video using OCR on sampled frames.

        Args:
            video_path: Path to video file

        Returns:
            Combined text from all frames, or None if extraction fails
        """
        if not PYTESSERACT_AVAILABLE:
            return None

        if not video_path.exists():
            logger.warning(f"Video file not found: {video_path}")
            return None

        try:
            # Extract frames
            frames = self._extract_frames(video_path)
            if not frames:
                logger.debug(f"No frames extracted from {video_path.name}")
                return None

            # OCR each frame
            all_text = []
            for i, frame_path in enumerate(frames):
                try:
                    text = self._ocr_frame(frame_path)
                    if text and len(text.split()) >= self.min_text_length:
                        all_text.append(text)
                        logger.debug(f"Frame {i}: extracted {len(text.split())} words")
                except Exception as e:
                    logger.debug(f"OCR failed for frame {i}: {e}")
                finally:
                    # Clean up frame
                    frame_path.unlink(missing_ok=True)

            if not all_text:
                return None

            # Combine and deduplicate
            combined = " ".join(all_text)
            words = combined.split()

            # Simple deduplication: remove consecutive duplicates
            deduped = []
            prev = None
            for word in words:
                if word != prev:
                    deduped.append(word)
                    prev = word

            result = " ".join(deduped)
            logger.info(
                f"Extracted {len(deduped)} words from {len(frames)} frames "
                f"in {video_path.name}"
            )
            return result

        except Exception as e:
            logger.warning(f"Video text extraction failed for {video_path.name}: {e}")
            return None

    def _extract_frames(self, video_path: Path) -> list[Path]:
        """Extract evenly-spaced frames from video using ffmpeg.

        Args:
            video_path: Path to video file

        Returns:
            List of paths to extracted frame images
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Get video duration
            duration_cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]

            try:
                result = subprocess.run(
                    duration_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
                duration = float(result.stdout.strip())
            except (subprocess.SubprocessError, ValueError) as e:
                logger.debug(f"Could not get video duration: {e}")
                duration = 10  # Fallback duration

            # Calculate frame timestamps (evenly spaced)
            if duration < 1:
                timestamps = [0.5]
            else:
                # Extract frames at 1/8, 2/8, 3/8, ... of duration
                timestamps = [duration * (i + 1) / (self.num_frames + 1)
                             for i in range(self.num_frames)]

            # Extract frames
            frame_paths = []
            for i, ts in enumerate(timestamps):
                output_path = tmpdir_path / f"frame_{i:03d}.png"

                extract_cmd = [
                    "ffmpeg",
                    "-ss", str(ts),
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-f", "image2",
                    "-y",  # Overwrite
                    str(output_path),
                ]

                try:
                    subprocess.run(
                        extract_cmd,
                        capture_output=True,
                        timeout=10,
                        check=True,
                    )
                    if output_path.exists():
                        # Copy to permanent location
                        perm_path = video_path.parent / f"{video_path.stem}_frame_{i:03d}.png"
                        import shutil
                        shutil.copy(output_path, perm_path)
                        frame_paths.append(perm_path)
                except subprocess.SubprocessError:
                    pass

            return frame_paths

    def _ocr_frame(self, frame_path: Path) -> str:
        """Run OCR on a single frame image.

        Args:
            frame_path: Path to frame image

        Returns:
            Extracted text
        """
        try:
            img = Image.open(frame_path)

            # Use pytesseract with optimized config for video text
            # - PSM 6: Assume a single uniform block of text
            # - OEM 3: Default OCR Engine Mode
            custom_config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(img, config=custom_config)

            # Clean up text
            text = text.strip()
            text = " ".join(text.split())  # Normalize whitespace

            return text
        except Exception as e:
            logger.debug(f"OCR failed for {frame_path.name}: {e}")
            return ""
