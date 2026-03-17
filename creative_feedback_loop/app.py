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

_LEAKED_HEADERS = re.compile(
    r'^\s*(HYPOTHESES|LEARNINGS|OPPORTUNITIES|EXECUTIVE SUMMARY|INSIGHTS)\s*:?\s*$',
    re.IGNORECASE | re.MULTILINE,
)

def clean_markdown(text: str) -> str:
    """Strip raw markdown markers and leaked section headers from Claude output."""
    if not isinstance(text, str):
        return str(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold**
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)  # ## headers
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', text)  # *italic*
    text = re.sub(r'\*{2,}', '', text)              # strip remaining ** runs (unbalanced)
    text = text.replace('$', '&#36;')               # escape $ to prevent LaTeX rendering
    text = re.sub(r'^\s*\d+\.\s*', '', text)        # strip leading "1. " numbering
    text = _LEAKED_HEADERS.sub('', text)
    return text.strip()


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


def classify_ads(
    df: pd.DataFrame,
    winner_roas: float,
    winner_min_spend: float,
    loser_roas: float,
    loser_min_spend: float,
) -> pd.DataFrame:
    """Classify ads as winner/loser/untested based on separate thresholds.

    Winner: ROAS >= winner_roas AND spend >= winner_min_spend
    Loser: ROAS < loser_roas AND spend >= loser_min_spend (ROAS=0 with spend = loser)
    Untested: spend below both thresholds
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

    # Classify with separate winner/loser thresholds
    def _classify(row):
        spend = row["_spend"]
        roas = row["_roas"]
        # Winner: meets winner spend threshold AND ROAS >= winner ROAS
        if spend >= winner_min_spend and roas >= winner_roas:
            return "winner"
        # Loser: meets loser spend threshold AND ROAS < loser ROAS
        # ROAS=0 with spend above loser_min = LOSER (spent money, got nothing)
        if spend >= loser_min_spend and roas < loser_roas:
            return "loser"
        return "untested"

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

    # ── Input Form — Numbered Steps ────────────────────────────────────────
    with st.form("analysis_form"):
        # Step 1: Upload CSV
        st.markdown(
            '<div style="background:#1e1e2e; padding:12px 16px; border-radius:8px; margin-bottom:12px;">'
            '<span style="background:#e91e8c; color:white; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:8px;">Step 1</span>'
            '<span style="color:#fafafa; font-weight:600;">Upload Meta CSV File</span>'
            '</div>', unsafe_allow_html=True)
        uploaded_file = st.file_uploader(
            "CSV File", type=["csv"], label_visibility="collapsed",
        )

        # Step 2: Brand Name
        st.markdown(
            '<div style="background:#1e1e2e; padding:12px 16px; border-radius:8px; margin-bottom:12px;">'
            '<span style="background:#e91e8c; color:white; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:8px;">Step 2</span>'
            '<span style="color:#fafafa; font-weight:600;">Brand Name on ClickUp</span>'
            '<span style="color:#888; font-size:12px; margin-left:8px;">(Optional — enables script reading)</span>'
            '</div>', unsafe_allow_html=True)
        brand_name = st.text_input("Brand Name", placeholder="e.g., Sculptique", label_visibility="collapsed")

        # Step 3: Winner Criteria
        st.markdown(
            '<div style="background:#1e1e2e; padding:12px 16px; border-radius:8px; margin-bottom:12px;">'
            '<span style="background:#e91e8c; color:white; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:8px;">Step 3</span>'
            '<span style="color:#fafafa; font-weight:600;">Winning Ad Criteria</span>'
            '</div>', unsafe_allow_html=True)
        wc1, wc2 = st.columns(2)
        with wc1:
            winner_roas = st.number_input("Winner ROAS (>=)", value=1.0, step=0.1, min_value=0.0, key="winner_roas")
        with wc2:
            winner_min_spend = st.number_input("Winner Min Spend ($)", value=5000.0, step=500.0, min_value=0.0, key="winner_spend")

        # Step 4: Loser Criteria
        st.markdown(
            '<div style="background:#1e1e2e; padding:12px 16px; border-radius:8px; margin-bottom:12px;">'
            '<span style="background:#e91e8c; color:white; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:8px;">Step 4</span>'
            '<span style="color:#fafafa; font-weight:600;">Loser Ad Criteria</span>'
            '</div>', unsafe_allow_html=True)
        lc1, lc2 = st.columns(2)
        with lc1:
            loser_roas = st.number_input("Loser ROAS (<)", value=1.0, step=0.1, min_value=0.0, key="loser_roas")
        with lc2:
            loser_min_spend = st.number_input("Loser Min Spend ($)", value=100.0, step=50.0, min_value=0.0, key="loser_spend")

        # Step 5: Analysis Priority
        st.markdown(
            '<div style="background:#1e1e2e; padding:12px 16px; border-radius:8px; margin-bottom:12px;">'
            '<span style="background:#e91e8c; color:white; padding:2px 8px; border-radius:4px; font-size:12px; margin-right:8px;">Step 5</span>'
            '<span style="color:#fafafa; font-weight:600;">Analysis Priority</span>'
            '<span style="color:#888; font-size:12px; margin-left:8px;">(Optional)</span>'
            '</div>', unsafe_allow_html=True)
        from creative_feedback_loop.context.operator_priorities import render_priority_input, build_priority_prompt
        priority, custom_context = render_priority_input()

        st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
        run_analysis = st.form_submit_button("\U0001f680 Run Analysis", use_container_width=True)

    if not run_analysis:
        # Show previous notes if brand is set
        if brand_name:
            from creative_feedback_loop.context.operator_notes import render_previous_notes
            render_previous_notes(_slugify(brand_name))
        return

    if not uploaded_file:
        st.error("Please upload a CSV file.")
        return

    # Brand name is optional — enables ClickUp script reading
    if not brand_name:
        brand_name = ""  # Proceed without ClickUp integration

    # ── Process CSV ───────────────────────────────────────────────────────
    import tempfile
    import os as _os
    try:
        raw_bytes = uploaded_file.getvalue()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as _tmp:
            _tmp.write(raw_bytes)
            _tmp_path = _tmp.name
        raw_df = pd.read_csv(_tmp_path)
    except Exception as e:
        st.error(f"Failed to read CSV: {e}")
        return

    # Auto-detect date range (Part 6)
    csv_start, csv_end = detect_date_range(raw_df)
    st.markdown(
        f'<div style="background:#1a1a2e; padding:12px 16px; border-radius:8px; margin-bottom:16px;">'
        f'<span style="color:#fafafa;">CSV covers: <b>{csv_start} — {csv_end}</b></span></div>',
        unsafe_allow_html=True,
    )

    # Show previous notes
    from creative_feedback_loop.context.operator_notes import render_previous_notes, render_notes_input, save_notes_to_run
    previous_notes_text = render_previous_notes(_slugify(brand_name)) or ""

    # ── Aggregate rows by ad name before classifying (FIX 1 — critical) ──
    # Meta CSVs have one row per ad per ad set. Without aggregation, the same
    # ad appears 20+ times with tiny per-row spend → all classified "untested".
    from creative_feedback_loop.csv_aggregator import load_and_aggregate_csv
    try:
        aggregated_ads, agg_stats = load_and_aggregate_csv(_tmp_path)
    except Exception as e:
        st.error(f"CSV aggregation failed: {e}")
        _os.unlink(_tmp_path)
        return
    _os.unlink(_tmp_path)

    # Find script/format columns in raw CSV and build per-ad-name lookups
    _script_col_raw = find_script_column(raw_df)
    _name_col_raw = find_ad_name_column(raw_df)
    _format_col_raw = find_ad_format_column(raw_df)

    script_lookup: dict = {}
    format_lookup: dict = {}
    if _name_col_raw:
        for _, _row in raw_df.iterrows():
            _key = str(_row[_name_col_raw]).strip()
            if not _key or _key.lower() == "nan":
                continue
            if _script_col_raw and _key not in script_lookup:
                _val = _row.get(_script_col_raw)
                if pd.notna(_val):
                    script_lookup[_key] = str(_val)
            if _format_col_raw and _key not in format_lookup:
                _val = _row.get(_format_col_raw)
                if pd.notna(_val):
                    format_lookup[_key] = str(_val)

    # Classify aggregated ads using blended ROAS and total spend (separate winner/loser thresholds)
    def _classify_agg(spend: float, roas: float) -> str:
        if spend >= winner_min_spend and roas >= winner_roas:
            return "winner"
        if spend >= loser_min_spend and roas < loser_roas:
            return "loser"
        return "untested"

    # Build DataFrame of unique ads with aggregated metrics
    _agg_rows = []
    for _ad in aggregated_ads:
        _agg_rows.append({
            "_agg_name": _ad.ad_name,
            "_spend": _ad.total_spend,
            "_roas": _ad.blended_roas,
            "_status": _classify_agg(_ad.total_spend, _ad.blended_roas),
            "_script": script_lookup.get(_ad.ad_name, ""),
            "_format": format_lookup.get(_ad.ad_name, ""),
        })
    df = pd.DataFrame(_agg_rows)
    name_col = "_agg_name"
    script_col = "_script"
    format_col = "_format"

    if not _script_col_raw:
        st.info("No script/copy column found — extracting components from ad naming conventions.")

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
    from creative_feedback_loop.extraction.naming_parser import parse_ad_naming, merge_extractions

    classified_df = df[df["_status"].isin(["winner", "loser"])].copy()

    ads_for_extraction = []
    for idx, row in classified_df.iterrows():
        ad_name = str(row[name_col]) if name_col else f"Ad_{idx}"
        ad = {
            "ad_name": ad_name,
            "script_text": str(row[script_col]) if script_col and pd.notna(row[script_col]) else "",
            "status": row["_status"],
            "spend": float(row["_spend"]),
            "roas": float(row["_roas"]),
        }
        if format_col and format_col in row.index and pd.notna(row[format_col]) and str(row[format_col]):
            ad["format_override"] = str(row[format_col])
        # Always parse naming convention as baseline extraction
        ad["naming_extraction"] = parse_ad_naming(ad_name)
        ads_for_extraction.append(ad)

    # Top 50 by spend (ALL ads, not just classified)
    top50_df = get_top_50_by_spend(df)
    top50_ads = []
    for idx, row in top50_df.iterrows():
        ad_name = str(row[name_col]) if name_col else f"Ad_{idx}"
        ad = {
            "ad_name": ad_name,
            "script_text": str(row[script_col]) if script_col and pd.notna(row[script_col]) else "",
            "status": row["_status"] if "_status" in row.index else "untested",
            "spend": float(row["_spend"]) if "_spend" in row.index else 0,
            "roas": float(row["_roas"]) if "_roas" in row.index else 0,
        }
        if format_col and format_col in row.index and pd.notna(row[format_col]) and str(row[format_col]):
            ad["format_override"] = str(row[format_col])
        ad["naming_extraction"] = parse_ad_naming(ad_name)
        top50_ads.append(ad)

    st.markdown(
        f'<p style="color:#999;">Prepared {len(ads_for_extraction)} classified ads + '
        f'{len(top50_ads)} top-50 ads for analysis</p>',
        unsafe_allow_html=True,
    )

    # ── Deep Extraction (Part 2) ──────────────────────────────────────────
    has_scripts = any(ad["script_text"].strip() for ad in ads_for_extraction)

    # Create a shared event loop for all async operations
    loop = asyncio.new_event_loop()

    if has_scripts and os.environ.get("ANTHROPIC_API_KEY"):
        st.markdown('<h3 style="color:#fafafa;">Extracting ad components with Claude...</h3>', unsafe_allow_html=True)

        try:
            from creative_feedback_loop.extraction.script_component_extractor import extract_batch

            progress_bar = st.progress(0)
            status_text = st.empty()

            def update_progress(completed, total):
                progress_bar.progress(completed / total)
                status_text.markdown(
                    f'<p style="color:#999;">Extracted {completed}/{total} ads</p>',
                    unsafe_allow_html=True,
                )

            extractions = loop.run_until_complete(
                extract_batch(ads_for_extraction, progress_callback=update_progress)
            )

            for i, ext in enumerate(extractions):
                # Merge Claude extraction with naming extraction (Claude takes priority)
                merged = merge_extractions(ads_for_extraction[i]["naming_extraction"], ext)
                if ads_for_extraction[i].get("format_override") and not merged.get("ad_format"):
                    merged["ad_format"] = ads_for_extraction[i]["format_override"]
                ads_for_extraction[i]["extraction"] = merged

            status_text.markdown(
                '<p style="color:#999;">Extracting top 50 by spend...</p>',
                unsafe_allow_html=True,
            )
            top50_extractions = loop.run_until_complete(
                extract_batch(top50_ads)
            )
            for i, ext in enumerate(top50_extractions):
                merged = merge_extractions(top50_ads[i]["naming_extraction"], ext)
                if top50_ads[i].get("format_override") and not merged.get("ad_format"):
                    merged["ad_format"] = top50_ads[i]["format_override"]
                top50_ads[i]["extraction"] = merged

            progress_bar.empty()
            status_text.empty()
        except Exception as e:
            st.error(f"Claude extraction error: {e}")
            logger.exception("Claude extraction failed")
            # Fall back to naming-only extraction
            for ad in ads_for_extraction:
                if "extraction" not in ad:
                    ad["extraction"] = ad["naming_extraction"]
            for ad in top50_ads:
                if "extraction" not in ad:
                    ad["extraction"] = ad["naming_extraction"]
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.warning("ANTHROPIC_API_KEY not set. Using naming convention extraction only.")
        # Use naming extraction as primary (no Claude)
        for ad in ads_for_extraction:
            extraction = ad["naming_extraction"].copy()
            if ad.get("format_override") and not extraction.get("ad_format"):
                extraction["ad_format"] = ad["format_override"]
            ad["extraction"] = extraction
        for ad in top50_ads:
            extraction = ad["naming_extraction"].copy()
            if ad.get("format_override") and not extraction.get("ad_format"):
                extraction["ad_format"] = ad["format_override"]
            ad["extraction"] = extraction

    # ── Structured Dashboard (Part 1) — Section A ─────────────────────────
    from creative_feedback_loop.dashboard.structured_splits import render_dashboard

    dashboard_data = {}
    try:
        st.markdown("---")
        dashboard_data = render_dashboard(ads_for_extraction, "Section A — Classified Ads")
    except Exception as e:
        st.error(f"Dashboard error (Section A): {e}")
        logger.exception("Section A dashboard failed")

    # ── Structured Dashboard — Section B (Top 50) ─────────────────────────
    top50_dashboard_data = {}
    try:
        st.markdown("---")
        top50_dashboard_data = render_dashboard(top50_ads, "Section B — Top 50 by Spend")
    except Exception as e:
        st.error(f"Dashboard error (Section B): {e}")
        logger.exception("Section B dashboard failed")

    # ── Load Previous Run for Comparison ──────────────────────────────────
    from creative_feedback_loop.context.run_store import load_previous_run, render_comparison

    previous_run = load_previous_run(brand_name)
    if previous_run:
        try:
            st.markdown("---")
            prev_dashboard = previous_run.get("dashboard_data", {})
            prev_date = previous_run.get("run_timestamp", "")[:10]
            if prev_dashboard:
                render_comparison(dashboard_data, prev_dashboard, prev_date)
        except Exception as e:
            st.error(f"Comparison error: {e}")
            logger.exception("Run comparison failed")

    # ── Pattern Analysis (Part 8) ─────────────────────────────────────────
    pattern_results = None
    has_extraction_data = any(
        ad.get("extraction", {}).get("pain_point") or ad.get("extraction", {}).get("ad_format")
        for ad in ads_for_extraction
    )

    if os.environ.get("ANTHROPIC_API_KEY") and has_extraction_data:
        try:
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
                    f'<p style="color:#fafafa;">{clean_markdown(pattern_results["executive_summary"])}</p></div>',
                    unsafe_allow_html=True,
                )

            for i, insight in enumerate(pattern_results.get("insights", []), 1):
                title = clean_markdown(insight.get("title", ""))
                detail = clean_markdown(insight.get("detail", ""))
                score = insight.get("score", 0)
                w = insight.get("winner_count")
                l = insight.get("loser_count")
                r = insight.get("avg_roas")
                conf = insight.get("confidence", "Based on Claude analysis")
                verified = insight.get("stats_verified", False)

                if verified and w is not None and (w or l):
                    stats_line = f"Winners: {w} | Losers: {l} | Avg ROAS: {r:.2f}x"
                else:
                    stats_line = ""

                score_badge = f" — Score: {score}/100" if score else ""

                st.markdown(
                    f'<div style="background:#1e1e2e; border-radius:12px; padding:20px; margin-bottom:16px; border:1px solid #333;">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">'
                    f'<span style="background:#e91e8c; color:white; padding:4px 12px; border-radius:6px; font-size:13px; font-weight:600;">PATTERN #{i}{score_badge}</span>'
                    f'<span style="color:#888; font-size:12px;">{stats_line}</span>'
                    f'</div>'
                    f'<h3 style="color:#fafafa; margin:0 0 8px 0; font-size:16px;">{title}</h3>'
                    f'<div style="color:#ccc; font-size:14px; line-height:1.6; margin-bottom:12px;">{detail}</div>'
                    f'<div style="display:flex; gap:12px;">'
                    f'<div style="flex:1; background:#262730; padding:10px; border-radius:6px;">'
                    f'<div style="color:#888; font-size:11px; text-transform:uppercase; margin-bottom:4px;">Confidence</div>'
                    f'<div style="color:#fafafa; font-size:13px;">{conf}</div>'
                    f'</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # Top 5 Strongest Patterns
            top_insights = sorted(
                [ins for ins in pattern_results.get("insights", []) if ins.get("detail")],
                key=lambda x: (x.get("score", 0), 1 if x.get("stats_verified") else 0),
                reverse=True
            )[:5]
            if top_insights:
                st.markdown("---")
                st.markdown('<h2 style="color:#fafafa;">🏆 Top 5 Strongest Patterns — Expansion Opportunities</h2>', unsafe_allow_html=True)
                for rank, ins in enumerate(top_insights, 1):
                    t = clean_markdown(ins.get("title", ""))
                    d = clean_markdown(ins.get("detail", ""))
                    r = ins.get("avg_roas")
                    roas_str = f"{r:.2f}x ROAS" if r else ""
                    st.markdown(
                        f'<div style="background:#1e1e2e; border-radius:12px; padding:20px; margin-bottom:16px; border:1px solid #f59e0b40;">'
                        f'<div style="border-left:4px solid #f59e0b; padding-left:12px; margin-bottom:12px;">'
                        f'<h3 style="color:#fafafa; margin:0; font-size:16px;">#{rank}: {t}</h3>'
                        f'<p style="color:#ccc; font-size:13px; margin:4px 0;">{roas_str}</p>'
                        f'</div>'
                        f'<div style="color:#ccc; font-size:14px; line-height:1.6;">{d}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # Learnings — collapsible
            if pattern_results.get("learnings"):
                with st.expander(f"📚 Learnings ({len(pattern_results['learnings'])})", expanded=False):
                    for learning in pattern_results["learnings"]:
                        text = clean_markdown(learning)
                        if " — " in text:
                            parts = text.split(" — ", 1)
                            l_title, l_detail = parts[0], parts[1]
                        elif ": " in text and len(text.split(": ", 1)[0]) < 60:
                            parts = text.split(": ", 1)
                            l_title, l_detail = parts[0], parts[1]
                        else:
                            sentences = text.split(". ", 1)
                            l_title = sentences[0]
                            l_detail = sentences[1] if len(sentences) > 1 else ""
                        st.markdown(
                            f'<div style="background:#1e1e2e; border-left:3px solid #3b82f6; padding:12px 16px; margin-bottom:8px; border-radius:0 8px 8px 0;">'
                            f'<div style="color:#fafafa; font-weight:600; font-size:14px;">{l_title}</div>'
                            f'{"<div style=\"color:#ccc; font-size:13px; margin-top:4px;\">" + l_detail + "</div>" if l_detail else ""}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

            # Hypotheses — collapsible
            if pattern_results.get("hypotheses"):
                with st.expander(f"💡 Hypotheses ({len(pattern_results['hypotheses'])})", expanded=False):
                    for hypothesis in pattern_results["hypotheses"]:
                        text = clean_markdown(hypothesis)
                        # Parse structured hypothesis: "What — Expected: X — Based on: Y — Risk: Z"
                        h_title = text
                        h_detail = ""
                        if " — " in text:
                            parts = text.split(" — ", 1)
                            h_title = parts[0]
                            h_detail = parts[1]
                        elif ": " in text and len(text.split(": ", 1)[0]) < 60:
                            parts = text.split(": ", 1)
                            h_title = parts[0]
                            h_detail = parts[1]
                        st.markdown(
                            f'<div style="background:#1e1e2e; border-left:3px solid #f59e0b; padding:12px 16px; margin-bottom:8px; border-radius:0 8px 8px 0;">'
                            f'<div style="color:#fafafa; font-weight:600; font-size:14px;">{h_title}</div>'
                            f'{"<div style=\"color:#ccc; font-size:13px; margin-top:4px;\">" + h_detail + "</div>" if h_detail else ""}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
        except Exception as e:
            st.error(f"Pattern analysis error: {e}")
            logger.exception("Pattern analysis failed")

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
        "winner_roas": winner_roas,
        "winner_min_spend": winner_min_spend,
        "loser_roas": loser_roas,
        "loser_min_spend": loser_min_spend,
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
