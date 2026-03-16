"""Streamlit UI for Creative Feedback Loop Analyzer.

Implements all 7 fixes with proper UX:
- FIX 1: CSV aggregation happens automatically
- FIX 2: Separate winner/loser threshold inputs
- FIX 3: ROAS=0 shown as loser
- FIX 4: Date range filters CSV, not ClickUp
- FIX 5: Top 50 as separate section
- FIX 6: Novelty filter in pattern display
- FIX 7: Aggregation stats shown in pipeline log
"""

from __future__ import annotations

import logging
import io
from pathlib import Path

import streamlit as st
import pandas as pd

from creative_feedback_loop.csv_aggregator import load_and_aggregate_csv
from creative_feedback_loop.classifier import ThresholdConfig, classify_ads
from creative_feedback_loop.clickup_matcher import ClickUpTask, match_ads_to_clickup
from creative_feedback_loop.top50 import build_top50
from creative_feedback_loop.novelty_filter import compute_novelty
from creative_feedback_loop.pipeline import run_pipeline, PipelineResult

logger = logging.getLogger(__name__)


def render_creative_feedback_loop():
    """Render the Creative Feedback Loop Analyzer page in Streamlit."""
    st.title("Creative Feedback Loop Analyzer")
    st.caption(
        "Upload a Meta Ads Manager CSV export. Ads are aggregated by name, "
        "classified as winners/losers, and matched to ClickUp tasks."
    )

    # ── Sidebar: Upload & Config ──
    with st.sidebar:
        st.header("Configuration")

        # CSV Upload
        uploaded_file = st.file_uploader(
            "Meta Ads Manager CSV",
            type=["csv"],
            help="Export from Ads Manager — one row per ad per ad set is fine, we aggregate automatically.",
        )

        st.divider()

        # FIX 4: Optional date range (filters CSV, NOT ClickUp)
        st.subheader("Date Range (Optional)")
        st.caption(
            "Filter rows within the CSV by date. Leave blank to use all CSV data. "
            "Only works if your CSV has a date column (Day, Reporting starts, etc.)."
        )
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            date_start = st.date_input("Start date", value=None, key="cfl_date_start")
        with col_d2:
            date_end = st.date_input("End date", value=None, key="cfl_date_end")

        st.divider()

        # FIX 2: Separate winner and loser thresholds
        st.subheader("Winner Criteria")
        st.caption("Ads meeting BOTH conditions are classified as winners.")
        winner_roas = st.number_input(
            "ROAS above",
            min_value=0.0,
            value=1.0,
            step=0.1,
            key="cfl_winner_roas",
            help="Minimum ROAS to be a winner (default: 1.0 = breakeven)",
        )
        winner_spend = st.number_input(
            "AND spend above ($)",
            min_value=0.0,
            value=50.0,
            step=10.0,
            key="cfl_winner_spend",
            help="Minimum aggregated spend to qualify (default: $50)",
        )

        st.divider()

        st.subheader("Loser Criteria")
        st.caption("Ads meeting BOTH conditions are classified as losers. ROAS = 0 with spend = loser.")
        loser_roas = st.number_input(
            "ROAS below",
            min_value=0.0,
            value=1.0,
            step=0.1,
            key="cfl_loser_roas",
            help="Maximum ROAS to be a loser (default: 1.0 = below breakeven)",
        )
        loser_spend = st.number_input(
            "AND spend above ($)",
            min_value=0.0,
            value=50.0,
            step=10.0,
            key="cfl_loser_spend",
            help="Minimum aggregated spend to qualify (default: $50)",
        )

        st.divider()

        # ClickUp tasks (optional JSON upload)
        clickup_file = st.file_uploader(
            "ClickUp Tasks JSON (optional)",
            type=["json"],
            help="Export from ClickUp. Each task needs 'id', 'name', and optionally 'status', 'script'.",
        )

        run_btn = st.button("Run Analysis", type="primary", use_container_width=True)

    # ── Main area ──
    if not uploaded_file:
        st.info("Upload a Meta Ads Manager CSV in the sidebar to begin.")
        return

    if not run_btn and "cfl_result" not in st.session_state:
        st.info("Configure thresholds in the sidebar, then click **Run Analysis**.")
        return

    if run_btn:
        _run_analysis(
            uploaded_file, clickup_file,
            ThresholdConfig(
                winner_roas_min=winner_roas,
                winner_spend_min=winner_spend,
                loser_roas_max=loser_roas,
                loser_spend_min=loser_spend,
            ),
            str(date_start) if date_start else None,
            str(date_end) if date_end else None,
        )

    if "cfl_result" in st.session_state:
        _render_results(st.session_state["cfl_result"])


