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
    """
    prefix = "META_ADS_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix) :].lower().split("_")
        _set_nested(config, parts, value)


def _set_nested(d: dict, keys: list[str], value: str) -> None:
    """Set a value in a nested dict using a list of keys."""
    for key in keys[:-1]:
        if key not in d:
            return
        d = d[key]
    if keys[-1] in d:
        existing = d[keys[-1]]
        d[keys[-1]] = _cast_value(value, type(existing))


def _cast_value(value: str, target_type: type) -> Any:
    if target_type is bool:
        return value.lower() in ("true", "1", "yes")
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    return value
