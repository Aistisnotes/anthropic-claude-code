"""Creative Feedback Loop — Streamlit App

Standalone Streamlit app running on port 8503.
Structured dashboards, deep extraction, operator context, run storage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Creative Feedback Loop",
    layout="wide",
    initial_sidebar_state="collapsed",
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
RUNS_DIR = PROJECT_ROOT / "output" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# ── Dark Mode CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .stMarkdown, .stText, p, span, label, .stSelectbox label,
    .stTextArea label, .stNumberInput label, .stFileUploader label {
        color: #fafafa !important;
    }
    h1, h2, h3, h4 { color: #fafafa !important; }
    .stMetric label { color: #999 !important; }
    .stMetric [data-testid="stMetricValue"] { color: #e91e8c !important; }
    div[data-testid="stExpander"] { border-color: #333 !important; }
    .stButton > button {
        background-color: #e91e8c !important;
        color: white !important;
        border: none !important;
        font-weight: 600 !important;
    }
    .stButton > button:hover {
        background-color: #c2185b !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #1a1a2e !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Auth Gate ─────────────────────────────────────────────────────────────────
def check_auth() -> bool:
    """Check TOOL_PASSWORD env var for authentication."""
    password = os.environ.get("TOOL_PASSWORD", "")
    if not password:
        return True  # No password set = skip auth

    if st.session_state.get("authenticated"):
        return True

    st.markdown('<h1 style="color:#fafafa; text-align:center;">Creative Feedback Loop</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#999; text-align:center;">Enter password to continue</p>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        pwd = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", use_container_width=True):
            if pwd == password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password")
    return False


# ── CSV Processing ────────────────────────────────────────────────────────────
def detect_date_range(df: pd.DataFrame) -> tuple[str, str]:
    """Auto-detect date range from CSV columns.

    Looks for 'Reporting starts' and 'Reporting ends' columns.
    Returns (start_date_str, end_date_str).
    """
    start_col = None
    end_col = None

    for col in df.columns:
        col_lower = col.lower().strip()
        if "reporting" in col_lower and "start" in col_lower:
            start_col = col
        elif "reporting" in col_lower and "end" in col_lower:
            end_col = col

    if start_col and end_col:
        try:
            starts = pd.to_datetime(df[start_col], errors="coerce").dropna()
            ends = pd.to_datetime(df[end_col], errors="coerce").dropna()
            if not starts.empty and not ends.empty:
                min_date = starts.min().strftime("%B %d, %Y")
                max_date = ends.max().strftime("%B %d, %Y")
                return min_date, max_date
        except Exception:
            pass

    return "Unknown", "Unknown"


def classify_ads(df: pd.DataFrame, roas_threshold: float, spend_threshold: float) -> pd.DataFrame:
    """Classify ads as winner/loser/untested based on thresholds.

    Looks for ROAS and spend columns in the CSV.
    """
    df = df.copy()

    # Find ROAS column
    roas_col = None
    for col in df.columns:
        if "roas" in col.lower():
            roas_col = col
            break

    # Find spend column
    spend_col = None
    for col in df.columns:
        col_lower = col.lower()
        if "spend" in col_lower or "amount spent" in col_lower or "cost" in col_lower:
            spend_col = col
            break

    if roas_col is None or spend_col is None:
        st.warning("Could not find ROAS or Spend columns in CSV. All ads marked as untested.")
        df["_status"] = "untested"
        df["_roas"] = 0.0
        df["_spend"] = 0.0
        return df

    # Clean numeric columns
    df["_roas"] = pd.to_numeric(df[roas_col].astype(str).str.replace("[,$]", "", regex=True), errors="coerce").fillna(0)
    df["_spend"] = pd.to_numeric(df[spend_col].astype(str).str.replace("[,$]", "", regex=True), errors="coerce").fillna(0)

    # Classify
    def _classify(row):
        if row["_spend"] < spend_threshold:
            return "untested"
        elif row["_roas"] >= roas_threshold:
            return "winner"
        else:
            return "loser"

    df["_status"] = df.apply(_classify, axis=1)
    return df


def find_script_column(df: pd.DataFrame) -> Optional[str]:
    """Find the column containing ad scripts/briefs."""
    candidates = [
        "script", "brief", "copy", "ad copy", "ad_copy", "primary_text",
        "primary text", "body", "text", "content", "description", "message",
    ]
    for col in df.columns:
        if col.lower().strip() in candidates:
            return col

    # Fallback: look for longest text columns
    for col in df.columns:
        if df[col].dtype == "object":
            avg_len = df[col].astype(str).str.len().mean()
            if avg_len > 200:
                return col
    return None


def find_ad_name_column(df: pd.DataFrame) -> Optional[str]:
    """Find the column containing ad names/IDs."""
    candidates = [
        "ad name", "ad_name", "name", "ad id", "ad_id", "creative name",
        "creative_name", "id", "ad set name",
    ]
    for col in df.columns:
        if col.lower().strip() in candidates:
            return col
    return df.columns[0] if len(df.columns) > 0 else None


def find_ad_format_column(df: pd.DataFrame) -> Optional[str]:
    """Find ad format column from CSV or ClickUp fields."""
    candidates = ["format", "ad format", "ad_format", "creative format", "type", "ad type"]
    for col in df.columns:
        if col.lower().strip() in candidates:
            return col
    return None


def get_top_50_by_spend(df: pd.DataFrame) -> pd.DataFrame:
    """Get top 50 ads by spend."""
    return df.nlargest(50, "_spend") if "_spend" in df.columns else df.head(50)


# ── Main App ──────────────────────────────────────────────────────────────────
def main():
    if not check_auth():
        return

    st.markdown('<h1 style="color:#fafafa;">Creative Feedback Loop</h1>', unsafe_allow_html=True)

    # ── Input Form ────────────────────────────────────────────────────────
    with st.form("analysis_form"):
        st.markdown('<p style="color:#fafafa; font-weight:600;">Upload Performance CSV</p>', unsafe_allow_html=True)

        uploaded_file = st.file_uploader(
            "CSV File",
            type=["csv"],
            label_visibility="collapsed",
        )

        col1, col2 = st.columns(2)
        with col1:
            brand_name = st.text_input("Brand Name", placeholder="e.g., Sculptique")
        with col2:
            st.markdown("")  # spacer

        st.markdown("---")

        # Thresholds
        col3, col4 = st.columns(2)
        with col3:
            roas_threshold = st.number_input("Winner ROAS Threshold", value=1.0, step=0.1, min_value=0.0)
        with col4:
            spend_threshold = st.number_input("Min Spend for Classification ($)", value=100.0, step=50.0, min_value=0.0)

        st.markdown("---")

        # Operator priority (Part 3)
        from creative_feedback_loop.context.operator_priorities import render_priority_input, build_priority_prompt
        priority, custom_context = render_priority_input()

        st.markdown("---")

        run_analysis = st.form_submit_button("Run Analysis", use_container_width=True)

    if not run_analysis:
        # Show previous notes if brand is set
        if brand_name:
            from creative_feedback_loop.context.operator_notes import render_previous_notes
            render_previous_notes(_slugify(brand_name))
        return

    if not uploaded_file:
        st.error("Please upload a CSV file.")
        return

    if not brand_name:
        st.error("Please enter a brand name.")
        return

    # ── Process CSV ───────────────────────────────────────────────────────
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Failed to read CSV: {e}")
        return

    # Auto-detect date range (Part 6)
    csv_start, csv_end = detect_date_range(df)
    st.markdown(
        f'<div style="background:#1a1a2e; padding:12px 16px; border-radius:8px; margin-bottom:16px;">'
        f'<span style="color:#fafafa;">CSV covers: <b>{csv_start} — {csv_end}</b></span></div>',
        unsafe_allow_html=True,
    )

    # Show previous notes
    from creative_feedback_loop.context.operator_notes import render_previous_notes, render_notes_input, save_notes_to_run
    previous_notes_text = render_previous_notes(_slugify(brand_name)) or ""

    # Classify ads
    df = classify_ads(df, roas_threshold, spend_threshold)

    # Find columns
    script_col = find_script_column(df)
    name_col = find_ad_name_column(df)
    format_col = find_ad_format_column(df)

    if not script_col:
        st.warning("No script/copy column found in CSV. Extraction will be limited.")

    # Classification counts
    counts = df["_status"].value_counts().to_dict()
    winners_count = counts.get("winner", 0)
    losers_count = counts.get("loser", 0)
    untested_count = counts.get("untested", 0)
    total_spend = df["_spend"].sum() if "_spend" in df.columns else 0

    # ── Header Metrics ────────────────────────────────────────────────────
    st.markdown("---")
    mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
    mcol1.metric("Total Ads", len(df))
    mcol2.metric("Winners", winners_count)
    mcol3.metric("Losers", losers_count)
    mcol4.metric("Untested", untested_count)
    mcol5.metric("Total Spend", f"${total_spend:,.0f}")

    # ── Prepare ads for extraction ────────────────────────────────────────
    classified_df = df[df["_status"].isin(["winner", "loser"])].copy()

    ads_for_extraction = []
    for _, row in classified_df.iterrows():
        ad = {
            "ad_name": str(row[name_col]) if name_col else f"Ad_{_}",
            "script_text": str(row[script_col]) if script_col and pd.notna(row[script_col]) else "",
            "status": row["_status"],
            "spend": float(row["_spend"]) if "_spend" in row.index else 0,
            "roas": float(row["_roas"]) if "_roas" in row.index else 0,
        }
        # Override format from CSV if available
        if format_col and pd.notna(row[format_col]):
            ad["format_override"] = str(row[format_col])
        ads_for_extraction.append(ad)

    # Top 50 by spend
    top50_df = get_top_50_by_spend(df)
    top50_ads = []
    for _, row in top50_df.iterrows():
        ad = {
            "ad_name": str(row[name_col]) if name_col else f"Ad_{_}",
            "script_text": str(row[script_col]) if script_col and pd.notna(row[script_col]) else "",
            "status": row["_status"] if "_status" in row.index else "untested",
            "spend": float(row["_spend"]) if "_spend" in row.index else 0,
            "roas": float(row["_roas"]) if "_roas" in row.index else 0,
        }
        if format_col and pd.notna(row[format_col]):
            ad["format_override"] = str(row[format_col])
        top50_ads.append(ad)

    # ── Deep Extraction (Part 2) ──────────────────────────────────────────
    has_scripts = any(ad["script_text"].strip() for ad in ads_for_extraction)

    # Create a shared event loop for all async operations
    loop = asyncio.new_event_loop()

    if has_scripts and os.environ.get("ANTHROPIC_API_KEY"):
        st.markdown('<h3 style="color:#fafafa;">Extracting ad components...</h3>', unsafe_allow_html=True)

        from creative_feedback_loop.extraction.script_component_extractor import extract_batch

        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(completed, total):
            progress_bar.progress(completed / total)
            status_text.markdown(
                f'<p style="color:#999;">Extracted {completed}/{total} ads</p>',
                unsafe_allow_html=True,
            )

        # Extract classified ads
        extractions = loop.run_until_complete(
            extract_batch(ads_for_extraction, progress_callback=update_progress)
        )

        for i, ext in enumerate(extractions):
            ads_for_extraction[i]["extraction"] = ext
            # Apply format override if available
            if ads_for_extraction[i].get("format_override") and not ext.get("ad_format"):
                ext["ad_format"] = ads_for_extraction[i]["format_override"]

        # Extract top 50
        status_text.markdown(
            '<p style="color:#999;">Extracting top 50 by spend...</p>',
            unsafe_allow_html=True,
        )
        top50_extractions = loop.run_until_complete(
            extract_batch(top50_ads)
        )
        for i, ext in enumerate(top50_extractions):
            top50_ads[i]["extraction"] = ext
            if top50_ads[i].get("format_override") and not ext.get("ad_format"):
                ext["ad_format"] = top50_ads[i]["format_override"]

        progress_bar.empty()
        status_text.empty()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.warning("ANTHROPIC_API_KEY not set. Skipping Claude extraction.")
        # Set empty extractions
        for ad in ads_for_extraction:
            ad["extraction"] = _build_basic_extraction(ad)
        for ad in top50_ads:
            ad["extraction"] = _build_basic_extraction(ad)

    # ── Structured Dashboard (Part 1) — Section A ─────────────────────────
    from creative_feedback_loop.dashboard.structured_splits import render_dashboard

    st.markdown("---")
    dashboard_data = render_dashboard(ads_for_extraction, "Section A — Classified Ads")

    # ── Structured Dashboard — Section B (Top 50) ─────────────────────────
    st.markdown("---")
    top50_dashboard_data = render_dashboard(top50_ads, "Section B — Top 50 by Spend")

    # ── Load Previous Run for Comparison ──────────────────────────────────
    from creative_feedback_loop.context.run_store import load_previous_run, render_comparison

    previous_run = load_previous_run(brand_name)
    if previous_run:
        st.markdown("---")
        prev_dashboard = previous_run.get("dashboard_data", {})
        prev_date = previous_run.get("run_timestamp", "")[:10]
        if prev_dashboard:
            render_comparison(dashboard_data, prev_dashboard, prev_date)

    # ── Pattern Analysis (Part 8) ─────────────────────────────────────────
    pattern_results = None
    if os.environ.get("ANTHROPIC_API_KEY") and has_scripts:
        st.markdown("---")
        st.markdown('<h3 style="color:#fafafa;">Running pattern analysis...</h3>', unsafe_allow_html=True)

        from creative_feedback_loop.analyzer.pattern_analyzer import analyze_patterns
        from creative_feedback_loop.context.operator_priorities import build_priority_prompt

        priority_prompt = build_priority_prompt(priority, custom_context)

        pattern_results = loop.run_until_complete(
            analyze_patterns(
                ads_for_extraction,
                dashboard_data,
                priority_prompt=priority_prompt,
                previous_notes=previous_notes_text,
            )
        )

        # Display insights
        st.markdown("---")
        st.markdown('<h2 style="color:#fafafa;">Pattern Insights</h2>', unsafe_allow_html=True)

        if pattern_results.get("executive_summary"):
            st.markdown(
                f'<div style="background:#1a1a2e; border-left:3px solid #e91e8c; padding:16px; '
                f'border-radius:0 8px 8px 0; margin-bottom:16px;">'
                f'<p style="color:#fafafa;">{pattern_results["executive_summary"]}</p></div>',
                unsafe_allow_html=True,
            )

        for insight in pattern_results.get("insights", []):
            baseline_badge = '<span style="background:#333; color:#999; padding:2px 8px; border-radius:4px; font-size:11px; margin-left:8px;">BASELINE</span>' if insight.get("is_baseline") else ""
            st.markdown(
                f'<div style="background:#1a1a2e; border-left:3px solid #e91e8c; padding:12px 16px; '
                f'margin-bottom:10px; border-radius:0 6px 6px 0;">'
                f'<p style="color:#fafafa; font-weight:700;">{insight.get("title", "")}{baseline_badge}</p>'
                f'<p style="color:#ccc; font-size:13px; margin-top:4px;">{insight.get("detail", "")}</p>'
                f'<p style="color:#888; font-size:11px; margin-top:4px;">Winners: {insight.get("winner_count", 0)} | '
                f'Losers: {insight.get("loser_count", 0)} | '
                f'Avg ROAS: {insight.get("avg_roas", 0)}x | '
                f'Confidence: {insight.get("confidence", "")}</p></div>',
                unsafe_allow_html=True,
            )

        # Learnings — collapsible
        if pattern_results.get("learnings"):
            with st.expander("Learnings", expanded=False):
                for learning in pattern_results["learnings"]:
                    st.markdown(f'<p style="color:#fafafa; margin-bottom:8px;">• {learning}</p>', unsafe_allow_html=True)

        # Hypotheses — collapsible
        if pattern_results.get("hypotheses"):
            with st.expander("Hypotheses", expanded=False):
                for hypothesis in pattern_results["hypotheses"]:
                    st.markdown(f'<p style="color:#fafafa; margin-bottom:8px;">• {hypothesis}</p>', unsafe_allow_html=True)

    # ── Operator Notes (Part 4) ───────────────────────────────────────────
    notes = render_notes_input()

    # ── Save Run (Part 5) ─────────────────────────────────────────────────
    from creative_feedback_loop.context.run_store import save_run

    classification_counts = {
        "winners": winners_count,
        "losers": losers_count,
        "untested": untested_count,
    }
    threshold_config = {
        "roas_threshold": roas_threshold,
        "spend_threshold": spend_threshold,
    }

    run_path = save_run(
        brand_name=brand_name,
        csv_start_date=csv_start,
        csv_end_date=csv_end,
        classification_counts=classification_counts,
        threshold_config=threshold_config,
        dashboard_data=dashboard_data,
        top50_dashboard_data=top50_dashboard_data,
        operator_priority=priority,
        operator_notes=notes,
        pattern_results=pattern_results,
    )

    st.session_state["current_run_path"] = str(run_path)

    # Save notes button
    if notes:
        if st.button("Save Notes"):
            save_notes_to_run(run_path, notes)
            st.success("Notes saved!")

    # ── PDF Export (Part 7) ───────────────────────────────────────────────
    st.markdown("---")
    if st.button("Export PDF Report", use_container_width=True):
        with st.spinner("Generating PDF..."):
            from creative_feedback_loop.reporter.pdf_generator import generate_pdf

            try:
                pdf_path = loop.run_until_complete(
                    generate_pdf(
                        brand_name=brand_name,
                        csv_start=csv_start,
                        csv_end=csv_end,
                        classification_counts=classification_counts,
                        total_spend=total_spend,
                        dashboard_data=dashboard_data,
                        top50_dashboard_data=top50_dashboard_data,
                        pattern_results=pattern_results,
                        previous_run=previous_run,
                        priority=priority,
                    )
                )
                st.success(f"PDF saved: {pdf_path}")

                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "Download PDF",
                        data=f.read(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        use_container_width=True,
                    )
            except Exception as e:
                st.error(f"PDF generation failed: {e}")


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:40]


def _build_basic_extraction(ad: dict) -> dict:
    """Build a basic extraction from ad metadata when Claude is unavailable."""
    return {
        "hooks": [],
        "body_copy_summary": "",
        "pain_point": "",
        "symptoms": [],
        "root_cause": {"depth": "", "chain": ""},
        "mechanism": {"ump": "", "ums": ""},
        "avatar": {"behavior": "", "impact": "", "root_cause_connection": "", "why_previous_failed": ""},
        "ad_format": ad.get("format_override", ""),
        "awareness_level": "",
        "emotional_triggers": [],
        "language_patterns": [],
        "lead_type": "",
        "cta_type": "",
        "hook_type": "",
    }


if __name__ == "__main__":
    main()
