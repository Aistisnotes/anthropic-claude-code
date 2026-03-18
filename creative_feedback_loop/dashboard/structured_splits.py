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

import re
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
    result = _render_dashboard_pure(data)
    lines = [result["title"], "=" * len(result["title"]), ""]
    for card in result["summary_cards"]:
        lines.append(card["display_text"])
    return "\n".join(lines)


# ── Backward-compatible wrapper for app.py ────────────────────────────────────

def render_dashboard(
    ads_data_or_dict,
    title: str = "Dashboard",
    *,
    include_negative: bool = True,
) -> dict[str, Any]:
    """Wrapper for app.py: accepts (list, title) or (dict) and renders to Streamlit."""
    if isinstance(ads_data_or_dict, dict):
        return _render_dashboard_pure(ads_data_or_dict, include_negative=include_negative)

    import streamlit as st

    ads_data: list = ads_data_or_dict
    if not ads_data:
        st.info(f"No ads to display for {title}.")
        return {"title": title, "dimensions": [], "summary_cards": [], "all_signals": []}

    winners = [a for a in ads_data if a.get("status") == "winner"]
    losers = [a for a in ads_data if a.get("status") == "loser"]
    n_winners = len(winners) or 1
    n_losers = len(losers) or 1
    total_ads = len(ads_data)

    dimension_keys = [
        ("pain_point", "Pain Point"), ("root_cause", "Root Cause"),
        ("mechanism", "Mechanism"), ("ad_format", "Ad Format"),
        ("awareness_level", "Awareness Level"), ("hook_type", "Hook Type"),
        ("avatar", "Avatar"),
    ]

    # Tags that are campaign/editor metadata, not creative dimensions
    _GARBAGE_SUBSTRINGS = ("copy", "coc", "pdp", "text #", "kandy", "ideation")
    _CAMEL_RE = re.compile(r'^[A-Z][a-z]+(?:[A-Z][a-z]+)+$')

    def _is_valid_value(val: str, key: str) -> bool:
        if not val or len(val) < 2:
            return False
        vl = val.lower()
        if vl in ("none", "unknown", "nan", ""):
            return False
        if any(g in vl for g in _GARBAGE_SUBSTRINGS):
            return False
        # Mechanism must be CamelCase compound (no spaces, dashes, special chars)
        if key == "mechanism":
            return bool(_CAMEL_RE.match(val))
        return True

    def _extract_val_from_ext(ext: dict, key: str) -> str:
        """Extract a scalar value from an extraction dict for a given key.

        Handles nested dicts with key-specific field priority:
          avatar      → behavior (primary), impact (fallback)
          root_cause  → depth (primary), chain (fallback)
          mechanism   → ump (primary), ums (fallback)
          others      → depth → ump → behavior (generic fallback chain)

        Also normalises awareness_level values: replaces underscores with
        spaces and title-cases the result so "problem_aware" → "Problem Aware".
        """
        raw = ext.get(key, "")
        # Treat None the same as missing
        if raw is None:
            raw = ""
        val = raw or ""
        if isinstance(val, dict):
            if key == "avatar":
                val = val.get("behavior", "") or val.get("impact", "") or ""
            elif key == "root_cause":
                val = val.get("depth", "") or val.get("chain", "") or ""
            elif key == "mechanism":
                val = val.get("ump", "") or val.get("ums", "") or ""
            else:
                val = val.get("depth", "") or val.get("ump", "") or val.get("behavior", "") or ""
        val = str(val).strip()
        # Normalise awareness_level: "problem_aware" → "Problem Aware"
        if key == "awareness_level" and val:
            val = val.replace("_", " ").title()
        # Normalise avatar: uppercase content inside parentheses so
        # "General (lcc)" and "General (LCC)" resolve to the same value.
        if key == "avatar" and val:
            val = re.sub(r'\(([^)]+)\)', lambda m: '(' + m.group(1).upper() + ')', val)
        return val

    dimensions = []
    for key, label in dimension_keys:
        all_values: set[str] = set()
        for ad in ads_data:
            ext = ad.get("extraction") or ad.get("naming_extraction") or {}
            val = _extract_val_from_ext(ext, key)
            if _is_valid_value(val, key):
                all_values.add(val)
        if not all_values:
            continue
        values = []
        for val in all_values:
            w_count = sum(1 for a in winners if _get_ext_field(a, key) == val)
            l_count = sum(1 for a in losers if _get_ext_field(a, key) == val)
            # Use float() safely — roas may be string "0" in some rows
            roas_vals = []
            for a in ads_data:
                if _get_ext_field(a, key) != val:
                    continue
                try:
                    r = float(a.get("roas", 0) or 0)
                except (TypeError, ValueError):
                    r = 0.0
                if r > 0:
                    roas_vals.append(r)
            avg_roas = sum(roas_vals) / len(roas_vals) if roas_vals else 0.0
            spend_total = sum(float(a.get("spend", 0) or 0) for a in ads_data if _get_ext_field(a, key) == val)
            count = sum(1 for a in ads_data if _get_ext_field(a, key) == val)
            pct_all = round(count / total_ads * 100, 1) if total_ads > 0 else 0
            values.append({
                "value": val,
                "winner_pct": round(w_count / n_winners * 100, 1),
                "loser_pct": round(l_count / n_losers * 100, 1),
                "avg_roas": round(avg_roas, 2),
                "pct_all": pct_all,
                "spend": round(spend_total, 0),
                "count": count,
            })
        if values:
            dimensions.append({"name": label, "values": values})

    result = _render_dashboard_pure({"title": title, "dimensions": dimensions},
                                    include_negative=include_negative)

    st.markdown(f'<h3 style="color:#fafafa;">{title}</h3>', unsafe_allow_html=True)

    def _fmt_spend(v: float) -> str:
        if v >= 1000:
            return f"${v/1000:,.0f}k"
        return f"${v:,.0f}"

    for i, (dim_info, dim_label) in enumerate(
        [(d, d["name"]) for d in dimensions]
    ):
        with st.expander(dim_label, expanded=(i < 3)):
            sorted_values = sorted(dim_info["values"], key=lambda x: x.get("spend", 0), reverse=True)
            rows = ""
            for j, v in enumerate(sorted_values):
                bg = "#1e1e2e" if j % 2 == 0 else "#262730"
                roas = v.get("avg_roas", 0)
                roas_color = "#27ae60" if roas >= 1.0 else "#e74c3c" if roas > 0 else "#888"
                wp = v.get("winner_pct", 0)
                lp = v.get("loser_pct", 0)
                wp_color = "#27ae60" if wp > lp else "#e74c3c" if wp < lp else "#888"
                spend_str = _fmt_spend(v.get("spend", 0))
                rows += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:8px 12px; color:#fafafa; font-size:13px;">{v.get("value", "")}</td>'
                    f'<td style="padding:8px 12px; color:#ccc; text-align:right; font-size:13px;">{v.get("pct_all", 0):.1f}%</td>'
                    f'<td style="padding:8px 12px; color:{wp_color}; text-align:right; font-size:13px;">{wp:.0f}%</td>'
                    f'<td style="padding:8px 12px; color:#e74c3c; text-align:right; font-size:13px;">{lp:.0f}%</td>'
                    f'<td style="padding:8px 12px; color:{roas_color}; text-align:right; font-size:13px;">{roas:.2f}x</td>'
                    f'<td style="padding:8px 12px; color:#fafafa; text-align:right; font-size:13px;">{spend_str}</td>'
                    f'</tr>'
                )
            table_html = (
                f'<table style="width:100%; border-collapse:collapse; background:#1e1e2e; border-radius:8px; overflow:hidden; font-size:13px;">'
                f'<thead>'
                f'<tr style="background:#2d2d3d;">'
                f'<th style="color:#fafafa; padding:8px 12px; text-align:left;">Value</th>'
                f'<th style="color:#fafafa; padding:8px 12px; text-align:right;">% All</th>'
                f'<th style="color:#fafafa; padding:8px 12px; text-align:right;">% Winners</th>'
                f'<th style="color:#fafafa; padding:8px 12px; text-align:right;">% Losers</th>'
                f'<th style="color:#fafafa; padding:8px 12px; text-align:right;">Avg ROAS</th>'
                f'<th style="color:#fafafa; padding:8px 12px; text-align:right;">Spend</th>'
                f'</tr>'
                f'</thead>'
                f'<tbody>{rows}</tbody>'
                f'</table>'
            )
            st.markdown(table_html, unsafe_allow_html=True)

    return result


def _get_ext_field(ad: dict, key: str) -> str:
    ext = ad.get("extraction") or ad.get("naming_extraction") or {}
    raw = ext.get(key, "")
    if raw is None:
        raw = ""
    val = raw or ""
    if isinstance(val, dict):
        if key == "avatar":
            val = val.get("behavior", "") or val.get("impact", "") or ""
        elif key == "root_cause":
            val = val.get("depth", "") or val.get("chain", "") or ""
        elif key == "mechanism":
            val = val.get("ump", "") or val.get("ums", "") or ""
        else:
            val = val.get("depth", "") or val.get("ump", "") or val.get("behavior", "") or ""
    val = str(val).strip()
    # Normalise awareness_level to match all_values collection
    if key == "awareness_level" and val:
        val = val.replace("_", " ").title()
    # Normalise avatar parenthetical acronyms to uppercase
    if key == "avatar" and val:
        val = re.sub(r'\(([^)]+)\)', lambda m: '(' + m.group(1).upper() + ')', val)
    return val