def _run_analysis(
    uploaded_file,
    clickup_file,
    thresholds: ThresholdConfig,
    date_start: str | None,
    date_end: str | None,
):
    """Run the pipeline and store result in session state."""
    import json
    import tempfile
    import os

    # Save uploaded CSV to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(uploaded_file.getvalue())
        csv_path = tmp.name

    # Parse ClickUp tasks if provided
    clickup_tasks = None
    if clickup_file:
        try:
            data = json.loads(clickup_file.getvalue())
            tasks_data = data if isinstance(data, list) else data.get("tasks", data.get("data", []))
            clickup_tasks = [
                ClickUpTask(
                    task_id=t.get("id", ""),
                    name=t.get("name", ""),
                    status=t.get("status", {}).get("status", "") if isinstance(t.get("status"), dict) else str(t.get("status", "")),
                    script=t.get("script", t.get("description", "")),
                    url=t.get("url", ""),
                )
                for t in tasks_data
            ]
        except (json.JSONDecodeError, KeyError) as e:
            st.error(f"Failed to parse ClickUp JSON: {e}")
            return

    with st.spinner("Aggregating CSV rows and running analysis..."):
        # Set up logging capture
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))

        # Add handler to all creative_feedback_loop loggers
        root_logger = logging.getLogger("creative_feedback_loop")
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

        try:
            result = run_pipeline(
                csv_path=csv_path,
                clickup_tasks=clickup_tasks,
                thresholds=thresholds,
                date_start=date_start,
                date_end=date_end,
            )
            st.session_state["cfl_result"] = result
            st.session_state["cfl_log"] = log_stream.getvalue()
        finally:
            root_logger.removeHandler(handler)
            os.unlink(csv_path)


