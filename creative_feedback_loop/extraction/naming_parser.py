"""Parse ad naming conventions to extract structured components.

Handles naming patterns like:
  B310_V1_LFS_LCC_W10_HY_-_Kidney_General(LCC)_RenalLymphaticClogged_UnclogRenalLymphatics_Problem Aware_LFStatic_L2

Extracts: pain point, mechanism UMP/UMS, avatar, awareness level, ad format, concept level, etc.
This is the FALLBACK when no ClickUp script is available — works for ALL ads.
"""

from __future__ import annotations

import re
from typing import Any


# Known pain points to match in naming
PAIN_POINTS = [
    "kidney", "liver", "thyroid", "cholesterol", "blood sugar", "blood pressure",
    "weight", "fat", "belly", "gut", "digestion", "joint", "knee", "back",
    "brain", "memory", "sleep", "energy", "fatigue", "skin", "hair", "nail",
    "heart", "prostate", "bladder", "lymph", "immune", "inflammation",
    "diabetes", "aging", "detox", "hormone", "estrogen", "testosterone",
    "cortisol", "stress", "anxiety", "vision", "eye", "hearing", "ear",
    "bone", "muscle", "metabolism", "cellular",
]

# Known ad formats in naming
FORMAT_MAP = {
    "ugc": "UGC",
    "ai": "AI",
    "vsl": "VSL",
    "lfstatic": "Long Form Static",
    "lfs": "Long Form Static",
    "sfv": "Short Form Video",
    "sfstatic": "Short Form Static",
    "image": "Image",
    "carousel": "Carousel",
    "longform": "Long Form",
    "shortform": "Short Form",
    "static": "Static",
    "video": "Video",
}

# Known awareness levels
AWARENESS_MAP = {
    "unaware": "unaware",
    "problem aware": "problem_aware",
    "problemaware": "problem_aware",
    "solution aware": "solution_aware",
    "solutionaware": "solution_aware",
    "product aware": "product_aware",
    "productaware": "product_aware",
    "most aware": "most_aware",
    "mostaware": "most_aware",
}

# Known lead types in naming
LEAD_TYPE_MAP = {
    "hy": "story",        # hypothesis / story
    "st": "story",
    "ps": "problem-solution",
    "tm": "testimonial",
    "ed": "educational",
    "nw": "news",
    "cr": "curiosity",
    "fr": "fear",
}


_STRUCTURED_PATTERN = re.compile(r"B\d{2,4}_V\d+", re.IGNORECASE)


