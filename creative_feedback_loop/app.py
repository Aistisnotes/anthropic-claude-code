"""Creative Feedback Loop Analyzer — Streamlit Application.

Full pipeline:
1. CSV upload/aggregation (ad performance data)
2. ClickUp integration (optional — pull ad scripts/copy)
3. Classification (winner/loser/untested based on ROAS + spend thresholds)
4. Naming parser (extract batch, version, format from ad names)
5. Script component extraction (Claude-powered dimension extraction)
6. Strategic opportunity analysis (Claude-powered scoring)
7. Visual card dashboard (dark theme, no tables)

Run: streamlit run creative_feedback_loop/app.py
"""

from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime
from typing import Any, Optional

import pandas as pd
import streamlit as st

from creative_feedback_loop.naming_parser import parse_ad_name, group_ads_by_batch
from creative_feedback_loop.dashboard.structured_splits import (
    render_header_metrics,
    render_compact_summary,
    render_detailed_breakdown,
    render_opportunities_section,
    render_drift_alerts,
    compute_dimension_summary,
    compute_detailed_breakdown,
)

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Creative Feedback Loop",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dark Theme CSS ───────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .stMetric { background: #1e1e2e; border-radius: 8px; padding: 12px; }
    .stMetric label { color: #9ca3af !important; }
    .stMetric [data-testid="stMetricValue"] { color: #fafafa !important; }
    .stExpander { background: #1e1e2e; border-radius: 8px; }
    .stExpander summary { color: #fafafa !important; }
    h1, h2, h3, h4, h5, h6 { color: #fafafa !important; }
    p, li, span { color: #ccc; }
    .stSelectbox label, .stMultiSelect label, .stNumberInput label,
    .stTextInput label, .stRadio label, .stFileUploader label { color: #fafafa !important; }
    .stButton > button {
        background: #3b82f6; color: white; border: none; border-radius: 6px;
        padding: 8px 24px; font-weight: 600;
    }
    .stButton > button:hover { background: #2563eb; }
    div[data-testid="stSidebar"] { background: #1e1e2e; }
    div[data-testid="stSidebar"] label { color: #fafafa !important; }
</style>
""", unsafe_allow_html=True)


# ── Session State Initialization ─────────────────────────────────────────────
if "pipeline_complete" not in st.session_state:
    st.session_state.pipeline_complete = False
if "ads_df" not in st.session_state:
    st.session_state.ads_df = None
if "top50_df" not in st.session_state:
    st.session_state.top50_df = None
if "opportunities" not in st.session_state:
    st.session_state.opportunities = []
if "drift_alerts" not in st.session_state:
    st.session_state.drift_alerts = []
if "dimension_summaries" not in st.session_state:
    st.session_state.dimension_summaries = []
if "top50_summaries" not in st.session_state:
    st.session_state.top50_summaries = []
if "detailed_breakdowns" not in st.session_state:
    st.session_state.detailed_breakdowns = {}
if "extraction_done" not in st.session_state:
    st.session_state.extraction_done = False
if "learnings" not in st.session_state:
    st.session_state.learnings = ""
if "hypotheses" not in st.session_state:
    st.session_state.hypotheses = ""


# ── Sidebar: Inputs ─────────────────────────────────────────────────────────
st.sidebar.title("🎯 Creative Feedback Loop")
st.sidebar.markdown("---")

# CSV Upload
st.sidebar.subheader("1. Upload Ad Data")
recent_csv = st.sidebar.file_uploader(
    "Recent Ads CSV",
    type=["csv"],
    help="CSV with columns: ad_name, spend, revenue, roas, impressions (and optionally: ad_text/script)",
    key="recent_csv",
)

top50_csv = st.sidebar.file_uploader(
    "Top 50 Ads CSV (optional)",
    type=["csv"],
    help="Historical best-performing ads for drift comparison",
    key="top50_csv",
)

st.sidebar.markdown("---")

# Classification Thresholds
st.sidebar.subheader("2. Classification")
roas_threshold = st.sidebar.number_input(
    "Winner ROAS Threshold",
    min_value=0.5,
    max_value=10.0,
    value=1.0,
    step=0.1,
    help="Ads with ROAS >= this are winners",
)
min_spend = st.sidebar.number_input(
    "Min Spend for Classification ($)",
    min_value=0,
    max_value=100000,
    value=500,
    step=100,
    help="Ads below this spend are 'untested'",
)

st.sidebar.markdown("---")

# Operator Priority
st.sidebar.subheader("3. Analysis Priority")
priority = st.sidebar.selectbox(
    "What matters most?",
    ["General", "Spend Volume", "Efficiency", "New Angles"],
    help="Shapes the entire Claude analysis",
)

st.sidebar.markdown("---")

# ClickUp Integration (optional)
st.sidebar.subheader("4. ClickUp Integration")
clickup_enabled = st.sidebar.checkbox("Enable ClickUp", value=False)
clickup_api_key = ""
clickup_list_id = ""
if clickup_enabled:
    clickup_api_key = st.sidebar.text_input("ClickUp API Key", type="password")
    clickup_list_id = st.sidebar.text_input("ClickUp List ID")

st.sidebar.markdown("---")

# Claude Extraction
st.sidebar.subheader("5. Claude Extraction")
run_extraction = st.sidebar.checkbox(
    "Run Claude Script Extraction",
    value=False,
    help="Extract pain points, root causes, mechanisms from ad scripts using Claude. Requires ad_text column and ANTHROPIC_API_KEY.",
)
claude_model = st.sidebar.selectbox(
    "Claude Model",
    ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
    index=0,
)

st.sidebar.markdown("---")

# Operator Notes
st.sidebar.subheader("6. Operator Notes")
operator_notes = st.sidebar.text_area(
    "Notes for this analysis run",
    placeholder="e.g., Testing new kidney angles this week...",
    height=80,
)


# ── Helper Functions ─────────────────────────────────────────────────────────

def load_csv(file) -> pd.DataFrame:
    """Load, aggregate by ad name, and normalize CSV file.

    Meta CSVs have one row per ad per ad set. Without aggregation the same ad
    appears 20+ times with tiny per-row spend and gets classified as untested.
    load_and_aggregate_csv groups rows by ad name and sums spend/revenue,
    producing blended ROAS before any classification happens (FIX 1).
    """
    import tempfile, os as _os
    from creative_feedback_loop.csv_aggregator import load_and_aggregate_csv

    # Save uploaded file to temp path (csv_aggregator needs a file path)
    raw_bytes = file.getvalue() if hasattr(file, "getvalue") else file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as _tmp:
        _tmp.write(raw_bytes)
        _tmp_path = _tmp.name

    try:
        aggregated_ads, _ = load_and_aggregate_csv(_tmp_path)
    finally:
        _os.unlink(_tmp_path)

    # Build normalized DataFrame from aggregated ads
    rows = [
        {
            "ad_name": ad.ad_name,
            "spend": ad.total_spend,
            "revenue": ad.total_revenue,
            "roas": ad.blended_roas,
            "impressions": ad.total_impressions,
            "conversions": ad.total_conversions,
            "_row_count": ad.row_count,
        }
        for ad in aggregated_ads
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    return df


def classify_ads(df: pd.DataFrame, roas_thresh: float, min_spend_val: float) -> pd.DataFrame:
    """Classify ads as winner/loser/untested."""
    conditions = []
    labels = []

    # Untested: spend below threshold
    mask_untested = df["spend"] < min_spend_val if "spend" in df.columns else pd.Series([False] * len(df))

    # Winners: ROAS >= threshold AND spend >= min
    mask_winner = (df["roas"] >= roas_thresh) & (~mask_untested) if "roas" in df.columns else pd.Series([False] * len(df))

    # Losers: ROAS < threshold AND spend >= min
    mask_loser = (df["roas"] < roas_thresh) & (~mask_untested) if "roas" in df.columns else pd.Series([False] * len(df))

    df["classification"] = "untested"
    df.loc[mask_winner, "classification"] = "winner"
    df.loc[mask_loser, "classification"] = "loser"

    return df


def apply_naming_parser(df: pd.DataFrame) -> pd.DataFrame:
    """Apply naming parser to extract components from ad names."""
    if "ad_name" not in df.columns:
        return df

    batches = []
    versions = []
    formats = []
    for name in df["ad_name"]:
        parsed = parse_ad_name(str(name))
        batches.append(parsed.batch)
        versions.append(parsed.version)
        formats.append(parsed.format_code or "Unknown")

    df["batch"] = batches
    df["version"] = versions
    df["format_code"] = formats

    return df


async def run_claude_extraction(df: pd.DataFrame, model: str) -> pd.DataFrame:
    """Run Claude extraction on ads with ad_text column."""
    from creative_feedback_loop.extraction.script_component_extractor import extract_batch

    if "ad_text" not in df.columns:
        st.warning("No 'ad_text' column found. Skipping Claude extraction.")
        return df

    ads_with_text = df[df["ad_text"].notna() & (df["ad_text"].str.len() > 20)]
    if ads_with_text.empty:
        st.warning("No ads with sufficient text for extraction.")
        return df

    ads_list = [
        {"name": row["ad_name"], "text": row["ad_text"]}
        for _, row in ads_with_text.iterrows()
    ]

    progress = st.progress(0, text="Extracting script components with Claude...")
    results = await extract_batch(ads_list, model=model)
    progress.progress(100, text="Extraction complete!")

    # Merge results back
    extraction_cols = [
        "pain_point", "pain_point_category", "root_cause", "root_cause_depth",
        "mechanism", "mechanism_depth", "avatar", "avatar_category",
        "awareness_level", "hook_type", "ad_format",
    ]

    for col in extraction_cols:
        if col not in df.columns:
            df[col] = None

    for result in results:
        ad_name = result.get("ad_name", "")
        mask = df["ad_name"] == ad_name
        if mask.any():
            for col in extraction_cols:
                val = result.get(col)
                if val and str(val).lower() not in ("not specified", "unknown", ""):
                    df.loc[mask, col] = val

    return df


async def fetch_clickup_tasks(api_key: str, list_id: str) -> list[dict]:
    """Fetch tasks from ClickUp list."""
    import httpx

    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_key}
    params = {"page": 0, "include_closed": "true"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            return data.get("tasks", [])
        else:
            st.error(f"ClickUp API error: {response.status_code}")
            return []


def merge_clickup_data(df: pd.DataFrame, tasks: list[dict]) -> pd.DataFrame:
    """Merge ClickUp task data (ad scripts) into the dataframe."""
    task_map = {}
    for task in tasks:
        name = task.get("name", "")
        description = task.get("description", "") or ""
        # Try to match task name to ad name
        task_map[name.strip()] = description

    if "ad_text" not in df.columns:
        df["ad_text"] = None

    for idx, row in df.iterrows():
        ad_name = str(row.get("ad_name", ""))
        # Try exact match then partial
        if ad_name in task_map:
            df.at[idx, "ad_text"] = task_map[ad_name]
        else:
            for task_name, desc in task_map.items():
                if ad_name in task_name or task_name in ad_name:
                    df.at[idx, "ad_text"] = desc
                    break

    return df


def compute_all_summaries(
    df: pd.DataFrame,
    winner_mask: pd.Series,
    loser_mask: pd.Series,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Compute compact summaries and detailed breakdowns for all dimensions."""
    dimensions = {
        "Pain Point": "pain_point_category",
        "Root Cause": "root_cause_depth",
        "Mechanism": "mechanism_depth",
        "Ad Format": "ad_format",
        "Avatar": "avatar_category",
        "Awareness": "awareness_level",
        "Hook Type": "hook_type",
        "Format Code": "format_code",
    }

    summaries = []
    breakdowns = {}

    for label, col in dimensions.items():
        if col in df.columns:
            summary = compute_dimension_summary(df, col, label, winner_mask, loser_mask)
            summaries.append(summary)
            breakdown = compute_detailed_breakdown(df, col, winner_mask, loser_mask)
            if breakdown:
                breakdowns[label] = breakdown

    # Sort summaries by absolute delta
    summaries.sort(key=lambda x: abs(x.get("delta", 0)), reverse=True)

    return summaries, breakdowns


def generate_pdf_report(
    ads_data: dict,
    summaries: list[dict],
    opportunities: list[dict],
    drift_alerts: list[dict],
    operator_notes: str,
) -> bytes:
    """Generate PDF report from analysis results."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.lib.colors import HexColor

        buffer = io.BytesIO()
        c = pdf_canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Title
        c.setFont("Helvetica-Bold", 20)
        c.drawString(1 * inch, height - 1 * inch, "Creative Feedback Loop Report")
        c.setFont("Helvetica", 10)
        c.drawString(1 * inch, height - 1.3 * inch, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        y = height - 1.8 * inch

        # Metrics
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1 * inch, y, "Performance Summary")
        y -= 20
        c.setFont("Helvetica", 10)
        metrics = [
            f"Total Ads: {ads_data.get('total', 0)}",
            f"Winners: {ads_data.get('winners', 0)}",
            f"Losers: {ads_data.get('losers', 0)}",
            f"Total Spend: ${ads_data.get('total_spend', 0):,.0f}",
            f"Avg ROAS: {ads_data.get('avg_roas', 0):.2f}x",
        ]
        for m in metrics:
            c.drawString(1.2 * inch, y, m)
            y -= 14

        # Dimension Summary
        y -= 10
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1 * inch, y, "Dimension Summary")
        y -= 20
        c.setFont("Helvetica", 9)
        for s in summaries[:8]:
            delta = s.get("delta", 0)
            signal = "HIGH" if delta > 20 else "MED" if delta > 10 else "BASE" if delta >= 0 else "AVOID"
            line = f"[{signal}] {s['dimension']}: {s['top_value']} | Win: {s['winner_pct']:.0f}% | Lose: {s['loser_pct']:.0f}% | Delta: {delta:+.0f}%"
            c.drawString(1.2 * inch, y, line[:90])
            y -= 13
            if y < 1 * inch:
                c.showPage()
                y = height - 1 * inch

        # Opportunities
        y -= 10
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1 * inch, y, "Strategic Opportunities")
        y -= 20

        for opp in opportunities[:7]:
            if opp.get("type") == "expensive_mistake":
                continue
            c.setFont("Helvetica-Bold", 10)
            c.drawString(1.2 * inch, y, f"[{opp.get('score', 0)}/100] {opp.get('title', '')[:70]}")
            y -= 14
            c.setFont("Helvetica", 9)
            evidence = opp.get("evidence", "")[:120]
            c.drawString(1.4 * inch, y, evidence)
            y -= 18
            if y < 1 * inch:
                c.showPage()
                y = height - 1 * inch

        # Operator Notes
        if operator_notes:
            y -= 10
            c.setFont("Helvetica-Bold", 12)
            c.drawString(1 * inch, y, "Operator Notes")
            y -= 16
            c.setFont("Helvetica", 9)
            for line in operator_notes.split("\n")[:5]:
                c.drawString(1.2 * inch, y, line[:90])
                y -= 13

        c.save()
        buffer.seek(0)
        return buffer.read()

    except ImportError:
        return b"PDF generation requires reportlab. Install with: pip install reportlab"


# ── Main Content ─────────────────────────────────────────────────────────────

st.title("🎯 Creative Feedback Loop Analyzer")
st.markdown(
    '<p style="color: #9ca3af; margin-top: -10px;">Compact visual dashboard with scored strategic opportunities backed by spend/ROAS data.</p>',
    unsafe_allow_html=True,
)

# ── Run Pipeline ─────────────────────────────────────────────────────────────
if recent_csv is not None:
    run_btn = st.button("🚀 Run Analysis Pipeline", use_container_width=True)

    if run_btn:
        with st.spinner("Running analysis pipeline..."):

            # Step 1: Load CSV
            st.info("📊 Loading CSV data...")
            df = load_csv(recent_csv)
            st.success(f"Loaded {len(df)} ads from CSV")

            # Step 2: ClickUp integration
            if clickup_enabled and clickup_api_key and clickup_list_id:
                st.info("📋 Fetching ClickUp tasks...")
                tasks = asyncio.run(fetch_clickup_tasks(clickup_api_key, clickup_list_id))
                if tasks:
                    df = merge_clickup_data(df, tasks)
                    st.success(f"Merged {len(tasks)} ClickUp tasks")

            # Step 3: Classification
            st.info("🏷️ Classifying ads...")
            df = classify_ads(df, roas_threshold, min_spend)

            # Step 4: Naming parser
            st.info("🔍 Parsing ad names...")
            df = apply_naming_parser(df)

            # Step 5: Claude extraction (optional)
            if run_extraction:
                st.info("🤖 Running Claude script extraction...")
                df = asyncio.run(run_claude_extraction(df, claude_model))
                st.session_state.extraction_done = True

            # Step 6: Load Top 50 if provided
            top50 = None
            if top50_csv is not None:
                st.info("📊 Loading Top 50 data...")
                top50 = load_csv(top50_csv)
                top50 = classify_ads(top50, roas_threshold, min_spend)
                top50 = apply_naming_parser(top50)
                if run_extraction and "ad_text" in top50.columns:
                    top50 = asyncio.run(run_claude_extraction(top50, claude_model))

            # Step 7: Compute summaries
            st.info("📈 Computing dimension summaries...")
            winner_mask = df["classification"] == "winner"
            loser_mask = df["classification"] == "loser"
            summaries, breakdowns = compute_all_summaries(df, winner_mask, loser_mask)

            top50_summaries_data = []
            top50_breakdowns = {}
            if top50 is not None:
                t50_win = top50["classification"] == "winner"
                t50_lose = top50["classification"] == "loser"
                top50_summaries_data, top50_breakdowns = compute_all_summaries(top50, t50_win, t50_lose)

            # Step 8: Strategic opportunities (Claude)
            has_extraction_cols = any(
                col in df.columns for col in [
                    "pain_point_category", "root_cause_depth", "mechanism_depth",
                ]
            )

            opportunities = []
            if has_extraction_cols:
                st.info("🧠 Generating strategic opportunities with Claude...")
                opportunities = asyncio.run(
                    generate_strategic_opportunities(
                        df, winner_mask, loser_mask,
                        priority=priority,
                        model=claude_model,
                    )
                )
            else:
                st.warning("No extracted dimensions available. Upload data with dimension columns or enable Claude extraction.")

            # Step 9: Drift alerts (if top 50 available)
            drift_alerts = []
            if top50 is not None and has_extraction_cols:
                st.info("📊 Generating drift alerts...")
                t50_win = top50["classification"] == "winner"
                t50_lose = top50["classification"] == "loser"
                drift_alerts = asyncio.run(
                    generate_drift_alerts(
                        df, top50, winner_mask, loser_mask,
                        t50_win, t50_lose, model=claude_model,
                    )
                )

            # Store results in session state
            st.session_state.ads_df = df
            st.session_state.top50_df = top50
            st.session_state.opportunities = opportunities
            st.session_state.drift_alerts = drift_alerts
            st.session_state.dimension_summaries = summaries
            st.session_state.top50_summaries = top50_summaries_data
            st.session_state.detailed_breakdowns = breakdowns
            st.session_state.top50_breakdowns = top50_breakdowns
            st.session_state.pipeline_complete = True

            st.success("✅ Pipeline complete!")

    # Import here to avoid circular imports
    from creative_feedback_loop.analyzer.pattern_analyzer import (
        generate_strategic_opportunities,
        generate_drift_alerts,
    )

# ── Display Results ──────────────────────────────────────────────────────────
if st.session_state.pipeline_complete and st.session_state.ads_df is not None:
    df = st.session_state.ads_df
    winner_mask = df["classification"] == "winner"
    loser_mask = df["classification"] == "loser"
    untested_mask = df["classification"] == "untested"

    # ── 1. HEADER METRICS ROW ────────────────────────────────────────────────
    ads_data = {
        "total": len(df),
        "winners": int(winner_mask.sum()),
        "losers": int(loser_mask.sum()),
        "untested": int(untested_mask.sum()),
        "total_spend": float(df["spend"].sum()) if "spend" in df.columns else 0,
        "avg_roas": float(df["roas"].mean()) if "roas" in df.columns else 0,
    }
    render_header_metrics(ads_data)

    st.markdown("---")

    # ── 2. COMPACT DIMENSION SUMMARY ─────────────────────────────────────────
    summaries = st.session_state.dimension_summaries
    if summaries:
        render_compact_summary(summaries, title="RECENT ADS — DIMENSION SUMMARY")

    st.markdown("---")

    # ── 3. STRATEGIC OPPORTUNITIES ───────────────────────────────────────────
    opportunities = st.session_state.opportunities
    if opportunities:
        render_opportunities_section(opportunities)

    st.markdown("---")

    # ── 4. TOP 50 COMPACT SUMMARY ────────────────────────────────────────────
    top50_summaries = st.session_state.top50_summaries
    if top50_summaries:
        render_compact_summary(top50_summaries, title="TOP 50 PROVEN ADS — DIMENSION SUMMARY")
        st.markdown("---")

    # ── 5. DRIFT ALERTS ──────────────────────────────────────────────────────
    drift_alerts = st.session_state.drift_alerts
    if drift_alerts:
        render_drift_alerts(drift_alerts)
        st.markdown("---")

    # ── 6. EXPANDABLE SECTIONS ───────────────────────────────────────────────

    # Full Dimension Breakdown
    breakdowns = st.session_state.detailed_breakdowns
    if breakdowns:
        render_detailed_breakdown(breakdowns, "Full Dimension Breakdown (Recent)")

    top50_breakdowns = st.session_state.get("top50_breakdowns", {})
    if top50_breakdowns:
        render_detailed_breakdown(top50_breakdowns, "Full Dimension Breakdown (Top 50)")

    # Individual Ad Details
    with st.expander("📋 Individual Ad Details", expanded=False):
        # Show ads as styled HTML cards, not dataframe
        for cls_label, cls_color in [("winner", "#22c55e"), ("loser", "#ef4444"), ("untested", "#6b7280")]:
            cls_ads = df[df["classification"] == cls_label]
            if cls_ads.empty:
                continue

            st.markdown(
                f'<div style="color: {cls_color}; font-size: 16px; font-weight: 700; margin: 16px 0 8px 0; text-transform: uppercase;">{cls_label}S ({len(cls_ads)})</div>',
                unsafe_allow_html=True,
            )

            rows_html = ""
            for _, row in cls_ads.head(50).iterrows():
                spend = row.get("spend", 0)
                roas = row.get("roas", 0)
                name = row.get("ad_name", "")
                pain = row.get("pain_point_category", "")
                fmt = row.get("format_code", row.get("ad_format", ""))
                bg = "#262730"

                rows_html += f"""<tr style="background: {bg};">
<td style="padding: 6px 10px; color: #fafafa; font-weight: 500;">{name}</td>
<td style="padding: 6px 10px; color: #fafafa; text-align: right;">${spend:,.0f}</td>
<td style="padding: 6px 10px; color: {'#22c55e' if roas >= 1 else '#ef4444'}; text-align: center; font-weight: 600;">{roas:.2f}x</td>
<td style="padding: 6px 10px; color: #ccc;">{pain}</td>
<td style="padding: 6px 10px; color: #ccc;">{fmt}</td>
</tr>"""

            table_html = f"""<table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
<thead><tr style="background: #1e1e2e;">
<th style="padding: 8px 10px; color: #fafafa; text-align: left;">Ad Name</th>
<th style="padding: 8px 10px; color: #fafafa; text-align: right;">Spend</th>
<th style="padding: 8px 10px; color: #fafafa; text-align: center;">ROAS</th>
<th style="padding: 8px 10px; color: #fafafa; text-align: left;">Pain Point</th>
<th style="padding: 8px 10px; color: #fafafa; text-align: left;">Format</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>"""
            st.markdown(table_html, unsafe_allow_html=True)

    # Learnings
    with st.expander("💡 Learnings", expanded=False):
        learnings_text = st.text_area(
            "Key Learnings from this analysis",
            value=st.session_state.learnings,
            height=150,
            key="learnings_input",
            placeholder="Document what you learned from this analysis...",
        )
        if learnings_text != st.session_state.learnings:
            st.session_state.learnings = learnings_text

    # Hypotheses
    with st.expander("🧪 Hypotheses with Script Outlines", expanded=False):
        hypotheses_text = st.text_area(
            "Hypotheses to test",
            value=st.session_state.hypotheses,
            height=150,
            key="hypotheses_input",
            placeholder="e.g., Hypothesis: Molecular kidney scripts with UGC format will outperform at $50k+ spend...",
        )
        if hypotheses_text != st.session_state.hypotheses:
            st.session_state.hypotheses = hypotheses_text

    # Operator Notes
    with st.expander("📝 Operator Notes", expanded=False):
        if operator_notes:
            st.markdown(
                f'<div style="background: #1e1e2e; border-radius: 8px; padding: 16px; color: #ccc; line-height: 1.6;">{operator_notes}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<p style="color: #6b7280;">No operator notes provided. Add notes in the sidebar.</p>',
                unsafe_allow_html=True,
            )

    # ── 7. PDF EXPORT ────────────────────────────────────────────────────────
    st.markdown("---")
    if st.button("📄 Export PDF Report", use_container_width=True):
        with st.spinner("Generating PDF..."):
            pdf_bytes = generate_pdf_report(
                ads_data,
                summaries,
                opportunities,
                drift_alerts,
                operator_notes,
            )
            st.download_button(
                label="⬇️ Download PDF",
                data=pdf_bytes,
                file_name=f"creative_feedback_loop_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
            )

else:
    # No data loaded — show instructions
    st.markdown("""
    <div style="background: #1e1e2e; border-radius: 12px; padding: 32px; margin: 40px 0; text-align: center;">
        <div style="color: #fafafa; font-size: 24px; font-weight: 700; margin-bottom: 16px;">
            Upload Your Ad Data to Get Started
        </div>
        <div style="color: #9ca3af; font-size: 15px; line-height: 1.8; max-width: 600px; margin: 0 auto;">
            <p><b>Required CSV columns:</b> ad_name, spend, revenue (or roas)</p>
            <p><b>Optional columns:</b> impressions, clicks, ad_text (for Claude extraction)</p>
            <p><b>Optional:</b> Upload a Top 50 CSV for drift comparison</p>
            <p><b>Optional:</b> Enable ClickUp to pull ad scripts automatically</p>
        </div>
        <div style="color: #6b7280; font-size: 13px; margin-top: 20px;">
            Use the sidebar to upload CSVs and configure the analysis.
        </div>
    </div>
    """, unsafe_allow_html=True)