def _render_results(result: PipelineResult):
    """Render the full analysis results."""

    # ── Pipeline Log (FIX 7) ──
    if "cfl_log" in st.session_state and st.session_state["cfl_log"]:
        with st.expander("Pipeline Log", expanded=False):
            st.code(st.session_state["cfl_log"])

    # ── Aggregation Summary ──
    st.header("Aggregation Summary")
    cols = st.columns(4)
    with cols[0]:
        st.metric("CSV Rows", f"{result.raw_rows:,}")
    with cols[1]:
        st.metric("Unique Ads", f"{result.unique_ads:,}")
    with cols[2]:
        st.metric("Total Spend", f"${result.total_csv_spend:,.2f}")
    with cols[3]:
        ratio = result.raw_rows / result.unique_ads if result.unique_ads > 0 else 0
        st.metric("Avg Rows/Ad", f"{ratio:.1f}")

    st.caption(
        f"Aggregated **{result.raw_rows:,}** CSV rows into **{result.unique_ads:,}** unique ads"
    )

    # ── Classification Summary ──
    st.header("Classification")
    cols2 = st.columns(4)
    with cols2[0]:
        st.metric("Winners", result.winner_count)
    with cols2[1]:
        st.metric("Losers", result.loser_count)
    with cols2[2]:
        st.metric("Untested", result.untested_count)
    with cols2[3]:
        st.metric("Above Spend Threshold", result.above_spend_threshold)

    # Show thresholds used
    t = result.thresholds
    st.caption(
        f"Winner: ROAS >= {t.winner_roas_min} AND spend >= ${t.winner_spend_min} | "
        f"Loser: ROAS < {t.loser_roas_max} AND spend >= ${t.loser_spend_min}"
    )

    # ── Section A: Winners & Losers Detail ──
    st.header("Section A: Winners & Losers")

    tab_w, tab_l, tab_u = st.tabs(["Winners", "Losers", "Untested"])

    with tab_w:
        _render_ad_table(
            [m for m in result.matched_ads if m.classified_ad.classification == "winner"],
            "winner",
        )

    with tab_l:
        _render_ad_table(
            [m for m in result.matched_ads if m.classified_ad.classification == "loser"],
            "loser",
        )

    with tab_u:
        _render_ad_table(
            [m for m in result.matched_ads if m.classified_ad.classification == "untested"],
            "untested",
        )

    # ── Section B: Top 50 by Spend (FIX 5) ──
    st.header("Section B: Top 50 by Spend")
    st.caption(
        "Top 50 ads ranked by total aggregated spend. No winner/loser thresholds — "
        "just profitability classification."
    )

    if result.top50:
        top50_data = []
        for t50 in result.top50:
            row = {
                "Rank": t50.rank,
                "Ad Name": t50.ad.ad_name,
                "Total Spend": f"${t50.ad.total_spend:,.2f}",
                "ROAS": f"{t50.ad.blended_roas:.2f}",
                "Revenue": f"${t50.ad.total_revenue:,.2f}",
                "Impressions": f"{t50.ad.total_impressions:,}",
                "Conversions": t50.ad.total_conversions,
                "Status": _profitability_label(t50.profitability),
                "ClickUp Match": t50.clickup_task.name if t50.clickup_task else "—",
            }
            top50_data.append(row)

        st.dataframe(
            pd.DataFrame(top50_data),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No ads to display.")

    # ── Section C: Pattern Analysis with Novelty Filter (FIX 6) ──
    st.header("Section C: Pattern Insights")

    if result.novelty:
        novelty = result.novelty

        # Winner signals
        if novelty.winner_signals:
            st.subheader("Winner Patterns (appear more in winners)")
            for sig in novelty.winner_signals:
                diff_pct = sig.differentiation * 100
                w_pct = sig.winner_rate * 100
                l_pct = sig.loser_rate * 100
                strength_icon = {"HIGH": "***", "MEDIUM": "**", "LOW": "*"}.get(sig.signal_strength, "")
                st.markdown(
                    f"- {strength_icon}`{sig.pattern}`{strength_icon}: "
                    f"{w_pct:.0f}% of winners vs {l_pct:.0f}% of losers "
                    f"(+{diff_pct:.0f}% differentiation — {sig.signal_strength} signal)"
                )

        # Loser signals
        if novelty.loser_signals:
            st.subheader("Loser Patterns (appear more in losers)")
            for sig in novelty.loser_signals:
                diff_pct = abs(sig.differentiation) * 100
                w_pct = sig.winner_rate * 100
                l_pct = sig.loser_rate * 100
                st.markdown(
                    f"- `{sig.pattern}`: "
                    f"{l_pct:.0f}% of losers vs {w_pct:.0f}% of winners "
                    f"(+{diff_pct:.0f}% loser skew — {sig.signal_strength} signal)"
                )

        # Baseline patterns
        if novelty.baseline_patterns:
            st.subheader("Baseline Patterns (already standard practice)")
            st.caption(
                "These patterns appear in > 85% of ALL analyzed ads (winners AND losers). "
                "They don't differentiate — they're table stakes."
            )
            for sig in novelty.baseline_patterns:
                st.markdown(
                    f"- `{sig.pattern}` — {sig.total_rate * 100:.0f}% of all ads"
                )
    else:
        st.info(
            "Not enough winners and losers to compute pattern differentiation. "
            "Try lowering thresholds or using a larger CSV export."
        )


def _render_ad_table(matched_ads: list, classification: str):
    """Render a table of matched ads."""
    if not matched_ads:
        st.info(f"No {classification} ads found.")
        return

    data = []
    for m in matched_ads:
        ad = m.classified_ad.ad
        row = {
            "Ad Name": ad.ad_name,
            "Total Spend": f"${ad.total_spend:,.2f}",
            "ROAS": f"{ad.blended_roas:.2f}",
            "Revenue": f"${ad.total_revenue:,.2f}",
            "Impressions": f"{ad.total_impressions:,}",
            "Conversions": ad.total_conversions,
            "CSV Rows": ad.row_count,
            "Reason": m.classified_ad.reason,
        }
        if m.clickup_task:
            row["ClickUp Task"] = m.clickup_task.name
            row["Match Score"] = f"{m.match_score:.0%}"
            row["Script"] = m.clickup_task.script[:100] + "..." if len(m.clickup_task.script) > 100 else m.clickup_task.script
        else:
            row["ClickUp Task"] = "—"
            row["Match Score"] = "—"
            row["Script"] = "—"
        data.append(row)

    # Sort by spend descending
    data.sort(key=lambda r: float(r["Total Spend"].replace("$", "").replace(",", "")), reverse=True)

    st.dataframe(
        pd.DataFrame(data),
        use_container_width=True,
        hide_index=True,
    )


def _profitability_label(status: str) -> str:
    """Human-readable profitability label."""
    return {
        "profitable": "Profitable (ROAS >= 1.0)",
        "unprofitable": "Unprofitable (ROAS < 1.0)",
        "no_conversions": "No Conversions (ROAS = 0)",
    }.get(status, status)

if __name__ == "__main__":
    pass


# Entry point
render_creative_feedback_loop()
