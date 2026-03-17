"""Structured splits dashboard for creative feedback loop.

Renders dimension-level summary cards showing the BEST signal per dimension
(highest positive delta = what winners do that losers don't), sorted with
green/positive cards first, red/negative cards last.

BUG 1 FIX: Previously showed only the WORST (most negative) pattern per
dimension. Now correctly finds the value with the HIGHEST POSITIVE delta
(winner% - loser%) for each dimension. If no positive delta exists, shows the
least negative one with a warning.
"""

from __future__ import annotations

from typing import Any


def compute_dimension_summary(dimension: dict[str, Any]) -> dict[str, Any]:
    """Compute the best signal for a single dimension.

    For each dimension, find the value with the HIGHEST POSITIVE delta
    (winner% - loser%). If no positive delta exists, pick the least negative
    one and flag it as a warning.

    Args:
        dimension: Dict with "name" and "values" list. Each value has:
            - value: str (the label, e.g. "Kidney")
            - winner_pct: float (percentage of winners with this value)
            - loser_pct: float (percentage of losers with this value)
            - avg_roas: float (average ROAS for ads with this value)

    Returns:
        Summary dict with the best signal for this dimension.
    """
    name = dimension.get("name", "Unknown")
    values = dimension.get("values", [])

    if not values:
        return {
            "dimension": name,
            "value": "No data",
            "winner_pct": 0,
            "loser_pct": 0,
            "delta": 0,
            "avg_roas": 0,
            "is_positive": False,
            "is_warning": True,
        }

    # Calculate delta for each value: winner% - loser%
    for v in values:
        v["delta"] = v.get("winner_pct", 0) - v.get("loser_pct", 0)

    # Sort by delta descending — best (most positive) first
    sorted_values = sorted(values, key=lambda v: v["delta"], reverse=True)

    best = sorted_values[0]
    is_positive = best["delta"] > 0

    return {
        "dimension": name,
        "value": best.get("value", "Unknown"),
        "winner_pct": best.get("winner_pct", 0),
        "loser_pct": best.get("loser_pct", 0),
        "delta": best["delta"],
        "avg_roas": best.get("avg_roas", 0),
        "is_positive": is_positive,
        "is_warning": not is_positive,
    }


def _render_dashboard_pure(
    data: dict[str, Any],
    *,
    include_negative: bool = True,
) -> dict[str, Any]:
    """Render the structured splits dashboard.

    Computes a summary card for each dimension showing the BEST signal
    (highest positive delta). Cards are sorted: green (positive) first,
    then red (negative) last.

    Args:
        data: Dashboard data with structure:
            {
                "title": str,
                "dimensions": [
                    {
                        "name": "Pain Point",
                        "values": [
                            {"value": "Kidney", "winner_pct": 55, "loser_pct": 15, "avg_roas": 1.45},
                            {"value": "Thyroid", "winner_pct": 8, "loser_pct": 20, "avg_roas": 0.73},
                        ]
                    },
                    ...
                ]
            }
        include_negative: If True, also include the worst signal per dimension
            as an "AVOID" card after all positive cards.

    Returns:
        Dict with "title", "dimensions" (original), and "summary_cards" list.
    """
    title = data.get("title", "Creative Feedback Loop")
    dimensions = data.get("dimensions", [])

    # Compute best signal per dimension
    summaries = [compute_dimension_summary(dim) for dim in dimensions]

    # Sort: positive deltas first (descending), then negative (descending)
    positive_cards = sorted(
        [s for s in summaries if s["is_positive"]],
        key=lambda s: s["delta"],
        reverse=True,
    )
    negative_cards = sorted(
        [s for s in summaries if not s["is_positive"]],
        key=lambda s: s["delta"],
        reverse=True,
    )

    # Build ordered card list: green first, red last
    summary_cards = []
    for card in positive_cards:
        summary_cards.append(_format_card(card))
    if include_negative:
        for card in negative_cards:
            summary_cards.append(_format_card(card))

    # Also collect ALL values across ALL dimensions for full detail view
    all_signals = []
    for dim in dimensions:
        for v in dim.get("values", []):
            delta = v.get("winner_pct", 0) - v.get("loser_pct", 0)
            all_signals.append({
                "dimension": dim.get("name", "Unknown"),
                "value": v.get("value", "Unknown"),
                "winner_pct": v.get("winner_pct", 0),
                "loser_pct": v.get("loser_pct", 0),
                "delta": delta,
                "avg_roas": v.get("avg_roas", 0),
                "is_positive": delta > 0,
            })

    # Sort all signals by delta descending
    all_signals.sort(key=lambda s: s["delta"], reverse=True)

    return {
        "title": title,
        "dimensions": dimensions,
        "summary_cards": summary_cards,
        "all_signals": all_signals,
    }