def parse_ad_naming(ad_name: str) -> dict[str, Any]:
    """Parse an ad name string to extract structured components.

    Only parses names that follow the structured Sculptique convention:
      B###_V#_... (e.g. B310_V1_LFS_...)

    Unstructured names like "New 2 – copy_coc" or "Lymph - PDP – text #6"
    return empty immediately to avoid garbage extractions.

    Args:
        ad_name: The ad name/ID string, typically underscore-delimited.

    Returns:
        Dict matching the extraction schema with whatever can be parsed.
    """
    if not ad_name or not ad_name.strip():
        return _empty()

    name = ad_name.strip()

    # Only parse structured names matching B###_V# pattern
    if not _STRUCTURED_PATTERN.search(name):
        return _empty()

    name_lower = name.lower()

    # Split by underscores and other delimiters
    parts = re.split(r"[_\-/]+", name)
    parts_lower = [p.lower().strip() for p in parts]

    result = _empty()

    # ── Pain Point ─────────────────────────────────────────────────────────
    for pain in PAIN_POINTS:
        if pain in name_lower:
            result["pain_point"] = pain.title()
            break

    # ── Ad Format ──────────────────────────────────────────────────────────
    for part in parts_lower:
        if part in FORMAT_MAP:
            result["ad_format"] = FORMAT_MAP[part]
            break
    # Also check combined parts
    if not result["ad_format"]:
        for fmt_key, fmt_val in FORMAT_MAP.items():
            if fmt_key in name_lower:
                result["ad_format"] = fmt_val
                break

    # ── Awareness Level ────────────────────────────────────────────────────
    for aw_key, aw_val in AWARENESS_MAP.items():
        if aw_key in name_lower:
            result["awareness_level"] = aw_val
            break

    # ── Mechanism UMP/UMS ──────────────────────────────────────────────────
    # Look for CamelCase segments that look like mechanism descriptions
    # Skip parts that contain parentheses (avatar markers like General(LCC))
    # Skip known non-mechanism parts
    _skip_words = {"general", "problem", "solution", "product", "aware", "unaware"}
    camel_parts = [
        p for p in parts
        if len(p) > 10
        and any(c.isupper() for c in p[1:])
        and "(" not in p
        and p.lower().split("(")[0].strip() not in _skip_words
    ]
    if len(camel_parts) >= 2:
        result["mechanism"]["ump"] = _camel_to_words(camel_parts[0])
        result["mechanism"]["ums"] = _camel_to_words(camel_parts[1])
    elif len(camel_parts) == 1:
        result["mechanism"]["ump"] = _camel_to_words(camel_parts[0])

    # ── Avatar from parenthetical ──────────────────────────────────────────
    paren_match = re.findall(r"\(([^)]+)\)", name)
    for match in paren_match:
        if match.upper() != match:  # Not just an acronym
            result["avatar"]["behavior"] = match
        elif len(match) <= 5:
            # Short acronym like (LCC) — store as avatar type
            result["avatar"]["behavior"] = f"General ({match})"

    # Check for "General(XXX)" pattern
    general_match = re.search(r"General\(([^)]+)\)", name, re.IGNORECASE)
    if general_match:
        result["avatar"]["behavior"] = f"General ({general_match.group(1)})"

    # ── Lead Type ──────────────────────────────────────────────────────────
    for part in parts_lower:
        if part in LEAD_TYPE_MAP:
            result["lead_type"] = LEAD_TYPE_MAP[part]
            break

    # ── Root Cause from mechanism ──────────────────────────────────────────
    if result["mechanism"]["ump"]:
        # Infer root cause depth from mechanism description
        ump_lower = result["mechanism"]["ump"].lower()
        if any(w in ump_lower for w in ["molecular", "cellular", "mitochondr", "dna", "rna", "receptor"]):
            result["root_cause"]["depth"] = "molecular"
        elif any(w in ump_lower for w in ["cell", "tissue", "vessel", "lymph", "organ"]):
            result["root_cause"]["depth"] = "cellular"
        else:
            result["root_cause"]["depth"] = "surface"

        result["root_cause"]["chain"] = result["mechanism"]["ump"]

    # ── Concept Level (L1, L2, etc.) ────────────────────────────────────────
    level_match = re.search(r"\bL(\d+)\b", name)
    if level_match:
        result["_concept_level"] = f"L{level_match.group(1)}"

    # ── Version (V1, V2, etc.) ─────────────────────────────────────────────
    version_match = re.search(r"\bV(\d+)\b", name, re.IGNORECASE)
    if version_match:
        result["_version"] = f"V{version_match.group(1)}"

    return result


def _camel_to_words(s: str) -> str:
    """Convert CamelCase to space-separated words."""
    result = re.sub(r"([A-Z])", r" \1", s)
    return result.strip()


def _empty() -> dict[str, Any]:
    """Return empty extraction dict."""
    return {
        "hooks": [],
        "body_copy_summary": "",
        "pain_point": "",
        "symptoms": [],
        "root_cause": {"depth": "", "chain": ""},
        "mechanism": {"ump": "", "ums": ""},
        "avatar": {
            "behavior": "",
            "impact": "",
            "root_cause_connection": "",
            "why_previous_failed": "",
        },
        "ad_format": "",
        "awareness_level": "",
        "emotional_triggers": [],
        "language_patterns": [],
        "lead_type": "",
        "cta_type": "",
        "hook_type": "",
    }


def merge_extractions(naming_extraction: dict, claude_extraction: dict) -> dict:
    """Merge naming-based extraction with Claude extraction.

    Claude extraction takes priority. Naming fills gaps.
    """
    result = {}
    for key in naming_extraction:
        naming_val = naming_extraction.get(key)
        claude_val = claude_extraction.get(key)

        if isinstance(naming_val, dict):
            merged_dict = {}
            for subkey in naming_val:
                cv = (claude_val or {}).get(subkey, "")
                nv = naming_val.get(subkey, "")
                merged_dict[subkey] = cv if cv else nv
            result[key] = merged_dict
        elif isinstance(naming_val, list):
            # Claude list takes priority if non-empty
            result[key] = claude_val if claude_val else naming_val
        else:
            result[key] = claude_val if claude_val else naming_val

    return result
