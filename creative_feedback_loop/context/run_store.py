"""Run store for creative feedback loop.

Stores and retrieves dashboard run data, and renders comparisons between runs.

BUG 3 FIX: render_comparison() was accessing a 'value' key that doesn't exist
in the dashboard data format. render_dashboard returns {"dimensions": [...],
"title": ...}. Now uses the correct keys and handles both old and new formats
gracefully with try/except.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_STORE_PATH = Path("output/creative_feedback_loop/runs")


class RunStore:
    """Persist and retrieve creative feedback loop run data."""

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or DEFAULT_STORE_PATH
        self.store_path.mkdir(parents=True, exist_ok=True)

    def save_run(self, run_id: str, data: dict[str, Any]) -> Path:
        """Save a run's dashboard data to disk."""
        data["run_id"] = run_id
        data["saved_at"] = datetime.utcnow().isoformat()
        path = self.store_path / f"{run_id}.json"
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        """Load a run's dashboard data from disk."""
        path = self.store_path / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def list_runs(self) -> list[str]:
        """List all saved run IDs, most recent first."""
        files = sorted(self.store_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [f.stem for f in files]

    def get_latest_run(self) -> dict[str, Any] | None:
        """Get the most recent run data."""
        runs = self.list_runs()
        if not runs:
            return None
        return self.load_run(runs[0])


def _render_comparison_pure(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Compare two dashboard runs and produce a diff.

    Both current and previous should be in the render_dashboard output format:
        {"title": str, "dimensions": [...], "summary_cards": [...]}

    Handles legacy formats gracefully — if previous data uses a different
    structure (e.g. flat "value" keys), it adapts.

    Args:
        current: Current run's dashboard data.
        previous: Previous run's dashboard data.

    Returns:
        Comparison dict with per-dimension deltas.
    """
    comparison = {
        "current_title": _safe_get_title(current),
        "previous_title": _safe_get_title(previous),
        "dimension_diffs": [],
    }

    current_dims = _extract_dimensions(current)
    previous_dims = _extract_dimensions(previous)

    # Build lookup of previous dimensions by name
    prev_lookup: dict[str, dict[str, Any]] = {}
    for dim in previous_dims:
        dim_name = dim.get("name", "")
        if dim_name:
            prev_lookup[dim_name] = dim

    # Compare each current dimension to previous
    for dim in current_dims:
        dim_name = dim.get("name", "Unknown")
        prev_dim = prev_lookup.get(dim_name)

        diff = _compare_dimension(dim_name, dim, prev_dim)
        comparison["dimension_diffs"].append(diff)

    return comparison


def _safe_get_title(data: dict[str, Any]) -> str:
    """Safely extract title from dashboard data, handling multiple formats."""
    if isinstance(data, dict):
        return data.get("title", data.get("name", "Untitled Run"))
    return "Untitled Run"


def _extract_dimensions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract dimensions list from dashboard data, handling multiple formats.

    Supports:
        - New format: {"dimensions": [...]}
        - Legacy format: {"value": ..., "values": [...]}  (single dimension)
        - Legacy flat: list of dicts with "name" keys
    """
    if not isinstance(data, dict):
        return []

    # New format: {"dimensions": [...]}
    dims = data.get("dimensions")
    if isinstance(dims, list):
        return dims

    # Legacy: data itself is a single dimension with "values" key
    try:
        if "values" in data and isinstance(data["values"], list):
            return [data]
    except (TypeError, KeyError):
        pass

    # Legacy: data has summary_cards from render_dashboard output
    cards = data.get("summary_cards")
    if isinstance(cards, list):
        # Reconstruct minimal dimensions from summary cards
        dims_from_cards = []
        for card in cards:
            dims_from_cards.append({
                "name": card.get("dimension", "Unknown"),
                "values": [{
                    "value": card.get("value", "Unknown"),
                    "winner_pct": card.get("winner_pct", 0),
                    "loser_pct": card.get("loser_pct", 0),
                    "avg_roas": card.get("avg_roas", 0),
                }],
            })
        return dims_from_cards

    return []


def _compare_dimension(
    name: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare a single dimension between two runs."""
    diff: dict[str, Any] = {
        "dimension": name,
        "is_new": previous is None,
        "value_changes": [],
    }

    if previous is None:
        # New dimension, no comparison possible
        diff["summary"] = f"NEW: {name} (not present in previous run)"
        return diff

    curr_values = {v.get("value", ""): v for v in current.get("values", [])}
    prev_values = {v.get("value", ""): v for v in previous.get("values", [])}

    all_keys = set(curr_values.keys()) | set(prev_values.keys())

    for key in sorted(all_keys):
        curr_v = curr_values.get(key, {})
        prev_v = prev_values.get(key, {})

        curr_delta = curr_v.get("winner_pct", 0) - curr_v.get("loser_pct", 0)
        prev_delta = prev_v.get("winner_pct", 0) - prev_v.get("loser_pct", 0)
        delta_change = curr_delta - prev_delta

        curr_roas = curr_v.get("avg_roas", 0)
        prev_roas = prev_v.get("avg_roas", 0)
        roas_change = curr_roas - prev_roas

        change = {
            "value": key,
            "current_delta": curr_delta,
            "previous_delta": prev_delta,
            "delta_change": delta_change,
            "current_roas": curr_roas,
            "previous_roas": prev_roas,
            "roas_change": roas_change,
            "is_new": key not in prev_values,
            "is_removed": key not in curr_values,
            "improved": delta_change > 0,
        }
        diff["value_changes"].append(change)

    # Sort by delta_change descending (biggest improvements first)
    diff["value_changes"].sort(key=lambda c: c["delta_change"], reverse=True)

    return diff


def format_comparison_text(comparison: dict[str, Any]) -> str:
    """Format a comparison as plain text for display."""
    lines = [
        f"Comparing: {comparison['current_title']} vs {comparison['previous_title']}",
        "=" * 60,
        "",
    ]

    for diff in comparison.get("dimension_diffs", []):
        dim = diff.get("dimension", "Unknown")
        if diff.get("is_new"):
            lines.append(f"  NEW: {dim}")
            continue

        lines.append(f"  {dim}:")
        for change in diff.get("value_changes", []):
            val = change.get("value", "?")
            dc = change.get("delta_change", 0)
            arrow = "↑" if dc > 0 else "↓" if dc < 0 else "→"
            status = "NEW" if change.get("is_new") else "REMOVED" if change.get("is_removed") else f"{arrow} {dc:+.0f}%"
            lines.append(f"    {val}: {status} (ROAS: {change.get('roas_change', 0):+.2f}x)")
        lines.append("")

    return "\n".join(lines)


# ── Backward-compatible module-level functions for app.py ─────────────────────

_store = RunStore()


def save_run(
    brand_name: str,
    csv_start_date: str | None = None,
    csv_end_date: str | None = None,
    classification_counts: dict | None = None,
    threshold_config: dict | None = None,
    dashboard_data: dict | None = None,
    top50_dashboard_data: dict | None = None,
    operator_priority: str = "",
    operator_notes: str = "",
    pattern_results: dict | None = None,
) -> Path:
    """Save a run to disk and return its path. Called by app.py."""
    run_id = f"{brand_name.lower().replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    data = {
        "brand_name": brand_name,
        "run_timestamp": datetime.utcnow().isoformat(),
        "csv_start_date": csv_start_date,
        "csv_end_date": csv_end_date,
        "classification_counts": classification_counts or {},
        "threshold_config": threshold_config or {},
        "dashboard_data": dashboard_data or {},
        "top50_dashboard_data": top50_dashboard_data or {},
        "operator_priority": operator_priority,
        "operator_notes": operator_notes,
        "pattern_results": pattern_results or {},
    }
    return _store.save_run(run_id, data)


def load_previous_run(brand_name: str) -> dict[str, Any] | None:
    """Load the most recent run for a brand. Called by app.py."""
    slug = brand_name.lower().replace(" ", "_")
    runs = _store.list_runs()
    for run_id in runs:
        if run_id.startswith(slug + "_"):
            return _store.load_run(run_id)
    return None


def render_comparison(  # type: ignore[misc]  # shadows module-level def
    current: dict[str, Any],
    previous: dict[str, Any],
    prev_date: str = "",
) -> None:
    """Compare two dashboard runs and render diff to Streamlit. Called by app.py."""
    import streamlit as st

    comparison = _render_comparison_pure(current, previous)

    title_current = comparison.get("current_title", "Current")
    title_previous = comparison.get("previous_title", f"Previous ({prev_date})" if prev_date else "Previous")

    st.markdown(
        f'<h3 style="color:#fafafa;">Run Comparison: {title_current} vs {title_previous}</h3>',
        unsafe_allow_html=True,
    )

    diffs = comparison.get("dimension_diffs", [])
    if not diffs:
        st.info("No comparable dimensions found in previous run.")
        return

    for diff in diffs:
        dim = diff.get("dimension", "Unknown")
        if diff.get("is_new"):
            st.markdown(f'<p style="color:#888; font-size:12px;">NEW dimension: {dim}</p>', unsafe_allow_html=True)
            continue
        changes = diff.get("value_changes", [])
        if not changes:
            continue
        with st.expander(f"{dim}", expanded=False):
            for change in changes:
                val = change.get("value", "?")
                dc = change.get("delta_change", 0)
                rc = change.get("roas_change", 0)
                if change.get("is_new"):
                    status = "NEW"
                    color = "#888"
                elif change.get("is_removed"):
                    status = "REMOVED"
                    color = "#888"
                else:
                    arrow = "↑" if dc > 0 else "↓" if dc < 0 else "→"
                    status = f"{arrow} {dc:+.0f}% delta | ROAS {rc:+.2f}x"
                    color = "#27ae60" if dc > 0 else "#c0392b"
                st.markdown(
                    f'<p style="color:{color}; font-size:13px; margin:2px 0;">• {val}: {status}</p>',
                    unsafe_allow_html=True,
                )


