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


def render_dashboard(
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
            avg_roas = v.get("avg_roas", 0)
            icon, level, _ = _get_signal_level(delta, avg_roas)
            all_signals.append({
                "dimension": dim.get("name", "Unknown"),
                "value": v.get("value", "Unknown"),
                "winner_pct": v.get("winner_pct", 0),
                "loser_pct": v.get("loser_pct", 0),
                "delta": delta,
                "avg_roas": avg_roas,
                "icon": icon,
                "level": level,
                "is_positive": level in ("HIGH", "MEDIUM"),
            })

    # Sort all signals by delta descending
    all_signals.sort(key=lambda s: s["delta"], reverse=True)

    return {
        "title": title,
        "dimensions": dimensions,
        "summary_cards": summary_cards,
        "all_signals": all_signals,
    }


def _get_signal_level(delta: float, avg_roas: float) -> tuple[str, str, str]:
    """Determine signal level based on delta AND ROAS.

    Returns (icon, level, suffix) tuple.

    Rules:
        🟢 HIGH:     delta > +15% AND avg ROAS >= 1.0
        🟡 MEDIUM:   delta > +10% AND avg ROAS >= 1.0
                      OR delta > +15% but ROAS < 1.0 (caution — losing money)
        ⚪ BASELINE:  delta <= +10% (insufficient signal)
        🔴 AVOID:    negative delta OR avg ROAS < 0.8
    """
    if delta < 0 or avg_roas < 0.8:
        return "🔴", "AVOID", " (AVOID)"
    if delta > 15 and avg_roas >= 1.0:
        return "🟢", "HIGH", ""
    if (delta > 10 and avg_roas >= 1.0) or (delta > 15 and avg_roas < 1.0):
        return "🟡", "MEDIUM", " (CAUTION)"
    return "⚪", "BASELINE", ""


def _format_card(card: dict[str, Any]) -> dict[str, Any]:
    """Format a summary card for display.

    Signal color is determined by BOTH delta AND average ROAS:
        🟢 HIGH:     delta > +15% AND avg ROAS >= 1.0
        🟡 MEDIUM:   delta > +10% AND avg ROAS >= 1.0, or high delta but ROAS < 1.0
        ⚪ BASELINE:  delta <= +10%
        🔴 AVOID:    negative delta OR avg ROAS < 0.8
    """
    delta = card.get("delta", 0)
    avg_roas = card.get("avg_roas", 0)
    icon, level, suffix = _get_signal_level(delta, avg_roas)
    delta_str = f"+{delta:.0f}%" if delta > 0 else f"{delta:.0f}%"
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
        "level": level,
        "delta_str": delta_str,
        "display_text": display_text,
    }


def render_summary_text(data: dict[str, Any]) -> str:
    """Render a plain-text summary of the dashboard for CLI output."""
    result = render_dashboard(data)
    lines = [result["title"], "=" * len(result["title"]), ""]
    for card in result["summary_cards"]:
        lines.append(card["display_text"])
    return "\n".join(lines)
