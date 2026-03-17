"""Creative Feedback Loop — Streamlit output renderer.

Renders the full creative feedback loop output with distinct sections:
  1. Executive Summary (from pattern analysis — 1 paragraph only)
  2. Structured Splits Dashboard (signal cards)
  3. Opportunity Cards (with verified stats from dashboard data)
  4. Learnings (deduplicated, one section only — no hypotheses mixed in)
  5. Hypotheses (deduplicated, one section only)
  6. Run Comparison (only when previous run has DIFFERENT date range)

BUG 1 FIX: Content was displayed 3 times — raw Claude response, parsed cards,
and again in learnings/hypotheses. Now the raw response_text is NEVER rendered.
Only the parsed/structured output appears, each in its own dedicated section.

BUG 2 FIX: Run comparison showed "Section A vs Section A" with 0% deltas.
Now only shown when previous run has a different CSV date range. Title shows
actual dates: "This Week (Mar 5-11) vs Previous Run (Feb 26-Mar 4)".

BUG 3 FIX: Markdown ** artifacts in learnings. clean_markdown now strips
all ** sequences (balanced or unbalanced), leading/trailing *, and headers.

BUG 4 FIX: Dollar signs caused LaTeX rendering in Streamlit. All Claude
output text now converts $ to &#36; HTML entity before passing to
st.markdown(unsafe_allow_html=True).

BUG 5 FIX: "Winners: 0 | Losers: 0" on opportunity cards. When both counts
are 0, the stats line is suppressed — only score shown (or nothing).

BUG 6 FIX: Font sizes randomly changed mid-sentence from LaTeX $ and raw
markdown. All Claude output now uses consistent HTML wrapping with
fixed font-size:14px via _html_text().
"""

from __future__ import annotations

import re
from typing import Any

from creative_feedback_loop.analyzer.pattern_analyzer import (
    analyze_patterns,
    format_opportunity_card,
)
from creative_feedback_loop.dashboard.hypotheses import format_hypotheses
from creative_feedback_loop.dashboard.learnings import format_learnings
from creative_feedback_loop.dashboard.structured_splits import render_dashboard
from creative_feedback_loop.context.run_store import RunStore, render_comparison


# ── Text cleaning ─────────────────────────────────────────────────────────────

def clean_markdown(text: str) -> str:
    """Strip markdown formatting artifacts and escape $ for Streamlit.

    Removes: **, ##, #+, unbalanced *, leaked section headers.
    Escapes: $ → &#36; to prevent Streamlit LaTeX rendering.
    """
    if not text or not isinstance(text, str):
        return text or ""
    # Strip any run of 2+ asterisks (handles **, ***, balanced or not)
    cleaned = re.sub(r'\*{2,}', '', text)
    # Strip leading asterisks: "* text" → "text"
    cleaned = re.sub(r'^\*+\s*', '', cleaned)
    # Strip trailing asterisks: "text *" → "text"
    cleaned = re.sub(r'\*+\s*$', '', cleaned)
    # Strip markdown header markers: ##, ###, etc.
    cleaned = re.sub(r'#{1,6}\s*', '', cleaned)
    # Strip leading section headers leaked from Claude response
    cleaned = re.sub(
        r'^\s*(?:HYPOTHESES|LEARNINGS|OPPORTUNITIES|EXECUTIVE SUMMARY)\s*:\s*',
        '', cleaned, flags=re.IGNORECASE,
    )
    # Escape $ to prevent Streamlit LaTeX rendering (BUG 4)
    cleaned = cleaned.replace('$', '&#36;')
    # Collapse multiple spaces
    cleaned = re.sub(r'  +', ' ', cleaned).strip()
    return cleaned


def _html_text(text: str, font_size: int = 14) -> str:
    """Wrap text in consistent HTML for Streamlit st.markdown rendering.

    Ensures uniform font size and color. All Claude output MUST go through
    this to prevent LaTeX rendering and inconsistent fonts (BUG 6).
    """
    return (
        f'<p style="color:#fafafa; font-size:{font_size}px; '
        f'line-height:1.6; margin:0 0 8px 0;">{text}</p>'
    )


# ── Streamlit rendering ──────────────────────────────────────────────────────

