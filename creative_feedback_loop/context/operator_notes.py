"""Operator notes — simple text box for analysis notes.

After results are displayed, shows a single text box for operator notes.
Notes are saved with run data and shown on next run for the same brand.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import streamlit as st

logger = logging.getLogger(__name__)

RUNS_DIR = Path("output/runs")


def render_previous_notes(brand_slug: str) -> Optional[str]:
    """Show previous notes from the most recent run for this brand.

    Returns the previous notes text if found, None otherwise.
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    previous_runs = sorted(RUNS_DIR.glob(f"{brand_slug}_*.json"), reverse=True)

    for run_path in previous_runs:
        try:
            with open(run_path) as f:
                run_data = json.load(f)
            notes = run_data.get("operator_notes", "")
            if notes and notes.strip():
                run_date = run_data.get("run_timestamp", "unknown date")
                if isinstance(run_date, str) and len(run_date) > 10:
                    run_date = run_date[:10]
                st.markdown(
                    f'<div style="background:#1a2332; border-left:3px solid #4caf50; '
                    f'padding:12px 16px; margin-bottom:16px; border-radius:4px;">'
                    f'<p style="color:#4caf50; font-weight:600; margin-bottom:6px;">'
                    f'Notes from last analysis ({run_date}):</p>'
                    f'<p style="color:#fafafa;">{notes}</p></div>',
                    unsafe_allow_html=True,
                )
                return notes
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def render_notes_input() -> str:
    """Render the notes text box after results.

    Returns the current notes text (may be empty).
    """
    st.markdown("---")
    st.markdown('<p style="color:#fafafa; font-size:16px; font-weight:600;">Notes from this analysis (optional)</p>', unsafe_allow_html=True)

    notes = st.text_area(
        "Notes",
        placeholder="What did you learn? What are you testing next? What insights do you disagree with?",
        height=100,
        key="operator_notes_input",
        label_visibility="collapsed",
    )

    return notes


def save_notes_to_run(run_path: Path, notes: str) -> None:
    """Save operator notes to an existing run JSON file."""
    if not run_path.exists():
        return

    try:
        with open(run_path) as f:
            data = json.load(f)
        data["operator_notes"] = notes
        with open(run_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved notes to {run_path.name}")
    except Exception as e:
        logger.error(f"Failed to save notes: {e}")
