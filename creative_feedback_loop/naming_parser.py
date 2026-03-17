"""Ad naming convention parser.

Extracts structured dimensions from ad names following patterns like:
  B310_V1_Kidney_ProblemAware_LFS_RenalLymphaticClogged_General
"""

from __future__ import annotations

import re
from typing import Any, Optional


# Known dimension values for fuzzy matching
PAIN_POINTS = [
    "Kidney", "Liver", "Thyroid", "Cholesterol", "Lymph", "Bladder",
    "Prostate", "Heart", "Blood", "Sugar", "Weight", "Joint", "Gut",
    "Brain", "Skin", "Hair", "Sleep", "Energy", "Immune", "Detox",
]

AWARENESS_LEVELS = [
    "Unaware", "ProblemAware", "SolutionAware", "ProductAware", "MostAware",
    "Problem Aware", "Solution Aware", "Product Aware", "Most Aware",
]

AD_FORMATS = [
    "LFS", "LFV", "SFS", "SFV", "UGC", "Carousel", "Static", "Video",
    "LongFormStatic", "LongFormVideo", "ShortFormStatic", "ShortFormVideo",
]

AVATARS = [
    "General", "Truckers", "WifeOfDadBod", "ScaredCheckup", "DadBod",
    "ActiveMom", "RetiredCouple", "HealthConscious", "Skeptic",
]


def parse_ad_name(ad_name: str) -> dict[str, Optional[str]]:
    """Parse an ad name into structured dimensions.

    Args:
        ad_name: The ad name string (e.g., "B310_V1_Kidney_ProblemAware_LFS_RenalLymphaticClogged_General")

    Returns:
        Dict with keys: ad_code, variant, pain_point, awareness_level, ad_format, mechanism, avatar, symptoms
    """
    result: dict[str, Optional[str]] = {
        "ad_code": None,
        "variant": None,
        "pain_point": None,
        "awareness_level": None,
        "ad_format": None,
        "mechanism": None,
        "avatar": None,
        "symptoms": None,
        "raw_name": ad_name,
    }

    if not ad_name:
        return result

    # Split by underscore or spaces
    parts = re.split(r'[_\s]+', ad_name.strip())

    for part in parts:
        part_upper = part.upper()
        part_clean = part.strip()

        # Ad code pattern: B###
        if re.match(r'^B\d+$', part_clean, re.IGNORECASE):
            result["ad_code"] = part_clean.upper()
            continue

        # Variant pattern: V#
        if re.match(r'^V\d+$', part_clean, re.IGNORECASE):
            result["variant"] = part_clean.upper()
            continue

        # Pain point
        for pp in PAIN_POINTS:
            if part_clean.lower() == pp.lower():
                result["pain_point"] = pp
                break

        # Awareness level
        for al in AWARENESS_LEVELS:
            if part_clean.lower().replace(" ", "") == al.lower().replace(" ", ""):
                # Normalize to spaced form
                normalized = al.replace("Aware", " Aware") if "Aware" in al and " Aware" not in al else al
                result["awareness_level"] = normalized
                break

        # Ad format
        for af in AD_FORMATS:
            if part_upper == af.upper():
                result["ad_format"] = af
                break

        # Avatar
        for av in AVATARS:
            if part_clean.lower() == av.lower():
                result["avatar"] = av
                break

        # Mechanism (CamelCase multi-word that isn't matched above)
        if (not result.get("mechanism") and
            len(part_clean) > 6 and
            re.match(r'^[A-Z][a-z]+[A-Z]', part_clean) and
            part_clean not in AWARENESS_LEVELS and
            part_clean not in AD_FORMATS and
            part_clean not in AVATARS):
            # Convert CamelCase to spaced: RenalLymphaticClogged -> Renal Lymphatic Clogged
            mechanism = re.sub(r'([A-Z])', r' \1', part_clean).strip()
            result["mechanism"] = mechanism

    return result


def parse_ads_batch(ad_names: list[str]) -> list[dict[str, Optional[str]]]:
    """Parse a batch of ad names."""
    return [parse_ad_name(name) for name in ad_names]


def extract_dimensions_from_dataframe(df: "pd.DataFrame", name_column: str = "Ad Name") -> "pd.DataFrame":
    """Add parsed dimension columns to a DataFrame.

    Args:
        df: DataFrame with ad data
        name_column: Column containing ad names

    Returns:
        DataFrame with additional dimension columns
    """
    import pandas as pd

    if name_column not in df.columns:
        return df

    parsed = df[name_column].apply(lambda x: parse_ad_name(str(x)) if pd.notna(x) else {})
    parsed_df = pd.DataFrame(parsed.tolist())

    # Only add columns that don't already exist
    for col in parsed_df.columns:
        if col not in df.columns and col != "raw_name":
            df[col] = parsed_df[col]

    return df
