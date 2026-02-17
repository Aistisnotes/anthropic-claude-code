"""Configuration loader with TOML support and environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "default.toml"


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config from TOML file, with environment variable overrides."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        config = tomllib.load(f)

    _apply_env_overrides(config)
    return config


def _apply_env_overrides(config: dict[str, Any]) -> None:
    """Override config values with META_ADS_ prefixed environment variables.

    Example: META_ADS_SCRAPER_MAX_ADS=200 overrides config["scraper"]["max_ads"]

    Uses greedy matching against actual config keys to handle underscored key names.
    """
    prefix = "META_ADS_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        remainder = key[len(prefix) :].lower()
        _set_nested_greedy(config, remainder, value)


def _set_nested_greedy(d: dict, remainder: str, value: str) -> None:
    """Set a value in a nested dict, greedily matching keys that may contain underscores."""
    if not remainder:
        return

    # Try matching current-level keys (longest match first to handle underscored keys)
    for config_key in sorted(d.keys(), key=len, reverse=True):
        prefix = config_key.lower()
        # Check if remainder starts with this key (followed by _ or end of string)
        if remainder == prefix:
            # Exact match - this is the leaf key, set the value
            existing = d[config_key]
            if isinstance(existing, dict):
                continue  # Can't override a section with a scalar
            d[config_key] = _cast_value(value, type(existing))
            return
        elif remainder.startswith(prefix + "_"):
            # This key matches as a prefix, recurse into subsection
            child = d[config_key]
            if isinstance(child, dict):
                sub_remainder = remainder[len(prefix) + 1 :]
                _set_nested_greedy(child, sub_remainder, value)
                return


def _cast_value(value: str, target_type: type) -> Any:
    if target_type is bool:
        return value.lower() in ("true", "1", "yes")
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    return value
