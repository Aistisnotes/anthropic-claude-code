"""Run storage for creative feedback loop.

Saves each analysis run as a JSON file:
  output/runs/{brand_slug}_{csv_start}_{csv_end}_{run_date}.json

Supports loading previous runs for comparison.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

RUNS_DIR = Path("output/runs")


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:40]


def _date_slug(dt_str: str) -> str:
    """Convert date string to slug format (YYYYMMDD)."""
    try:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
            try:
                dt = datetime.strptime(dt_str.strip(), fmt)
                return dt.strftime("%Y%m%d")
            except ValueError:
                continue
        # Fallback: just slugify it
        return re.sub(r"[^0-9]", "", dt_str)[:8]
    except Exception:
        return "unknown"


def save_run(
    brand_name: str,
    csv_start_date: str,
    csv_end_date: str,
    classification_counts: dict[str, int],
    threshold_config: dict[str, Any],
    dashboard_data: dict[str, Any],
    top50_dashboard_data: dict[str, Any],
    operator_priority: str = "General",
    operator_notes: str = "",
    top50_data: Optional[list[dict]] = None,
    pattern_results: Optional[dict] = None,
) -> Path:
    """Save a run to disk.

    Returns the path to the saved JSON file.
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    brand_slug = _slugify(brand_name)
    start_slug = _date_slug(csv_start_date)
    end_slug = _date_slug(csv_end_date)
    run_date = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"{brand_slug}_{start_slug}_{end_slug}_{run_date}.json"
    filepath = RUNS_DIR / filename

    run_data = {
        "brand_name": brand_name,
        "brand_slug": brand_slug,
        "run_timestamp": datetime.now().isoformat(),
        "csv_date_range": {
            "start": csv_start_date,
            "end": csv_end_date,
        },
        "classification_counts": classification_counts,
        "threshold_config": threshold_config,
        "dashboard_data": dashboard_data,
        "top50_dashboard_data": top50_dashboard_data,
        "operator_priority": operator_priority,
        "operator_notes": operator_notes,
        "top50_data": top50_data or [],
        "pattern_results": pattern_results,
    }

    with open(filepath, "w") as f:
        json.dump(run_data, f, indent=2, default=str)

    logger.info(f"Run saved: {filepath}")
    return filepath


def load_previous_run(brand_name: str) -> Optional[dict[str, Any]]:
    """Load the most recent previous run for a brand.

    Returns the run data dict, or None if no previous runs found.
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    brand_slug = _slugify(brand_name)

    matching = sorted(RUNS_DIR.glob(f"{brand_slug}_*.json"), reverse=True)

    for path in matching:
        try:
            with open(path) as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, KeyError):
            continue

    return None


def render_comparison(
    current_data: dict[str, list[dict]],
    previous_data: dict[str, list[dict]],
    previous_run_date: str,
) -> None:
    """Render comparison dashboard between current and previous run.

    Shows delta changes for each dimension value.
    """
    import streamlit as st

    st.markdown(f"### Comparison with Previous Run ({previous_run_date})")

    changes = []

    for dim_key, current_rows in current_data.items():
        prev_rows = previous_data.get(dim_key, [])
        prev_by_value = {r["value"]: r for r in prev_rows}

        for row in current_rows:
            val = row["value"]
            prev = prev_by_value.get(val)

            if prev:
                pct_change = row["pct_winners"] - prev["pct_winners"]
                if abs(pct_change) >= 3:  # Only show meaningful changes
                    changes.append({
                        "value": val,
                        "dimension": dim_key,
                        "prev_pct": prev["pct_winners"],
                        "curr_pct": row["pct_winners"],
                        "change": pct_change,
                    })
            else:
                if row["pct_winners"] > 0:
                    changes.append({
                        "value": val,
                        "dimension": dim_key,
                        "prev_pct": 0,
                        "curr_pct": row["pct_winners"],
                        "change": row["pct_winners"],
                        "is_new": True,
                    })

    if not changes:
        st.info("No significant changes from previous run.")
        return

    # Sort by absolute change
    changes.sort(key=lambda c: abs(c["change"]), reverse=True)

    html = '<div style="background:#1a1a2e; padding:16px; border-radius:8px; margin-bottom:20px;">'
    for change in changes[:20]:
        arrow = "↑" if change["change"] > 0 else "↓"
        color = "#4caf50" if change["change"] > 0 else "#ef5350"
        prefix = "+" if change["change"] > 0 else ""

        if change.get("is_new"):
            html += (
                f'<p style="color:#fafafa; margin:4px 0;">'
                f'<span style="color:#2196f3; font-weight:bold;">NEW</span> '
                f'{change["value"]}: {change["curr_pct"]:.0f}% of winners '
                f'<span style="color:#999;">(was 0% last run)</span></p>'
            )
        else:
            html += (
                f'<p style="color:#fafafa; margin:4px 0;">'
                f'{change["value"]}: {change["prev_pct"]:.0f}% → {change["curr_pct"]:.0f}% '
                f'<span style="color:{color}; font-weight:bold;">'
                f'({prefix}{change["change"]:.0f}% {arrow})</span></p>'
            )

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
