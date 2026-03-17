"""Ad naming convention parser for creative feedback loop.

Parses structured ad names like:
    B310_V1_LFS_LCC_W10_HY_- _Kidney_General(LCC)_RenalLymphaticClogged_UnclogRenalLymphatics_Problem Aware_LFStatic_L2_AM script kidney_Ideation_None_Kandy_COC

Field positions (underscore-separated):
    0: Batch (B310)
    1: Version (V1)
    2: Format code (LFS, VID, IMG, Static)
    3: Editor code (LCC, WM, HY, HN, MB, RS, AP, AL, MM)
    4: Week code (W5-W11)
    5: Second editor/country code
    6: Dash separator (-)
    7: Pain point (Kidney, Liver, Thyroid, Cholesterol, Lymph)
    8: Avatar (General(LCC), Truckers, WomenOver30, etc.)
    9: Mechanism UMP (problem — CamelCase compound)
    10: Mechanism UMS (solution — CamelCase compound)
    11: Awareness level (Problem Aware, Solution Aware, Most Aware, etc.)
    12: Ad format (LFStatic, Video, Static, Image)
    13: Concept level (L1, L2, L3)
    14+: Trailing tags — script ref, ad type, brand, suffix (ignored)

CRITICAL: awareness levels, editor codes, week codes, and campaign suffixes
must NEVER be extracted as mechanisms, pain points, or root causes.
"""

from __future__ import annotations

import re
from typing import Any


# ── Known value sets ──────────────────────────────────────────────────────────

AWARENESS_LEVELS = {
    "problem aware", "solution aware", "most aware", "product aware", "unaware",
}

AD_FORMAT_CODES = {
    "lfs": "Long Form Static",
    "vid": "Video",
    "lfstatic": "Long Form Static",
    "img": "Image",
    "static": "Static",
    "video": "Video",
    "image": "Image",
}

EDITOR_CODES = {"wm", "lcc", "hy", "hn", "mb", "rs", "ap", "al", "mm"}

WEEK_PATTERN = re.compile(r'^W\d{1,2}$', re.IGNORECASE)

IGNORE_SUFFIXES = {"coc", "kandy", "none", "ideation", "imitation"}

PAIN_POINTS = {"kidney", "liver", "thyroid", "cholesterol", "lymph"}

BATCH_PATTERN = re.compile(r'^B\d+$', re.IGNORECASE)
VERSION_PATTERN = re.compile(r'^V\d+$', re.IGNORECASE)
LEVEL_PATTERN = re.compile(r'^L\d+$', re.IGNORECASE)

# CamelCase compound words indicating a mechanism
CAMEL_CASE_PATTERN = re.compile(r'[a-z][A-Z]')


def parse_ad_name(ad_name: str) -> dict[str, Any]:
    """Parse an ad name into structured components.

    Returns a dict with keys:
        batch, version, format_code, ad_format, editor, week, pain_point,
        avatar, mechanism_ump, mechanism_ums, awareness_level,
        concept_level, root_cause_depth, raw_name, parsed

    If the name can't be parsed (manually named ads, short names), returns
    parsed=False with all fields set to empty/unknown.
    """
    result = _empty_result(ad_name)

    if not ad_name or not isinstance(ad_name, str):
        return result

    # Reject manually named ads (no underscores or too few segments)
    # These are things like "New 2 – copy_coc 2" or "Lymph - PDP – text #6"
    # First, check if it looks like a structured name (starts with batch code)
    cleaned = ad_name.strip()

    # Split on underscore — the primary delimiter
    parts = cleaned.split("_")

    # If fewer than 7 parts, it's likely a manual name — try partial extraction
    if len(parts) < 7:
        return _parse_unstructured(cleaned, result)

    # Check if first part is a batch code (B###)
    if not BATCH_PATTERN.match(parts[0].strip()):
        return _parse_unstructured(cleaned, result)

    result["parsed"] = True

    # ── Fixed-position fields ─────────────────────────────────────────────
    result["batch"] = parts[0].strip()

    if len(parts) > 1:
        result["version"] = parts[1].strip() if VERSION_PATTERN.match(parts[1].strip()) else ""

    # Scan remaining parts for known field types
    remaining = parts[2:]  # Skip batch and version

    # Strategy: walk through remaining parts and classify each one
    _classify_parts(remaining, result)

    # Infer root cause depth from mechanisms
    result["root_cause_depth"] = _infer_root_cause_depth(
        result.get("mechanism_ump", ""),
        result.get("mechanism_ums", ""),
    )

    return result