def render_streamlit(
    pattern_results: dict[str, Any],
    dashboard_data: dict[str, Any] | None = None,
    *,
    brand_name: str = "",
    current_date_range: str = "",
) -> None:
    """Render the full creative feedback loop in Streamlit.

    This is the ONLY entry point for displaying pattern analysis results.
    The raw Claude response_text is NEVER displayed — only parsed sections.

    Args:
        pattern_results: Dict from Claude pattern analysis containing:
            - response_text: Raw Claude response (NOT displayed)
            - learnings: List of extracted learnings
            - hypotheses: List of extracted hypotheses
            - executive_summary: Optional summary text
        dashboard_data: Optional structured dashboard data with dimensions.
        brand_name: Brand name for run comparison lookup.
        current_date_range: CSV date range string (e.g. "Mar 5-11") for
            comparison logic.
    """
    import streamlit as st

    # ── 1. Executive Summary (1 paragraph ONLY) ──────────────────────────
    summary = pattern_results.get("executive_summary", "")
    if summary:
        st.subheader("Executive Summary")
        st.markdown(_html_text(clean_markdown(summary)), unsafe_allow_html=True)

    # ── 2. Structured Splits Dashboard ────────────────────────────────────
    if dashboard_data:
        st.subheader("Structured Splits")
        dashboard_result = render_dashboard(dashboard_data)
        for card in dashboard_result.get("summary_cards", []):
            st.markdown(
                _html_text(clean_markdown(card.get("display_text", ""))),
                unsafe_allow_html=True,
            )

    # ── 3. Opportunity Cards ──────────────────────────────────────────────
    # Parse opportunities from response — do NOT display raw response_text
    response_text = pattern_results.get("response_text", "")
    opportunities = analyze_patterns(response_text, dashboard_data)
    if opportunities:
        st.subheader("Opportunities")
        for i, opp in enumerate(opportunities, 1):
            title = clean_markdown(opp.get("title", "Untitled Opportunity"))
            opp_text = clean_markdown(opp.get("text", ""))
            score = opp.get("score", 0)
            stats_verified = opp.get("stats_verified", False)
            winner_count = opp.get("winner_count") or 0
            loser_count = opp.get("loser_count") or 0

            # BUG 5: Don't show "Winners: 0 | Losers: 0" — suppress zero stats
            if stats_verified and (winner_count > 0 or loser_count > 0):
                avg_roas = opp.get("avg_roas", 0.0) or 0.0
                total_spend = opp.get("total_spend", 0) or 0
                stats_parts = [
                    f"Winners: {winner_count}",
                    f"Losers: {loser_count}",
                    f"Avg ROAS: {avg_roas:.2f}x",
                ]
                if total_spend:
                    spend_str = f"&#36;{total_spend / 1000:.0f}k" if total_spend >= 1000 else f"&#36;{total_spend:.0f}"
                    stats_parts.append(f"Spend: {spend_str}")
                if score:
                    stats_parts.append(f"Score: {score}/100")
                stats_line = " | ".join(stats_parts)
            elif score:
                stats_line = f"Score: {score}/100"
            else:
                stats_line = ""

            card_html = (
                f'<div style="background:#1f2937; border:1px solid #374151; '
                f'border-radius:8px; padding:16px; margin:8px 0;">'
                f'<div style="color:#60a5fa; font-size:15px; font-weight:700; '
                f'margin-bottom:6px;">Opportunity #{i}: {title}</div>'
            )
            if stats_line:
                card_html += (
                    f'<div style="color:#9ca3af; font-size:13px; '
                    f'margin-bottom:8px;">{stats_line}</div>'
                )
            card_html += (
                f'<div style="color:#fafafa; font-size:14px; '
                f'line-height:1.6;">{opp_text}</div>'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

    # ── 4. Learnings (ONLY here — not in pattern insights) ────────────────
    raw_learnings = pattern_results.get("learnings", [])
    if raw_learnings:
        st.subheader("Learnings")
        formatted = format_learnings(raw_learnings, dashboard_data)
        for learning in formatted:
            idx = learning.get("index", "")
            display = clean_markdown(learning.get("display_text", ""))
            st.markdown(
                _html_text(f"{idx}. {display}"),
                unsafe_allow_html=True,
            )

    # ── 5. Hypotheses (ONLY here — not in pattern insights) ───────────────
    raw_hypotheses = pattern_results.get("hypotheses", [])
    if raw_hypotheses:
        st.subheader("Hypotheses")
        formatted = format_hypotheses(raw_hypotheses)
        for hyp in formatted:
            title = clean_markdown(hyp.get("title", ""))
            bullets = hyp.get("bullets", [])
            bullet_html = ""
            for b in bullets:
                label = clean_markdown(b.get("label", ""))
                value = clean_markdown(b.get("value", ""))
                bullet_html += (
                    f'<div style="margin:4px 0; padding:2px 0;">'
                    f'<span style="color:#9ca3af; font-weight:600;">'
                    f'{label}:</span> '
                    f'<span style="color:#e5e7eb;">{value}</span>'
                    f'</div>'
                )
            card_html = (
                f'<div style="background:#1f2937; border:1px solid #374151; '
                f'border-radius:8px; padding:16px; margin:8px 0;">'
                f'<div style="color:#60a5fa; font-size:14px; font-weight:700; '
                f'margin-bottom:8px;">{title}</div>'
                f'{bullet_html}'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

    # ── 6. Run Comparison (BUG 2: only show for different date ranges) ────
    _render_comparison(
        st, dashboard_data, brand_name, current_date_range,
    )


def _render_comparison(
    st: Any,
    dashboard_data: dict[str, Any] | None,
    brand_name: str,
    current_date_range: str,
) -> None:
    """Render week-over-week comparison if a previous run with different dates exists.

    BUG 2 FIX: Only shows comparison when previous run has a DIFFERENT CSV date
    range than the current run. If same dates or no previous run, shows an info
    message instead of stale "Section A vs Section A" with 0% deltas.
    """
    if not dashboard_data or not brand_name:
        return

    store = RunStore()
    runs = store.list_runs()

    # Find the most recent run for this brand with a DIFFERENT date range
    previous_run = None
    previous_date_range = ""
    for run_id in runs:
        run_data = store.load_run(run_id)
        if not run_data:
            continue
        run_brand = run_data.get("brand_name", "")
        run_dates = run_data.get("date_range", "")
        # Must be same brand, different date range
        if run_brand == brand_name and run_dates and run_dates != current_date_range:
            previous_run = run_data
            previous_date_range = run_dates
            break

    if not previous_run:
        st.info(
            "No previous run with different dates found for this brand. "
            "Run again with a new CSV to see week-over-week comparison."
        )
        return

    # Show comparison with actual date titles (not "Section A vs Section A")
    current_title = f"This Week ({current_date_range})" if current_date_range else "Current Run"
    previous_title = f"Previous Run ({previous_date_range})" if previous_date_range else "Previous Run"

    st.subheader(f"{current_title} vs {previous_title}")

    comparison = render_comparison(
        {**dashboard_data, "title": current_title},
        {**previous_run, "title": previous_title},
    )

    for diff in comparison.get("dimension_diffs", []):
        dim = diff.get("dimension", "Unknown")
        if diff.get("is_new"):
            st.markdown(
                _html_text(f"NEW: {dim} (not present in previous run)"),
                unsafe_allow_html=True,
            )
            continue

        changes = diff.get("value_changes", [])
        # Skip dimensions where all deltas are 0 (identical data)
        if all(c.get("delta_change", 0) == 0 for c in changes):
            continue

        st.markdown(
            f'<div style="color:#60a5fa; font-size:14px; font-weight:600; '
            f'margin:12px 0 4px 0;">{dim}</div>',
            unsafe_allow_html=True,
        )
        for change in changes:
            val = change.get("value", "?")
            dc = change.get("delta_change", 0)
            if dc == 0 and not change.get("is_new") and not change.get("is_removed"):
                continue  # Skip unchanged values
            arrow = "↑" if dc > 0 else "↓" if dc < 0 else "→"
            color = "#22c55e" if dc > 0 else "#ef4444" if dc < 0 else "#9ca3af"
            if change.get("is_new"):
                status = "NEW"
            elif change.get("is_removed"):
                status = "REMOVED"
            else:
                roas_change = change.get("roas_change", 0)
                status = f"{arrow} {dc:+.0f}% (ROAS: {roas_change:+.2f}x)"
            st.markdown(
                f'<p style="color:{color}; font-size:14px; line-height:1.6; '
                f'margin:2px 0 2px 16px;">{val}: {status}</p>',
                unsafe_allow_html=True,
            )


# ── Non-Streamlit rendering (CLI / plain text) ───────────────────────────────

def render_full_output(
    pattern_results: dict[str, Any],
    dashboard_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render the full creative feedback loop output as structured data.

    Args:
        pattern_results: Dict from Claude pattern analysis containing:
            - response_text: Raw Claude response (NOT displayed directly)
            - learnings: List of extracted learnings
            - hypotheses: List of extracted hypotheses
            - executive_summary: Optional summary text
        dashboard_data: Optional structured dashboard data with dimensions.

    Returns:
        Structured output dict with sections ready for display.
    """
    output: dict[str, Any] = {"sections": []}

    # ── 1. Executive Summary ──────────────────────────────────────────────
    summary = pattern_results.get("executive_summary", "")
    if summary:
        output["sections"].append({
            "type": "executive_summary",
            "title": "Executive Summary",
            "content": clean_markdown(summary),
        })

    # ── 2. Structured Splits Dashboard ────────────────────────────────────
    if dashboard_data:
        dashboard_result = render_dashboard(dashboard_data)
        output["sections"].append({
            "type": "dashboard",
            "title": "Structured Splits",
            "cards": dashboard_result.get("summary_cards", []),
            "all_signals": dashboard_result.get("all_signals", []),
        })

    # ── 3. Opportunity Cards (with verified stats from dashboard data) ────
    response_text = pattern_results.get("response_text", "")
    opportunities = analyze_patterns(response_text, dashboard_data)
    if opportunities:
        opp_cards = []
        for opp in opportunities:
            opp["text"] = clean_markdown(opp.get("text", ""))
            opp["title"] = clean_markdown(opp.get("title", ""))
            opp_cards.append(opp)
        output["sections"].append({
            "type": "opportunities",
            "title": "Opportunities",
            "cards": opp_cards,
        })

    # ── 4. Learnings (ONLY here — NOT in pattern insights) ────────────────
    raw_learnings = pattern_results.get("learnings", [])
    if raw_learnings:
        formatted = format_learnings(raw_learnings, dashboard_data)
        for learning in formatted:
            learning["display_text"] = clean_markdown(learning.get("display_text", ""))
            learning["observation"] = clean_markdown(learning.get("observation", ""))
        output["sections"].append({
            "type": "learnings",
            "title": "Learnings",
            "items": formatted,
        })

    # ── 5. Hypotheses (ONLY here — NOT in pattern insights) ───────────────
    raw_hypotheses = pattern_results.get("hypotheses", [])
    if raw_hypotheses:
        formatted = format_hypotheses(raw_hypotheses)
        for hyp in formatted:
            hyp["display_text"] = clean_markdown(hyp.get("display_text", ""))
            hyp["title"] = clean_markdown(hyp.get("title", ""))
            for bullet in hyp.get("bullets", []):
                bullet["value"] = clean_markdown(bullet.get("value", ""))
        output["sections"].append({
            "type": "hypotheses",
            "title": "Hypotheses",
            "items": formatted,
        })

    return output


def render_text_output(
    pattern_results: dict[str, Any],
    dashboard_data: dict[str, Any] | None = None,
) -> str:
    """Render the full output as plain text for CLI display."""
    result = render_full_output(pattern_results, dashboard_data)
    lines: list[str] = []

    for section in result.get("sections", []):
        section_type = section.get("type", "")
        title = section.get("title", "")

        lines.append("")
        lines.append(f"{'=' * 60}")
        lines.append(f"  {title}")
        lines.append(f"{'=' * 60}")
        lines.append("")

        if section_type == "executive_summary":
            lines.append(section.get("content", ""))

        elif section_type == "dashboard":
            for card in section.get("cards", []):
                lines.append(f"  {card.get('display_text', '')}")

        elif section_type == "opportunities":
            for i, opp in enumerate(section.get("cards", []), 1):
                title_text = opp.get("title", "Untitled")
                score = opp.get("score", 0)
                winner_count = opp.get("winner_count") or 0
                loser_count = opp.get("loser_count") or 0
                lines.append(f"  Opportunity #{i}: {title_text}")
                if opp.get("stats_verified") and (winner_count > 0 or loser_count > 0):
                    avg_roas = opp.get("avg_roas", 0.0) or 0.0
                    lines.append(f"    Winners: {winner_count} | Losers: {loser_count} | Avg ROAS: {avg_roas:.2f}x | Score: {score}/100")
                elif score:
                    lines.append(f"    Score: {score}/100")
                text = opp.get("text", "")
                if text:
                    for tline in text.split("\n"):
                        lines.append(f"    {tline}")
                lines.append("")

        elif section_type == "learnings":
            for item in section.get("items", []):
                idx = item.get("index", "")
                lines.append(f"  {idx}. {item.get('display_text', '')}")
                lines.append("")

        elif section_type == "hypotheses":
            for item in section.get("items", []):
                lines.append(f"  {item.get('display_text', '')}")
                lines.append(f"  {'-' * 40}")
                lines.append("")

    return "\n".join(lines)
