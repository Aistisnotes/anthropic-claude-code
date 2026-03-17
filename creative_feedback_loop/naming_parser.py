"""Extract components from ad naming conventions.

Parses ad names like:
  B310_V1, B150_V1_UGC, B279_V3_LSS, B255_V1_TH
  
Convention: B{batch}_{version}_{format}_{variant}

Components extracted:
  - batch: Brief/batch number (e.g., 310)
  - version: Version number (e.g., 1, 2, 3)
  - format_code: UGC, LSS, LFS, TH, VSL, etc.
  - variant: Additional variant info
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Format code mappings
FORMAT_CODES = {
    "UGC": "UGC (User Generated Content)",
    "LSS": "Long Form Static",
    "LFS": "Long Form Static",
    "TH": "Talking Head",
    "VSL": "Video Sales Letter",
    "SS": "Short Static",
    "GIF": "GIF/Animation",
    "CAR": "Carousel",
    "IMG": "Image Ad",
    "VID": "Video Ad",
    "DPA": "Dynamic Product Ad",
    "COL": "Collection Ad",
    "SLD": "Slideshow",
    "REM": "Remarketing",
    "PRO": "Prospecting",
    "RTG": "Retargeting",
}


@dataclass
class ParsedAdName:
    """Parsed components from an ad name."""

    raw_name: str
    batch: Optional[int] = None
    version: Optional[int] = None
    format_code: Optional[str] = None
    format_label: Optional[str] = None
    variant: Optional[str] = None
    editor: Optional[str] = None
    components: dict = field(default_factory=dict)

    @property
    def batch_label(self) -> str:
        return f"B{self.batch}" if self.batch else "Unknown"

    @property
    def version_label(self) -> str:
        return f"V{self.version}" if self.version else "V1"


def parse_ad_name(name: str) -> ParsedAdName:
    """Parse an ad name into its components.

    Handles formats like:
      B310_V1
      B310_V1_UGC
      B310_V1_UGC_KidneyFocus
      B310-V1-UGC
      Batch310_Ver1_UGC
    """
    result = ParsedAdName(raw_name=name)

    if not name:
        return result

    # Normalize separators
    normalized = name.strip().replace("-", "_").replace(" ", "_")
    parts = [p.strip() for p in normalized.split("_") if p.strip()]

    for part in parts:
        upper = part.upper()

        # Batch number: B310, Batch310, B-310
        batch_match = re.match(r"^B(?:ATCH)?(\d+)$", upper)
        if batch_match and result.batch is None:
            result.batch = int(batch_match.group(1))
            continue

        # Version: V1, V2, Ver1, Version2
        ver_match = re.match(r"^V(?:ER(?:SION)?)?(\d+)$", upper)
        if ver_match and result.version is None:
            result.version = int(ver_match.group(1))
            continue

        # Format code
        if upper in FORMAT_CODES and result.format_code is None:
            result.format_code = upper
            result.format_label = FORMAT_CODES[upper]
            continue

        # Everything else is variant/descriptor
        if result.batch is not None:  # Only capture after batch is found
            if result.variant is None:
                result.variant = part
            else:
                result.variant += f"_{part}"

    # Store parsed components dict
    result.components = {
        "batch": result.batch,
        "version": result.version,
        "format_code": result.format_code,
        "format_label": result.format_label,
        "variant": result.variant,
    }

    return result


def parse_ad_names_batch(names: list[str]) -> list[ParsedAdName]:
    """Parse a batch of ad names."""
    return [parse_ad_name(name) for name in names]


def extract_editor_from_name(name: str) -> Optional[str]:
    """Extract editor/creator name if embedded in ad name.

    Some conventions include editor: B310_V1_UGC_JohnD
    """
    parsed = parse_ad_name(name)
    # If variant looks like a name (capitalized, no numbers), treat as editor
    if parsed.variant and re.match(r"^[A-Z][a-z]+[A-Z]?[a-z]*$", parsed.variant):
        return parsed.variant
    return None


def group_ads_by_batch(names: list[str]) -> dict[int, list[str]]:
    """Group ad names by batch number."""
    groups: dict[int, list[str]] = {}
    for name in names:
        parsed = parse_ad_name(name)
        if parsed.batch is not None:
            groups.setdefault(parsed.batch, []).append(name)
    return groups


def group_ads_by_format(names: list[str]) -> dict[str, list[str]]:
    """Group ad names by format code."""
    groups: dict[str, list[str]] = {}
    for name in names:
        parsed = parse_ad_name(name)
        fmt = parsed.format_code or "Unknown"
        groups.setdefault(fmt, []).append(name)
    return groups