def _format_card(card: dict[str, Any]) -> dict[str, Any]:
    """Format a summary card for display.

    Produces output like:
        🟢 Pain Point: Kidney | Winners: 55% | Losers: 15% | Delta: +40% | 1.45x ROAS
        🔴 Pain Point: Thyroid | Winners: 8% | Losers: 20% | Delta: -12% | 0.73x ROAS (AVOID)
    """
    is_positive = card.get("is_positive", False)
    icon = "🟢" if is_positive else "🔴"
    delta = card.get("delta", 0)
    delta_str = f"+{delta:.0f}%" if delta > 0 else f"{delta:.0f}%"
    suffix = "" if is_positive else " (AVOID)"
    warning = " ⚠️ No positive signal found" if card.get("is_warning") else ""

    display_text = (
        f"{icon} {card['dimension']}: {card['value']} | "
        f"Winners: {card['winner_pct']:.0f}% | "
        f"Losers: {card['loser_pct']:.0f}% | "
        f"Delta: {delta_str} | "
        f"{card['avg_roas']:.2f}x ROAS{suffix}{warning}"
    )

    return {
        **card,
        "icon": icon,
        "delta_str": delta_str,
        "display_text": display_text,
    }


def render_summary_text(data: dict[str, Any]) -> str:
    """Render a plain-text summary of the dashboard for CLI output."""
    result = _render_dashboard_pure(data)
    lines = [result["title"], "=" * len(result["title"]), ""]
    for card in result["summary_cards"]:
        lines.append(card["display_text"])
    return "\n".join(lines)


# ── Backward-compatible wrapper for app.py ────────────────────────────────────

def render_dashboard(  # type: ignore[misc]  # shadows module-level def intentionally
    ads_data_or_dict,
    title: str = "Dashboard",
    *,
    include_negative: bool = True,
) -> dict[str, Any]:
    """Overloaded render_dashboard for app.py compatibility.

    app.py calls render_dashboard(ads_data: list, title: str) and expects:
    - Streamlit cards rendered to the page
    - A dashboard_data dict returned (with "dimensions", "summary_cards", etc.)

    If passed a list, converts it to the dimension structure expected by the
    new pure-computation render_dashboard, renders cards via Streamlit, and
    returns the result.

    If passed a dict (new-style call), delegates directly to the pure function.
    """
    # If already a dict (new-style call), delegate to pure function
    if isinstance(ads_data_or_dict, dict):
        return _render_dashboard_pure(ads_data_or_dict, include_negative=include_negative)

    import streamlit as st

    ads_data: list = ads_data_or_dict
    if not ads_data:
        st.info(f"No ads to display for {title}.")
        return {"title": title, "dimensions": [], "summary_cards": [], "all_signals": []}

    # Build dimension structure from flat ad list
    winners = [a for a in ads_data if a.get("status") == "winner"]
    losers = [a for a in ads_data if a.get("status") == "loser"]
    n_winners = len(winners) or 1
    n_losers = len(losers) or 1

    dimension_keys = [
        ("pain_point", "Pain Point"),
        ("root_cause", "Root Cause"),
        ("mechanism", "Mechanism"),
        ("ad_format", "Ad Format"),
        ("awareness_level", "Awareness Level"),
        ("hook_type", "Hook Type"),
    ]

    dimensions = []
    for key, label in dimension_keys:
        # Collect all distinct values across winners and losers
        all_values: set[str] = set()
        for ad in ads_data:
            ext = ad.get("extraction") or ad.get("naming_extraction") or {}
            val = ext.get(key, "") or ""
            if isinstance(val, dict):
                val = val.get("depth", "") or val.get("ump", "") or ""
            val = str(val).strip()
            if val and val.lower() not in ("none", "unknown", "nan", ""):
                all_values.add(val)

        if not all_values:
            continue

        values = []
        for val in all_values:
            w_count = sum(
                1 for a in winners
                if _get_ext_field(a, key) == val
            )
            l_count = sum(
                1 for a in losers
                if _get_ext_field(a, key) == val
            )
            roas_vals = [
                float(a.get("roas", 0))
                for a in ads_data
                if _get_ext_field(a, key) == val and float(a.get("roas", 0)) > 0
            ]
            avg_roas = sum(roas_vals) / len(roas_vals) if roas_vals else 0.0
            values.append({
                "value": val,
                "winner_pct": round(w_count / n_winners * 100, 1),
                "loser_pct": round(l_count / n_losers * 100, 1),
                "avg_roas": round(avg_roas, 2),
            })

        if values:
            dimensions.append({"name": label, "values": values})

    data = {"title": title, "dimensions": dimensions}
    result = _render_dashboard_pure(data, include_negative=include_negative)

    # Render to Streamlit
    st.markdown(f'<h3 style="color:#fafafa;">{title}</h3>', unsafe_allow_html=True)
    for card in result.get("summary_cards", []):
        color = "#27ae60" if card.get("is_positive") else "#c0392b"
        st.markdown(
            f'<div style="background:#1a1a2e; border-left:3px solid {color}; '
            f'padding:10px 14px; margin-bottom:8px; border-radius:0 6px 6px 0;">'
            f'<p style="color:#fafafa; margin:0; font-size:13px;">{card["display_text"]}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

    return result


def _get_ext_field(ad: dict, key: str) -> str:
    """Extract a named field from an ad's extraction dict."""
    ext = ad.get("extraction") or ad.get("naming_extraction") or {}
    val = ext.get(key, "") or ""
    if isinstance(val, dict):
        val = val.get("depth", "") or val.get("ump", "") or ""
    return str(val).strip()
