"""Creative Feedback Loop Analyzer — Streamlit App

Analyzes Meta ad CSV exports to find multi-dimensional patterns
in winning vs losing ads. Uses Claude API for deep pattern analysis.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

from creative_feedback_loop.naming_parser import extract_dimensions_from_dataframe
from creative_feedback_loop.dashboard.structured_splits import (
    DIMENSIONS,
    DIMENSION_LABELS,
    build_dimension_html_table,
    compute_all_dimensions,
)
from creative_feedback_loop.analyzer.pattern_analyzer import analyze_patterns

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Creative Feedback Loop",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Dark theme CSS ───────────────────────────────────────────────────────────
st.markdown("""<style>
    .stApp { background-color: #0e1117; }
    .step-badge { background:#e91e8c; color:white; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:8px; }
    .step-label { color:#fafafa; font-weight:600; }
    .step-container { background:#1e1e2e; padding:12px 16px; border-radius:8px; margin-bottom:12px; }
</style>""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def clean_markdown(text: str) -> str:
    """Escape dollar signs for Streamlit markdown rendering."""
    if not text:
        return ""
    return str(text).replace("$", "&#36;")


def load_and_aggregate_csv(uploaded_file) -> Optional[pd.DataFrame]:
    """Load and aggregate a Meta ads CSV export.

    Handles multiple CSV formats, cleans numeric columns,
    and returns a unified DataFrame.

    Args:
        uploaded_file: Streamlit UploadedFile object

    Returns:
        Aggregated DataFrame or None if loading fails
    """
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Failed to read CSV: {e}")
        return None

    if df.empty:
        st.error("CSV file is empty.")
        return None

    # Normalize column names — strip whitespace
    df.columns = df.columns.str.strip()

    # Detect spend column
    spend_candidates = [
        "Amount Spent (USD)", "Amount spent (USD)", "Spend", "spend",
        "Cost", "Amount Spent", "amount_spent",
    ]
    spend_col = None
    for c in spend_candidates:
        if c in df.columns:
            spend_col = c
            break

    if spend_col and spend_col != "Amount Spent (USD)":
        df = df.rename(columns={spend_col: "Amount Spent (USD)"})

    # Detect ROAS column
    roas_candidates = [
        "ROAS (Purchase)", "Purchase ROAS", "ROAS", "roas",
        "Website Purchase ROAS", "Purchase ROAS (Total)",
    ]
    roas_col = None
    for c in roas_candidates:
        if c in df.columns:
            roas_col = c
            break

    if roas_col and roas_col != "ROAS (Purchase)":
        df = df.rename(columns={roas_col: "ROAS (Purchase)"})

    # Detect ad name column
    name_candidates = [
        "Ad Name", "Ad name", "ad_name", "Name", "name",
        "Campaign name", "Ad Set Name",
    ]
    name_col = None
    for c in name_candidates:
        if c in df.columns:
            name_col = c
            break

    if name_col and name_col != "Ad Name":
        df = df.rename(columns={name_col: "Ad Name"})

    # Clean numeric columns
    for col in ["Amount Spent (USD)", "ROAS (Purchase)"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "").str.replace("$", ""), errors="coerce")

    # Extract dimensions from ad names
    if "Ad Name" in df.columns:
        df = extract_dimensions_from_dataframe(df, "Ad Name")

    return df


def classify_ads(
    df: pd.DataFrame,
    winner_min_roas: float,
    winner_min_spend: float,
    loser_max_roas: float,
    loser_min_spend: float,
) -> pd.DataFrame:
    """Classify ads as Winner, Loser, or Unclear based on thresholds.

    Args:
        df: DataFrame with spend and ROAS columns
        winner_min_roas: Minimum ROAS for a winner
        winner_min_spend: Minimum spend for a winner
        loser_max_roas: Maximum ROAS for a loser
        loser_min_spend: Minimum spend for a loser (to avoid noise)

    Returns:
        DataFrame with 'classification' column added
    """
    spend_col = "Amount Spent (USD)"
    roas_col = "ROAS (Purchase)"

    conditions = []
    # Winner: high ROAS + enough spend
    is_winner = (df[roas_col] >= winner_min_roas) & (df[spend_col] >= winner_min_spend)
    # Loser: low ROAS + enough spend to be meaningful
    is_loser = (df[roas_col] < loser_max_roas) & (df[spend_col] >= loser_min_spend)

    df["classification"] = "Unclear"
    df.loc[is_winner, "classification"] = "Winner"
    df.loc[is_loser, "classification"] = "Loser"

    return df


def get_top50_by_spend(df: pd.DataFrame) -> pd.DataFrame:
    """Get top 50 ads by spend."""
    spend_col = "Amount Spent (USD)"
    if spend_col in df.columns:
        return df.nlargest(50, spend_col).copy()
    return df.head(50).copy()


def _prepare_classified_data(df: pd.DataFrame) -> dict[str, Any]:
    """Prepare classified ad data for Claude analysis."""
    winners = df[df["classification"] == "Winner"]
    losers = df[df["classification"] == "Loser"]

    def _summarize_group(group: pd.DataFrame) -> list[dict]:
        rows = []
        for _, row in group.iterrows():
            rows.append({
                "ad_name": str(row.get("Ad Name", "")),
                "spend": float(row.get("Amount Spent (USD)", 0)),
                "roas": float(row.get("ROAS (Purchase)", 0)),
                "pain_point": str(row.get("pain_point", "")),
                "awareness_level": str(row.get("awareness_level", "")),
                "ad_format": str(row.get("ad_format", "")),
                "mechanism": str(row.get("mechanism", "")),
                "avatar": str(row.get("avatar", "")),
                "root_cause": str(row.get("root_cause", "")),
                "symptoms": str(row.get("symptoms", "")),
            })
        return rows

    dimensions = compute_all_dimensions(df)

    return {
        "total_ads": len(df),
        "total_winners": len(winners),
        "total_losers": len(losers),
        "total_spend": float(df["Amount Spent (USD)"].sum()) if "Amount Spent (USD)" in df.columns else 0,
        "winners": _summarize_group(winners),
        "losers": _summarize_group(losers),
        "dimension_breakdowns": {k: v[:10] for k, v in dimensions.items()},  # Top 10 per dim
    }


def _prepare_top50_data(df: pd.DataFrame) -> dict[str, Any]:
    """Prepare top 50 data for Claude analysis."""
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ad_name": str(row.get("Ad Name", "")),
            "spend": float(row.get("Amount Spent (USD)", 0)),
            "roas": float(row.get("ROAS (Purchase)", 0)),
            "pain_point": str(row.get("pain_point", "")),
            "awareness_level": str(row.get("awareness_level", "")),
            "ad_format": str(row.get("ad_format", "")),
            "mechanism": str(row.get("mechanism", "")),
            "avatar": str(row.get("avatar", "")),
            "root_cause": str(row.get("root_cause", "")),
            "symptoms": str(row.get("symptoms", "")),
        })

    dimensions = compute_all_dimensions(df)

    return {
        "total_ads": len(df),
        "total_spend": float(df["Amount Spent (USD)"].sum()) if "Amount Spent (USD)" in df.columns else 0,
        "ads": rows,
        "dimension_breakdowns": {k: v[:10] for k, v in dimensions.items()},
    }


# ── Render helpers ───────────────────────────────────────────────────────────

def render_step(number: int, label: str) -> None:
    """Render a styled step header."""
    st.markdown(f"""<div style="background:#1e1e2e; padding:12px 16px; border-radius:8px; margin-bottom:12px;">
  <span style="background:#e91e8c; color:white; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:8px;">Step {number}</span>
  <span style="color:#fafafa; font-weight:600;">{clean_markdown(label)}</span>
</div>""", unsafe_allow_html=True)


def render_insight_card(insight: dict, index: int) -> None:
    """Render a loophole-style insight card."""
    title = clean_markdown(insight.get("title", "Untitled"))
    desc = clean_markdown(insight.get("description", ""))
    score = insight.get("score", 0)
    spend_vol = clean_markdown(str(insight.get("spend_volume", "")))
    hit_rate = clean_markdown(str(insight.get("hit_rate", "")))
    evidence = clean_markdown(str(insight.get("evidence_from", "")))
    confidence = clean_markdown(str(insight.get("confidence", "")))

    w_data = insight.get("winner_data", {})
    l_data = insight.get("loser_data", {})
    w_count = w_data.get("count", 0)
    w_spend = w_data.get("total_spend", 0)
    w_roas = w_data.get("avg_roas", 0)
    w_share = w_data.get("spend_share_pct", 0)
    l_count = l_data.get("count", 0)
    l_spend = l_data.get("total_spend", 0)
    l_roas = l_data.get("avg_roas", 0)

    st.markdown(f"""<div style="background:#1e1e2e; border-radius:12px; padding:20px; margin-bottom:16px; border:1px solid #333;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <span style="background:#e91e8c; color:white; padding:4px 12px; border-radius:6px; font-size:13px; font-weight:600;">
      PATTERN #{index} — Score: {score}/100
    </span>
    <span style="color:#888; font-size:12px;">Spend Volume: {spend_vol} | Hit Rate: {hit_rate}</span>
  </div>
  <h3 style="color:#fafafa; margin:0 0 8px 0; font-size:16px;">
    {title}
  </h3>
  <div style="color:#ccc; font-size:14px; line-height:1.6; margin-bottom:12px;">
    {desc}
  </div>
  <div style="display:flex; gap:20px; margin-bottom:12px;">
    <div style="flex:1; background:#262730; padding:10px; border-radius:6px;">
      <div style="color:#888; font-size:11px; text-transform:uppercase;">Evidence From</div>
      <div style="color:#fafafa; font-size:13px;">{evidence}</div>
    </div>
    <div style="flex:1; background:#262730; padding:10px; border-radius:6px;">
      <div style="color:#888; font-size:11px; text-transform:uppercase;">Confidence</div>
      <div style="color:#fafafa; font-size:13px;">{confidence}</div>
    </div>
  </div>
  <div style="background:#262730; padding:10px; border-radius:6px;">
    <div style="color:#888; font-size:11px; text-transform:uppercase;">Data</div>
    <div style="color:#fafafa; font-size:13px;">
      Winners: {w_count} ads | &#36;{w_spend:,.0f} total spend | {w_roas:.2f}x avg ROAS | {w_share}% of winner spend<br>
      Losers: {l_count} ads | &#36;{l_spend:,.0f} total spend | {l_roas:.2f}x avg ROAS
    </div>
  </div>
</div>""", unsafe_allow_html=True)


def render_top_pattern_card(pattern: dict, index: int) -> None:
    """Render a top pattern card with gold/amber border."""
    pat_name = clean_markdown(str(pattern.get("pattern", "")))
    total_spend = pattern.get("total_spend", 0)
    avg_roas = pattern.get("avg_roas", 0)
    hit_rate = clean_markdown(str(pattern.get("hit_rate", "")))
    expansions = pattern.get("expansion_opportunities", [])

    exp_html = ""
    for exp in expansions:
        exp_html += f'<div style="color:#ccc; font-size:13px; margin-top:4px;">→ {clean_markdown(str(exp))}</div>'

    st.markdown(f"""<div style="background:#1e1e2e; border-radius:12px; padding:20px; margin-bottom:16px; border:1px solid #f59e0b;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <span style="background:#f59e0b; color:#000; padding:4px 12px; border-radius:6px; font-size:13px; font-weight:600;">
      TOP PATTERN #{index}
    </span>
    <span style="color:#888; font-size:12px;">&#36;{total_spend:,.0f} spend | {avg_roas:.2f}x ROAS | {hit_rate}</span>
  </div>
  <h3 style="color:#fafafa; margin:0 0 8px 0; font-size:16px;">{pat_name}</h3>
  <div style="background:#262730; padding:10px; border-radius:6px; margin-top:8px;">
    <div style="color:#888; font-size:11px; text-transform:uppercase; margin-bottom:4px;">Expansion Opportunities</div>
    {exp_html}
  </div>
</div>""", unsafe_allow_html=True)


def render_learning_card(learning: dict) -> None:
    """Render a styled learning card."""
    title = clean_markdown(str(learning.get("title", "")))
    desc = clean_markdown(str(learning.get("description", "")))
    confidence = clean_markdown(str(learning.get("confidence", "")))
    spend_share = learning.get("spend_share_pct", 0)
    hit_rate = clean_markdown(str(learning.get("hit_rate", "")))

    st.markdown(f"""<div style="background:#1e1e2e; border-left:3px solid #3b82f6; padding:12px 16px; margin-bottom:8px; border-radius:0 8px 8px 0;">
  <div style="color:#fafafa; font-weight:600; font-size:14px;">{title}</div>
  <div style="color:#ccc; font-size:13px; margin-top:4px;">
    {desc}
  </div>
  <div style="color:#888; font-size:11px; margin-top:4px;">
    Confidence: {confidence} | Spend share: {spend_share}% of winners | Hit rate: {hit_rate}
  </div>
</div>""", unsafe_allow_html=True)


def render_hypothesis_card(hyp: dict) -> None:
    """Render a styled hypothesis card."""
    title = clean_markdown(str(hyp.get("title", "")))
    test = clean_markdown(str(hyp.get("test", "")))
    expected = clean_markdown(str(hyp.get("expected_outcome", "")))
    based_on = hyp.get("based_on_ads", [])
    based_on_str = clean_markdown(", ".join(str(a) for a in based_on))
    risk = clean_markdown(str(hyp.get("risk_level", "")))
    risk_rationale = clean_markdown(str(hyp.get("risk_rationale", "")))
    priority = clean_markdown(str(hyp.get("priority", "")))

    st.markdown(f"""<div style="background:#1e1e2e; border-left:3px solid #f59e0b; padding:12px 16px; margin-bottom:8px; border-radius:0 8px 8px 0;">
  <div style="color:#fafafa; font-weight:600; font-size:14px;">{title}</div>
  <div style="color:#ccc; font-size:13px; margin-top:4px;">
    TEST: {test}<br>
    EXPECTED: {expected}<br>
    BASED ON: {based_on_str}
  </div>
  <div style="color:#888; font-size:11px; margin-top:4px;">
    Risk: {risk} — {risk_rationale} | Priority: {priority}
  </div>
</div>""", unsafe_allow_html=True)


def render_header_metrics(df: pd.DataFrame, classified_df: pd.DataFrame) -> None:
    """Render summary metric cards at top of results."""
    total = len(df)
    winners = len(classified_df[classified_df["classification"] == "Winner"])
    losers = len(classified_df[classified_df["classification"] == "Loser"])
    total_spend = df["Amount Spent (USD)"].sum() if "Amount Spent (USD)" in df.columns else 0
    avg_roas = df["ROAS (Purchase)"].mean() if "ROAS (Purchase)" in df.columns else 0

    cols = st.columns(5)
    metrics = [
        ("Total Ads", f"{total}"),
        ("Winners", f"{winners}"),
        ("Losers", f"{losers}"),
        ("Total Spend", f"${total_spend:,.0f}"),
        ("Avg ROAS", f"{avg_roas:.2f}x"),
    ]
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.markdown(f"""<div style="background:#1e1e2e; padding:16px; border-radius:8px; text-align:center;">
  <div style="color:#888; font-size:12px; text-transform:uppercase;">{label}</div>
  <div style="color:#fafafa; font-size:24px; font-weight:700;">{clean_markdown(value)}</div>
</div>""", unsafe_allow_html=True)


# ── Main app ─────────────────────────────────────────────────────────────────

def main():
    st.markdown('<h1 style="color:#fafafa;">🔄 Creative Feedback Loop Analyzer</h1>', unsafe_allow_html=True)

    # ── Step 1: Upload CSV ──
    render_step(1, "Upload Meta CSV File")
    uploaded_file = st.file_uploader(
        "Upload your Meta Ads CSV export",
        type=["csv"],
        key="csv_upload",
        label_visibility="collapsed",
    )

    # ── Step 2: Brand Name ──
    render_step(2, "Brand Name on ClickUp (Optional)")
    brand_name = st.text_input(
        "Brand name",
        placeholder="e.g., Sculptique",
        key="brand_name",
        label_visibility="collapsed",
        help="Optional — enables script reading from ClickUp tasks",
    )

    # ── Step 3: Winning Ad Criteria ──
    render_step(3, "Winning Ad Criteria")
    col_w1, col_w2 = st.columns(2)
    with col_w1:
        winner_min_roas = st.number_input(
            "Winner Min ROAS",
            value=1.0,
            min_value=0.0,
            step=0.1,
            key="winner_min_roas",
        )
    with col_w2:
        winner_min_spend = st.number_input(
            "Winner Min Spend ($)",
            value=5000.0,
            min_value=0.0,
            step=100.0,
            key="winner_min_spend",
        )

    # ── Step 4: Losing Ad Criteria ──
    render_step(4, "Losing Ad Criteria")
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        loser_max_roas = st.number_input(
            "Loser Max ROAS",
            value=1.0,
            min_value=0.0,
            step=0.1,
            key="loser_max_roas",
        )
    with col_l2:
        loser_min_spend = st.number_input(
            "Loser Min Spend ($)",
            value=100.0,
            min_value=0.0,
            step=10.0,
            key="loser_min_spend",
        )

    # ── Step 5: Analysis Priority ──
    render_step(5, "Analysis Priority (Optional)")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        priority_focus = st.selectbox(
            "Priority",
            options=["General", "Spend Volume", "Efficiency", "New Angles"],
            key="priority_focus",
            label_visibility="collapsed",
        )
    with col_p2:
        specific_focus = st.text_input(
            "Any specific focus?",
            placeholder="e.g., Compare kidney vs liver performance",
            key="specific_focus",
            label_visibility="collapsed",
        )

    # ── Run button ──
    st.markdown("<br>", unsafe_allow_html=True)
    run_clicked = st.button("🚀 Run Analysis", type="primary", use_container_width=True)

    # ── Analysis logic ──
    if run_clicked and uploaded_file is not None:
        with st.spinner("Loading and processing CSV..."):
            df = load_and_aggregate_csv(uploaded_file)

        if df is None:
            return

        # Classify ads
        classified_df = classify_ads(
            df.copy(),
            winner_min_roas=winner_min_roas,
            winner_min_spend=winner_min_spend,
            loser_max_roas=loser_max_roas,
            loser_min_spend=loser_min_spend,
        )

        top50_df = get_top50_by_spend(df)
        if "classification" not in top50_df.columns:
            top50_df = classify_ads(
                top50_df,
                winner_min_roas=winner_min_roas,
                winner_min_spend=winner_min_spend,
                loser_max_roas=loser_max_roas,
                loser_min_spend=loser_min_spend,
            )

        # ── Header metrics ──
        st.markdown("---")
        render_header_metrics(df, classified_df)
        st.markdown("<br>", unsafe_allow_html=True)

        # ══════════════════════════════════════════════════════════════════
        # ANALYTICS DASHBOARD — Dimension Tables
        # ══════════════════════════════════════════════════════════════════
        st.markdown('<h2 style="color:#fafafa;">📊 Analytics Dashboard</h2>', unsafe_allow_html=True)

        # Compute dimension breakdowns for both sections
        classified_dims = compute_all_dimensions(classified_df)
        top50_dims = compute_all_dimensions(top50_df)

        tab_a, tab_b = st.tabs(["Section A — Classified Ads", "Section B — Top 50 by Spend"])

        # Default-expanded dimensions
        expanded_dims = {"pain_point", "root_cause", "mechanism"}

        with tab_a:
            for dim in DIMENSIONS:
                label = DIMENSION_LABELS.get(dim, dim)
                expanded = dim in expanded_dims
                with st.expander(f"📈 {label}", expanded=expanded):
                    html = build_dimension_html_table(
                        classified_dims.get(dim, []),
                        label,
                        "Section A",
                    )
                    st.markdown(html, unsafe_allow_html=True)

        with tab_b:
            for dim in DIMENSIONS:
                label = DIMENSION_LABELS.get(dim, dim)
                expanded = dim in expanded_dims
                with st.expander(f"📈 {label}", expanded=expanded):
                    html = build_dimension_html_table(
                        top50_dims.get(dim, []),
                        label,
                        "Section B",
                    )
                    st.markdown(html, unsafe_allow_html=True)

        # ══════════════════════════════════════════════════════════════════
        # PATTERN ANALYSIS — Claude API
        # ══════════════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown('<h2 style="color:#fafafa;">🔍 Pattern Insights</h2>', unsafe_allow_html=True)

        classified_data = _prepare_classified_data(classified_df)
        top50_data = _prepare_top50_data(top50_df)

        with st.spinner("Running multi-dimensional pattern analysis with Claude..."):
            try:
                loop = asyncio.new_event_loop()
                results = loop.run_until_complete(
                    analyze_patterns(
                        classified_data=classified_data,
                        top50_data=top50_data,
                        brand_name=brand_name,
                        priority_focus=priority_focus,
                        specific_focus=specific_focus,
                    )
                )
                loop.close()
            except Exception as e:
                st.error(f"Pattern analysis failed: {e}")
                results = {"insights": [], "top_patterns": [], "learnings": [], "hypotheses": []}

        # Store results in session state for PDF export
        st.session_state["last_results"] = results
        st.session_state["last_classified_df"] = classified_df
        st.session_state["last_top50_df"] = top50_df
        st.session_state["last_classified_dims"] = classified_dims
        st.session_state["last_top50_dims"] = top50_dims
        st.session_state["last_brand_name"] = brand_name
        st.session_state["last_run_date"] = datetime.now().isoformat()

        # ── Insight cards ──
        insights = results.get("insights", [])
        if insights:
            for i, insight in enumerate(insights, 1):
                render_insight_card(insight, i)
        else:
            st.markdown('<div style="color:#888; padding:16px;">No pattern insights generated.</div>', unsafe_allow_html=True)

        # ══════════════════════════════════════════════════════════════════
        # TOP 5 STRONGEST PATTERNS — Expansion Opportunities
        # ══════════════════════════════════════════════════════════════════
        top_patterns = results.get("top_patterns", [])
        if top_patterns:
            st.markdown("---")
            st.markdown('<h2 style="color:#fafafa;">🏆 Top 5 Strongest Patterns — Expansion Opportunities</h2>', unsafe_allow_html=True)
            for i, pat in enumerate(top_patterns[:5], 1):
                render_top_pattern_card(pat, i)

        # ══════════════════════════════════════════════════════════════════
        # LEARNINGS
        # ══════════════════════════════════════════════════════════════════
        learnings = results.get("learnings", [])
        if learnings:
            st.markdown("---")
            st.markdown('<h2 style="color:#fafafa;">📚 Learnings</h2>', unsafe_allow_html=True)
            for learning in learnings:
                render_learning_card(learning)

        # ══════════════════════════════════════════════════════════════════
        # HYPOTHESES
        # ══════════════════════════════════════════════════════════════════
        hypotheses = results.get("hypotheses", [])
        if hypotheses:
            st.markdown("---")
            st.markdown('<h2 style="color:#fafafa;">🧪 Hypotheses to Test</h2>', unsafe_allow_html=True)
            for hyp in hypotheses:
                render_hypothesis_card(hyp)

        # ══════════════════════════════════════════════════════════════════
        # PDF EXPORT
        # ══════════════════════════════════════════════════════════════════
        st.markdown("---")
        if st.button("📄 Export PDF Report", use_container_width=True):
            with st.spinner("Generating PDF..."):
                try:
                    from creative_feedback_loop.report_generator import generate_pdf_report
                    pdf_path = asyncio.get_event_loop().run_until_complete(
                        generate_pdf_report(
                            brand_name=brand_name,
                            classified_df=classified_df,
                            top50_df=top50_df,
                            classified_dims=classified_dims,
                            top50_dims=top50_dims,
                            results=results,
                        )
                    )
                    if pdf_path and Path(pdf_path).exists():
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                "⬇️ Download PDF",
                                data=f.read(),
                                file_name=f"creative_feedback_{brand_name or 'report'}_{datetime.now().strftime('%Y%m%d')}.pdf",
                                mime="application/pdf",
                            )
                    else:
                        st.error("PDF generation failed — file not created.")
                except ImportError:
                    st.error("PDF export requires playwright and jinja2. Run: pip install playwright jinja2 && playwright install chromium")
                except Exception as e:
                    st.error(f"PDF export failed: {e}")

    elif run_clicked and uploaded_file is None:
        st.warning("Please upload a CSV file first.")

    # CHANGE 3: No comparison section shown — only show when previous run with different dates exists
    # Check session state for previous run
    if "previous_run_date" in st.session_state and "last_run_date" in st.session_state:
        prev = st.session_state.get("previous_run_date", "")
        curr = st.session_state.get("last_run_date", "")
        if prev and curr and prev != curr:
            # Only render comparison if we have two different runs
            st.markdown("---")
            st.markdown('<h2 style="color:#fafafa;">🔄 Run Comparison</h2>', unsafe_allow_html=True)
            st.markdown(f'<div style="color:#ccc;">Comparing run from {clean_markdown(prev)} to {clean_markdown(curr)}</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
