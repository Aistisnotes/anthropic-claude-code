"""Creative Feedback Loop Analyzer — Standalone Streamlit App (port 8503).

Pipeline: aggregate CSV -> classify -> match ClickUp -> read scripts ->
          Claude pattern analysis -> hypothesis generation -> report

Implements all 7 fixes:
  FIX 1: CSV aggregation by ad name before matching
  FIX 2: Separate winner/loser thresholds (defaults: ROAS 1.0, spend $50)
  FIX 3: ROAS=0 with spend = LOSER
  FIX 4: Date range filters CSV, not ClickUp
  FIX 5: Top 50 as separate unfiltered section
  FIX 6: Novelty filter for pattern analysis
  FIX 7: Aggregation stats in pipeline log
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ── Backend imports ───────────────────────────────────────────────────────────
from creative_feedback_loop.csv_aggregator import load_and_aggregate_csv, AggregatedAd
from creative_feedback_loop.classifier import ThresholdConfig, ClassifiedAd, classify_ads
from creative_feedback_loop.clickup_matcher import (
    ClickUpTask, MatchedAd, match_ads_to_clickup,
)
from creative_feedback_loop.top50 import Top50Ad, build_top50
from creative_feedback_loop.novelty_filter import compute_novelty, NoveltyResult
from creative_feedback_loop.pipeline import run_pipeline, PipelineResult, _extract_name_patterns

# ── Analyzer imports (Claude-powered deep analysis) ───────────────────────────
from creative_feedback_loop.analyzer.clickup_client import fetch_clickup_tasks
from creative_feedback_loop.analyzer.script_reader import read_scripts_from_tasks
from creative_feedback_loop.analyzer.pattern_analyzer import analyze_creative_patterns
from creative_feedback_loop.analyzer.hypothesis_generator import generate_hypotheses
from creative_feedback_loop.analyzer.report_generator import generate_markdown_report

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG — must be first Streamlit call
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Creative Feedback Loop",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
#  DARK MODE CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
  :root {
    --bg: #1a1a2e;
    --surface: #16213e;
    --card: #0f3460;
    --accent: #e94560;
    --text: #fafafa;
    --text-dim: #a0a0b0;
    --success: #00c853;
    --warning: #ffd600;
    --danger: #ff1744;
  }

  .main .block-container {
    padding-top: 1.5rem;
    max-width: 1200px;
    color: var(--text);
  }

  /* Cards */
  .metric-card {
    background: var(--surface);
    border: 1px solid #2a2a4a;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
  }
  .metric-card .value {
    font-size: 28px;
    font-weight: 800;
    color: var(--text);
  }
  .metric-card .label {
    font-size: 12px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 1px;
  }

  /* Section headers */
  .section-hdr {
    font-size: 20px;
    font-weight: 800;
    color: var(--accent);
    border-bottom: 2px solid var(--accent);
    padding-bottom: 6px;
    margin: 24px 0 12px 0;
  }

  /* Winner / Loser badges */
  .badge-winner {
    display: inline-block;
    background: #1b5e20;
    color: #69f0ae;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
  }
  .badge-loser {
    display: inline-block;
    background: #b71c1c;
    color: #ff8a80;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
  }
  .badge-untested {
    display: inline-block;
    background: #424242;
    color: #bdbdbd;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
  }

  /* Hypothesis cards */
  .hypo-card {
    border: 1px solid #2a2a4a;
    border-left: 4px solid var(--accent);
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 12px;
    background: var(--surface);
    color: var(--text);
  }

  /* Buttons */
  .stButton > button {
    background: var(--accent) !important;
    color: white !important;
    border: none !important;
    font-weight: 700 !important;
    border-radius: 8px !important;
  }
  .stButton > button:hover {
    background: #c62828 !important;
  }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN GATE
# ══════════════════════════════════════════════════════════════════════════════
def _check_auth() -> bool:
    """Login gate using TOOL_PASSWORD env var. Skipped if not set."""
    if st.session_state.get("cfl_authenticated"):
        return True

    expected_pass = os.environ.get("TOOL_PASSWORD", "")
    if not expected_pass:
        st.session_state["cfl_authenticated"] = True
        return True

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("## 🔄 Creative Feedback Loop")
        st.markdown("---")
        with st.form("cfl_login"):
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
            if submitted:
                if password == expected_pass:
                    st.session_state["cfl_authenticated"] = True
                    st.rerun()
                else:
                    st.error("Invalid password.")
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
def main():
    if not _check_auth():
        return

    st.markdown("# 🔄 Creative Feedback Loop")
    st.caption(
        "Upload a Meta Ads Manager CSV. Ads are aggregated by name across ad sets, "
        "classified as winners/losers, matched to ClickUp, scripts read, and "
        "analyzed with Claude for patterns and hypotheses."
    )

    # ── Sidebar: Input Form ───────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## Configuration")

        with st.form("cfl_config_form"):
            brand_name = st.text_input(
                "Brand Name",
                placeholder="e.g. TryElare",
                key="cfl_brand",
            )

            uploaded_csv = st.file_uploader(
                "Meta Ads Manager CSV",
                type=["csv"],
                help="One row per ad per ad set is fine — we aggregate automatically.",
                key="cfl_csv_upload",
            )

            st.markdown("---")

            # FIX 4: Optional date range (filters CSV rows, NOT ClickUp)
            st.markdown("**Date Range (Optional)**")
            st.caption("Filters rows within the CSV. Leave blank to use all data.")
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                date_start = st.date_input("Start", value=None, key="cfl_ds")
            with d_col2:
                date_end = st.date_input("End", value=None, key="cfl_de")

            st.markdown("---")

            # FIX 2: Separate winner and loser thresholds
            st.markdown("**Winner Criteria**")
            st.caption("Ads meeting BOTH = winner")
            winner_roas = st.number_input(
                "ROAS above", min_value=0.0, value=1.0, step=0.1, key="cfl_wr",
            )
            winner_spend = st.number_input(
                "AND spend above ($)", min_value=0.0, value=50.0, step=10.0, key="cfl_ws",
            )

            st.markdown("---")

            st.markdown("**Loser Criteria**")
            st.caption("Ads meeting BOTH = loser. ROAS=0 with spend = LOSER.")
            loser_roas = st.number_input(
                "ROAS below", min_value=0.0, value=1.0, step=0.1, key="cfl_lr",
            )
            loser_spend = st.number_input(
                "AND spend above ($)", min_value=0.0, value=50.0, step=10.0, key="cfl_ls",
            )

            st.markdown("---")

            # ClickUp config
            st.markdown("**ClickUp (Optional)**")
            clickup_list_id = st.text_input(
                "ClickUp List ID",
                placeholder="e.g. 901234567890",
                key="cfl_clickup_list",
                help="Leave blank to skip ClickUp matching. Set CLICKUP_API_KEY env var.",
            )

            st.markdown("---")

            run_deep = st.checkbox(
                "Run Claude deep analysis",
                value=True,
                key="cfl_deep",
                help="Uses Claude API for pattern analysis and hypothesis generation.",
            )

            submitted = st.form_submit_button(
                "Run Analysis", type="primary", use_container_width=True,
            )

    # ── Main area ─────────────────────────────────────────────────────────────
    if not uploaded_csv:
        st.info("Upload a Meta Ads Manager CSV in the sidebar to begin.")
        return

    if not submitted and "cfl_result" not in st.session_state:
        st.info("Configure thresholds, then click **Run Analysis**.")
        return

    # ── Run pipeline on submit ────────────────────────────────────────────────
    if submitted:
        _run_full_pipeline(
            uploaded_csv=uploaded_csv,
            brand_name=brand_name or "Brand",
            thresholds=ThresholdConfig(
                winner_roas_min=winner_roas,
                winner_spend_min=winner_spend,
                loser_roas_max=loser_roas,
                loser_spend_min=loser_spend,
            ),
            date_start=str(date_start) if date_start else None,
            date_end=str(date_end) if date_end else None,
            clickup_list_id=clickup_list_id.strip() if clickup_list_id else None,
            run_deep=run_deep,
        )

    # ── Render results ────────────────────────────────────────────────────────
    if "cfl_result" in st.session_state:
        _render_results()


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE EXECUTION
# ══════════════════════════════════════════════════════════════════════════════
def _run_full_pipeline(
    uploaded_csv,
    brand_name: str,
    thresholds: ThresholdConfig,
    date_start: str | None,
    date_end: str | None,
    clickup_list_id: str | None,
    run_deep: bool,
):
    """Execute the full pipeline and store results in session state."""

    # Save CSV to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(uploaded_csv.getvalue())
        csv_path = tmp.name

    # Set up logging capture (FIX 7)
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    cfl_logger = logging.getLogger("creative_feedback_loop")
    cfl_logger.setLevel(logging.INFO)
    cfl_logger.addHandler(handler)

    try:
        with st.spinner("Step 1/6: Aggregating CSV rows by ad name..."):
            # ── FIX 1: Aggregate CSV ──
            all_ads, csv_stats = load_and_aggregate_csv(
                csv_path, date_start=date_start, date_end=date_end,
            )

        st.toast(
            f"Aggregated {csv_stats['raw_rows']:,} rows into "
            f"{csv_stats['unique_ads']:,} unique ads"
        )

        with st.spinner("Step 2/6: Classifying winners and losers..."):
            # ── FIX 2 + FIX 3: Classify with separate thresholds, ROAS=0 = loser ──
            classified, counts = classify_ads(all_ads, thresholds)

        with st.spinner("Step 3/6: Matching to ClickUp tasks..."):
            # ── Fetch ClickUp tasks if configured ──
            clickup_tasks = None
            if clickup_list_id:
                clickup_tasks = fetch_clickup_tasks(clickup_list_id)
                if clickup_tasks:
                    st.toast(f"Fetched {len(clickup_tasks)} ClickUp tasks")

            if clickup_tasks:
                matched = match_ads_to_clickup(classified, clickup_tasks)
            else:
                matched = [MatchedAd(classified_ad=c) for c in classified]

        with st.spinner("Step 4/6: Building Top 50 by spend..."):
            # ── FIX 5: Top 50 unfiltered ──
            top50 = build_top50(all_ads, clickup_tasks)

        # ── Read scripts from matched ClickUp tasks ──
        with st.spinner("Step 5/6: Reading scripts from ClickUp tasks..."):
            tasks_with_scripts = []
            for m in matched:
                tasks_with_scripts.append({
                    "ad_name": m.classified_ad.ad.ad_name,
                    "classification": m.classified_ad.classification,
                    "spend": m.classified_ad.ad.total_spend,
                    "roas": m.classified_ad.ad.blended_roas,
                    "revenue": m.classified_ad.ad.total_revenue,
                    "clickup_task": m.clickup_task,
                })
            tasks_with_scripts = read_scripts_from_tasks(tasks_with_scripts)

        # ── Claude deep analysis ──
        pattern_analysis = None
        hypotheses = None
        if run_deep:
            with st.spinner("Step 6/6: Running Claude pattern analysis + hypotheses..."):
                winners_for_claude = [
                    t for t in tasks_with_scripts if t["classification"] == "winner"
                ]
                losers_for_claude = [
                    t for t in tasks_with_scripts if t["classification"] == "loser"
                ]

                try:
                    loop = asyncio.new_event_loop()
                    pattern_analysis = loop.run_until_complete(
                        analyze_creative_patterns(
                            winners_for_claude, losers_for_claude, brand_name,
                        )
                    )

                    if pattern_analysis and not pattern_analysis.get("error"):
                        hypotheses = loop.run_until_complete(
                            generate_hypotheses(pattern_analysis, brand_name)
                        )
                    loop.close()
                except Exception as e:
                    logger.error(f"Claude analysis failed: {e}")
                    st.warning(f"Claude analysis failed: {e}. Results shown without deep analysis.")
        else:
            st.info("Skipping Claude deep analysis (checkbox unchecked).")

        # ── FIX 6: Novelty filter ──
        winners_classified = [c for c in classified if c.classification == "winner"]
        losers_classified = [c for c in classified if c.classification == "loser"]
        winner_pats = _extract_name_patterns(winners_classified)
        loser_pats = _extract_name_patterns(losers_classified)
        novelty = None
        if winners_classified or losers_classified:
            novelty = compute_novelty(
                winner_pats, loser_pats,
                total_winners=len(winners_classified),
                total_losers=len(losers_classified),
            )

        # ── Generate markdown report ──
        report_md = generate_markdown_report(
            brand_name=brand_name,
            aggregation_stats=csv_stats,
            classification_counts=counts,
            winners=[
                {"ad_name": c.ad.ad_name, "spend": c.ad.total_spend,
                 "roas": c.ad.blended_roas, "revenue": c.ad.total_revenue}
                for c in classified if c.classification == "winner"
            ],
            losers=[
                {"ad_name": c.ad.ad_name, "spend": c.ad.total_spend,
                 "roas": c.ad.blended_roas, "revenue": c.ad.total_revenue}
                for c in classified if c.classification == "loser"
            ],
            top50=[
                {"ad_name": t.ad.ad_name, "spend": t.ad.total_spend,
                 "roas": t.ad.blended_roas, "profitability": t.profitability}
                for t in top50
            ],
            pattern_analysis=pattern_analysis,
            hypotheses=hypotheses,
            novelty=novelty,
        )

        # ── Store everything in session state ──
        st.session_state["cfl_result"] = {
            "brand_name": brand_name,
            "csv_stats": csv_stats,
            "counts": counts,
            "thresholds": thresholds,
            "classified": classified,
            "matched": matched,
            "top50": top50,
            "tasks_with_scripts": tasks_with_scripts,
            "pattern_analysis": pattern_analysis,
            "hypotheses": hypotheses,
            "novelty": novelty,
            "report_md": report_md,
            "all_ads": all_ads,
        }
        st.session_state["cfl_log"] = log_stream.getvalue()

    finally:
        cfl_logger.removeHandler(handler)
        try:
            os.unlink(csv_path)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER RESULTS
# ══════════════════════════════════════════════════════════════════════════════
def _render_results():
    """Render the full analysis results."""
    r = st.session_state["cfl_result"]
    csv_stats = r["csv_stats"]
    counts = r["counts"]
    thresholds = r["thresholds"]
    classified = r["classified"]
    matched = r["matched"]
    top50 = r["top50"]
    pattern_analysis = r.get("pattern_analysis")
    hypotheses = r.get("hypotheses")
    novelty = r.get("novelty")
    report_md = r.get("report_md", "")

    # ── Pipeline log ──────────────────────────────────────────────────────────
    if st.session_state.get("cfl_log"):
        with st.expander("Pipeline Log", expanded=False):
            st.code(st.session_state["cfl_log"])

    # ── Aggregation metrics (FIX 7) ──────────────────────────────────────────
    st.markdown('<div class="section-hdr">Aggregation Summary</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("CSV Rows", f"{csv_stats['raw_rows']:,}")
    with m2:
        st.metric("Unique Ads", f"{csv_stats['unique_ads']:,}")
    with m3:
        st.metric("Total Spend", f"${csv_stats['total_spend']:,.2f}")
    with m4:
        ratio = csv_stats["raw_rows"] / csv_stats["unique_ads"] if csv_stats["unique_ads"] > 0 else 0
        st.metric("Avg Rows/Ad", f"{ratio:.1f}")

    st.caption(
        f"Aggregated **{csv_stats['raw_rows']:,}** CSV rows into "
        f"**{csv_stats['unique_ads']:,}** unique ads"
    )

    # ── Classification metrics ────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">Classification</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Winners", counts["winner"])
    with c2:
        st.metric("Losers", counts["loser"])
    with c3:
        st.metric("Untested", counts["untested"])
    with c4:
        st.metric("Above Spend Min", counts["winner"] + counts["loser"])

    st.caption(
        f"Winner: ROAS >= {thresholds.winner_roas_min} AND spend >= ${thresholds.winner_spend_min} | "
        f"Loser: ROAS < {thresholds.loser_roas_max} AND spend >= ${thresholds.loser_spend_min}"
    )

    # ══════════════════════════════════════════════════════════════════════════
    #  THREE TABS: Recent Creative | Top 50 | Comparison
    # ══════════════════════════════════════════════════════════════════════════
    tab_recent, tab_top50, tab_comparison = st.tabs([
        "Recent Creative", "Top 50 by Spend", "Comparison"
    ])

    # ── TAB 1: Recent Creative (winners, losers, untested) ────────────────────
    with tab_recent:
        st.markdown('<div class="section-hdr">Winners & Losers</div>', unsafe_allow_html=True)

        sub_w, sub_l, sub_u = st.tabs(["Winners", "Losers", "Untested"])

        with sub_w:
            _render_ad_table(
                [m for m in matched if m.classified_ad.classification == "winner"],
                "winner",
            )
        with sub_l:
            _render_ad_table(
                [m for m in matched if m.classified_ad.classification == "loser"],
                "loser",
            )
        with sub_u:
            _render_ad_table(
                [m for m in matched if m.classified_ad.classification == "untested"],
                "untested",
            )

        # Pattern analysis results (Claude-powered)
        if pattern_analysis and not pattern_analysis.get("error"):
            st.markdown('<div class="section-hdr">Claude Pattern Analysis</div>', unsafe_allow_html=True)

            summary = pattern_analysis.get("executive_summary", "")
            if summary:
                st.info(summary)

            pa_col1, pa_col2 = st.columns(2)

            with pa_col1:
                winning_pats = pattern_analysis.get("winning_patterns", [])
                if winning_pats:
                    st.markdown("**Winning Patterns**")
                    for p in winning_pats:
                        st.markdown(
                            f"- **{p.get('pattern', '')}** ({p.get('frequency', '')})\n"
                            f"  {p.get('why_it_works', '')}"
                        )

            with pa_col2:
                losing_pats = pattern_analysis.get("losing_patterns", [])
                if losing_pats:
                    st.markdown("**Losing Patterns**")
                    for p in losing_pats:
                        st.markdown(
                            f"- **{p.get('pattern', '')}** ({p.get('frequency', '')})\n"
                            f"  {p.get('why_it_fails', '')}"
                        )

            key_diffs = pattern_analysis.get("key_differences", [])
            if key_diffs:
                st.markdown("**Key Differences**")
                diff_data = []
                for d in key_diffs:
                    diff_data.append({
                        "Dimension": d.get("dimension", ""),
                        "Winners Do": d.get("winners_do", ""),
                        "Losers Do": d.get("losers_do", ""),
                        "Insight": d.get("insight", ""),
                    })
                st.dataframe(pd.DataFrame(diff_data), use_container_width=True, hide_index=True)

            recs = pattern_analysis.get("actionable_recommendations", [])
            if recs:
                st.markdown("**Recommendations**")
                for rec in recs:
                    st.markdown(
                        f"**P{rec.get('priority', '?')}:** {rec.get('action', '')} "
                        f"— *{rec.get('expected_impact', '')}*"
                    )

        # Hypotheses
        if hypotheses:
            st.markdown('<div class="section-hdr">Creative Hypotheses</div>', unsafe_allow_html=True)
            for h in hypotheses:
                priority = h.get("priority", "")
                color = {"HIGH": "#e94560", "MEDIUM": "#ffd600", "LOW": "#69f0ae"}.get(priority, "#a0a0b0")
                st.markdown(f"""
                <div class="hypo-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <strong style="color:{color};">{h.get('hypothesis_id', '')} — {priority}</strong>
                        <span style="font-size:11px;color:var(--text-dim);">
                            Confidence: {h.get('confidence', '')}
                        </span>
                    </div>
                    <div style="margin-top:8px;font-size:14px;color:var(--text);">
                        {h.get('hypothesis', '')}
                    </div>
                    <div style="margin-top:8px;font-size:12px;color:var(--text-dim);">
                        <strong>Format:</strong> {h.get('test_format', '')} &nbsp;|&nbsp;
                        <strong>Metric:</strong> {h.get('success_metric', '')}
                    </div>
                    <div style="margin-top:4px;font-size:12px;color:var(--text-dim);">
                        <strong>Brief:</strong> {h.get('script_direction', '')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # ── TAB 2: Top 50 by Spend (FIX 5) ───────────────────────────────────────
    with tab_top50:
        st.markdown('<div class="section-hdr">Top 50 by Aggregated Spend</div>', unsafe_allow_html=True)
        st.caption(
            "Ranked by total spend. No winner/loser thresholds — simple profitability."
        )

        if top50:
            top50_rows = []
            for t in top50:
                status_label = {
                    "profitable": "Profitable",
                    "unprofitable": "Unprofitable",
                    "no_conversions": "No Conversions (ROAS=0)",
                }.get(t.profitability, t.profitability)

                top50_rows.append({
                    "Rank": t.rank,
                    "Ad Name": t.ad.ad_name,
                    "Total Spend": f"${t.ad.total_spend:,.2f}",
                    "ROAS": f"{t.ad.blended_roas:.2f}",
                    "Revenue": f"${t.ad.total_revenue:,.2f}",
                    "Impressions": f"{t.ad.total_impressions:,}",
                    "Conversions": t.ad.total_conversions,
                    "Status": status_label,
                    "ClickUp": t.clickup_task.name if t.clickup_task else "—",
                })
            st.dataframe(
                pd.DataFrame(top50_rows), use_container_width=True, hide_index=True,
            )
        else:
            st.info("No ads to display.")

    # ── TAB 3: Comparison — Novelty Filter (FIX 6) ───────────────────────────
    with tab_comparison:
        st.markdown('<div class="section-hdr">Pattern Comparison — Novelty Filter</div>', unsafe_allow_html=True)
        st.caption(
            "Patterns that differentiate winners from losers. "
            "Baseline patterns (>85% of all ads) are separated as non-differentiating."
        )

        if novelty:
            if novelty.winner_signals:
                st.markdown("#### Winner-Skewing Patterns")
                for sig in novelty.winner_signals:
                    diff_pct = sig.differentiation * 100
                    w_pct = sig.winner_rate * 100
                    l_pct = sig.loser_rate * 100
                    icon = {"HIGH": "🔥", "MEDIUM": "📊", "LOW": "📉"}.get(sig.signal_strength, "")
                    st.markdown(
                        f"- {icon} **`{sig.pattern}`**: "
                        f"{w_pct:.0f}% of winners vs {l_pct:.0f}% of losers "
                        f"(+{diff_pct:.0f}% — **{sig.signal_strength}** signal)"
                    )

            if novelty.loser_signals:
                st.markdown("#### Loser-Skewing Patterns")
                for sig in novelty.loser_signals:
                    diff_pct = abs(sig.differentiation) * 100
                    l_pct = sig.loser_rate * 100
                    w_pct = sig.winner_rate * 100
                    st.markdown(
                        f"- **`{sig.pattern}`**: "
                        f"{l_pct:.0f}% of losers vs {w_pct:.0f}% of winners "
                        f"(+{diff_pct:.0f}% loser skew — **{sig.signal_strength}**)"
                    )

            if novelty.baseline_patterns:
                st.markdown("#### Baseline — Already Standard Practice")
                st.caption(
                    "These patterns appear in >85% of ALL ads. They don't differentiate."
                )
                for sig in novelty.baseline_patterns:
                    st.markdown(f"- `{sig.pattern}` — {sig.total_rate * 100:.0f}% of all ads")
        else:
            st.info(
                "Not enough winners and losers to compute differentiation. "
                "Try lowering thresholds or using a larger CSV."
            )

    # ── Download report ───────────────────────────────────────────────────────
    st.markdown("---")
    if report_md:
        st.download_button(
            "Download Full Report (.md)",
            data=report_md,
            file_name=f"creative_feedback_{r['brand_name']}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _render_ad_table(matched_ads: list[MatchedAd], classification: str):
    """Render a dataframe table for a set of matched ads."""
    if not matched_ads:
        st.info(f"No {classification} ads found.")
        return

    rows = []
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
            row["Match"] = f"{m.match_score:.0%} ({m.match_method})"
            script = m.clickup_task.script
            row["Script Preview"] = (script[:80] + "...") if len(script) > 80 else (script or "—")
        else:
            row["ClickUp Task"] = "—"
            row["Match"] = "—"
            row["Script Preview"] = "—"
        rows.append(row)

    rows.sort(
        key=lambda x: float(x["Total Spend"].replace("$", "").replace(",", "")),
        reverse=True,
    )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