def _classify_parts(parts: list[str], result: dict[str, Any]) -> None:
    """Walk through parts and classify each into the correct field.

    Uses a combination of known value lookups and positional heuristics.
    """
    # We need to handle "Problem Aware" which spans TWO parts after split:
    # ["Problem", "Aware"] or ["Most", "Aware"] etc.
    # So first, rejoin parts and re-split carefully to preserve awareness levels.
    joined = "_".join(parts)

    # Replace known awareness levels with a placeholder to preserve them
    awareness_found = ""
    for level in sorted(AWARENESS_LEVELS, key=len, reverse=True):
        # Match case-insensitive, with underscores or spaces between words
        pattern = level.replace(" ", r"[\s_]+")
        m = re.search(pattern, joined, re.IGNORECASE)
        if m:
            awareness_found = level.title()
            joined = joined[:m.start()] + "_AWARENESS_PLACEHOLDER_" + joined[m.end():]
            break

    if awareness_found:
        result["awareness_level"] = awareness_found

    # Re-split
    tokens = [t.strip() for t in joined.split("_") if t.strip()]

    # Track what we've assigned — mechanisms are CamelCase compounds
    mechanisms_found = []
    format_found = False
    pain_point_found = False
    avatar_found = False

    for token in tokens:
        token_lower = token.lower()

        # Skip placeholder
        if token == "AWARENESS_PLACEHOLDER":
            continue

        # Skip dash separators
        if token in ("-", "- ", "–"):
            continue

        # Skip batch/version (already handled)
        if BATCH_PATTERN.match(token) or VERSION_PATTERN.match(token):
            continue

        # Editor codes — skip
        if token_lower in EDITOR_CODES:
            continue

        # Week codes — skip
        if WEEK_PATTERN.match(token):
            continue

        # Concept level (L1, L2, L3)
        if LEVEL_PATTERN.match(token):
            result["concept_level"] = token
            continue

        # Ignore suffixes (campaign/brand tags)
        if token_lower in IGNORE_SUFFIXES:
            continue

        # Ad format codes
        if token_lower in AD_FORMAT_CODES and not format_found:
            result["format_code"] = token
            result["ad_format"] = AD_FORMAT_CODES[token_lower]
            format_found = True
            continue

        # Pain points
        if token_lower in PAIN_POINTS and not pain_point_found:
            result["pain_point"] = token
            pain_point_found = True
            continue

        # Avatar patterns — contain parentheses or known avatar patterns
        if (("(" in token and ")" in token) or
            token_lower in {"truckers", "womenover30", "wifeofdadbod", "scaredcheckup"}) and not avatar_found:
            result["avatar"] = token
            avatar_found = True
            continue

        # CamelCase compound words → mechanisms (max 2: UMP then UMS)
        if CAMEL_CASE_PATTERN.search(token) and len(mechanisms_found) < 2:
            mechanisms_found.append(token)
            continue

        # Script references, ad type labels — skip remaining unknowns
        # (e.g. "AM script kidney", "Ideation", brand names)

    # Assign mechanisms in order: first = UMP (problem), second = UMS (solution)
    if len(mechanisms_found) >= 1:
        result["mechanism_ump"] = mechanisms_found[0]
    if len(mechanisms_found) >= 2:
        result["mechanism_ums"] = mechanisms_found[1]


def _parse_unstructured(name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Try partial extraction from unstructured/manual ad names.

    For names like "Lymph - PDP – text #6", extract what we can.
    """
    name_lower = name.lower()

    # Check for pain points anywhere in the name
    for pp in PAIN_POINTS:
        if pp in name_lower:
            result["pain_point"] = pp.title()
            break

    return result


def _infer_root_cause_depth(mechanism_ump: str, mechanism_ums: str) -> str:
    """Infer root cause depth from mechanism complexity.

    - cellular: mentions specific organ/system pathways (lymphatic, renal, hepatic)
    - molecular: mentions molecular processes
    - surface: vague or missing mechanism
    """
    combined = (mechanism_ump + " " + mechanism_ums).lower()

    if not combined.strip():
        return "surface"

    # Cellular-level indicators: organ systems, specific pathways
    cellular_keywords = [
        "lymphatic", "renal", "hepatic", "thyroid", "cholesterol",
        "vessel", "drainage", "clogged", "drain", "unclog",
        "tissue", "organ", "gland",
    ]

    # Molecular-level indicators
    molecular_keywords = [
        "molecular", "cellular", "receptor", "enzyme", "protein",
        "mitochondr", "oxidat", "inflamma", "cytokine", "hormone",
        "metaboli",
    ]

    has_molecular = any(kw in combined for kw in molecular_keywords)
    has_cellular = any(kw in combined for kw in cellular_keywords)

    if has_molecular:
        return "molecular"
    if has_cellular:
        return "cellular"
    return "surface"


def _empty_result(ad_name: str) -> dict[str, Any]:
    """Return an empty result dict."""
    return {
        "raw_name": ad_name,
        "parsed": False,
        "batch": "",
        "version": "",
        "format_code": "",
        "ad_format": "",
        "editor": "",
        "week": "",
        "pain_point": "",
        "avatar": "",
        "mechanism_ump": "",
        "mechanism_ums": "",
        "awareness_level": "",
        "concept_level": "",
        "root_cause_depth": "surface",
    }
