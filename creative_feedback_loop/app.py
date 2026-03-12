"""Creative Feedback Loop Analyzer — Streamlit App

Single-form pipeline: brand name + CSV upload → full analysis in one click.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Creative Feedback Loop",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dark mode CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    .stSidebar { background-color: #1A1D24; }
    .stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp td, .stApp th {
        color: #fafafa !important;
    }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #fafafa !important; }
    .stTextInput input, .stNumberInput input, .stSelectbox select {
        background-color: #1A1D24 !important;
        color: #fafafa !important;
    }
    .stButton > button {
        background-color: #6C63FF !important;
        color: #fafafa !important;
        border: none !important;
        border-radius: 8px !important;
    }
    .stButton > button:hover {
        background-color: #5A52E0 !important;
    }
    .stTabs [data-baseweb="tab"] { color: #fafafa !important; }
    .stTabs [aria-selected="true"] { border-bottom-color: #6C63FF !important; }
    [data-testid="stMetricValue"] { color: #6C63FF !important; }
    [data-testid="stMetricLabel"] { color: #aaa !important; }
    .streamlit-expanderHeader { color: #fafafa !important; }
    [data-testid="stFileUploader"] label { color: #fafafa !important; }
    .stProgress > div > div { background-color: #6C63FF !important; }
    .stAlert { background-color: #1A1D24 !important; }
</style>
""", unsafe_allow_html=True)


# ── Login gate ────────────────────────────────────────────────────────────────

def check_login() -> bool:
    """Simple password gate. Set CFL_PASSWORD env var to enable."""
    password = os.environ.get("CFL_PASSWORD", "")
    if not password:
        return True  # No password set = open access

    if st.session_state.get("authenticated"):
        return True

    st.markdown('<h1 style="color:#fafafa;text-align:center;">🔄 Creative Feedback Loop</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#aaa;text-align:center;">Enter password to continue</p>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pwd = st.text_input("Password", type="password", key="login_pwd")
        if st.button("Login", use_container_width=True):
            if pwd == password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid password")
    return False


# ── Session state init ────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "analysis_done": False,
        "tasks": None,
        "space_name": None,
        "list_name": None,
        "csv_ads": None,
        "csv_total_spend": 0.0,
        "match_summary": None,
        "classification": None,
        "scripts": None,
        "pattern_analysis": None,
        "hypothesis_report": None,
        "top_performers_data": None,
        "pipeline_log": [],
        "brand_name": "",
        "analysis_error": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown('<h2 style="color:#fafafa;">🔄 Creative Feedback</h2>', unsafe_allow_html=True)
        st.markdown('<p style="color:#aaa;font-size:13px;">Find winning patterns in your creative</p>', unsafe_allow_html=True)
        st.markdown("---")

        page = st.radio("Navigation", ["Dashboard", "Reports History"], label_visibility="collapsed")

        if st.session_state.get("analysis_done"):
            st.markdown("---")
            brand = st.session_state.get("brand_name", "")
            space = st.session_state.get("space_name", "")
            clf = st.session_state.get("classification")
            if clf:
                st.markdown(f'<p style="color:#aaa;font-size:12px;">Brand: <strong style="color:#fafafa;">{brand}</strong></p>', unsafe_allow_html=True)
                st.markdown(f'<p style="color:#aaa;font-size:12px;">Space: {space}</p>', unsafe_allow_html=True)
                st.markdown(f'<p style="color:#4CAF50;font-size:12px;">✅ {len(clf.winners)} winners</p>', unsafe_allow_html=True)
                st.markdown(f'<p style="color:#F44336;font-size:12px;">❌ {len(clf.losers)} losers</p>', unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🔄 Reset", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    return page


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_full_pipeline(brand_name, csv_bytes, date_range, winner_roas, loser_roas, min_spend):
    """Run the complete analysis pipeline. All progress shown via pipeline_log."""
    log = []

    def add_log(level, msg):
        log.append((level, msg))
        st.session_state["pipeline_log"] = log[:]

    try:
        # Step 1: Pull ClickUp tasks
        add_log("info", f"Searching ClickUp for '{brand_name}'...")
        from analyzer.clickup_client import find_brand_and_pull_tasks
        space_name, list_name, tasks = find_brand_and_pull_tasks(brand_name, date_range_days=date_range, fetch_comments=True)

        if not space_name:
            add_log("error", f"Could not find ClickUp space matching '{brand_name}'")
            st.session_state["analysis_error"] = f"Could not find ClickUp space matching '{brand_name}'"
            return
        if not list_name:
            add_log("error", f"Found space '{space_name}' but no Creative Team or Media Buying list")
            st.session_state["analysis_error"] = "No Creative Team or Media Buying list found"
            return

        add_log("success", f"Found '{space_name}' → {list_name} — {len(tasks)} tasks")
        st.session_state["tasks"] = tasks
        st.session_state["space_name"] = space_name
        st.session_state["list_name"] = list_name

        # Step 2: Parse CSV
        add_log("info", "Parsing Meta Ads Manager CSV...")
        from analyzer.csv_matcher import parse_meta_csv
        csv_ads, total_spend = parse_meta_csv(csv_bytes)
        add_log("success", f"Parsed {len(csv_ads)} ads — Total spend: ${total_spend:,.2f}")
        st.session_state["csv_ads"] = csv_ads
        st.session_state["csv_total_spend"] = total_spend

        # Step 3: Match
        add_log("info", "Matching ClickUp tasks to CSV ads...")
        from analyzer.csv_matcher import match_tasks_to_csv, get_top_account_ads
        match_summary = match_tasks_to_csv(tasks, csv_ads, total_spend)
        add_log("success", f"Matched {match_summary.total_matched} tasks | Unmatched: {match_summary.total_unmatched_tasks} tasks, {match_summary.total_unmatched_csv} CSV rows")

        if match_summary.total_matched + match_summary.total_unmatched_csv > 0:
            rate = match_summary.total_matched / (match_summary.total_matched + match_summary.total_unmatched_csv)
            if rate < 0.5:
                add_log("warning", f"Low match rate: {rate*100:.0f}% — check ad naming convention")

        st.session_state["match_summary"] = match_summary

        # Step 4: Compute top performers
        top5 = get_top_account_ads(csv_ads, n=5)
        # Build lookup: ad_name -> MatchResult
        matched_lookup = {}
        for mr in match_summary.matched:
            for mad in mr.matched_ads:
                matched_lookup[mad.ad_name] = mr

        top_performers_data = []
        for ad in top5:
            mr = matched_lookup.get(ad.ad_name)
            top_performers_data.append({"ad": ad, "match_result": mr})

        unmatched_top = sum(1 for x in top_performers_data if x["match_result"] is None)
        if unmatched_top > 0:
            add_log("warning", f"{unmatched_top} of top 5 account ads not matched to ClickUp")
        st.session_state["top_performers_data"] = top_performers_data

        # Step 5: Classify
        add_log("info", f"Classifying ads (Winner≥{winner_roas}x, Loser≤{loser_roas}x, MinSpend≥${min_spend:,.0f})...")
        from analyzer.classifier import Thresholds, classify_ads
        thresholds = Thresholds(
            winner_roas=winner_roas,
            winner_min_spend=min_spend,
            loser_roas=loser_roas,
            loser_min_spend=min_spend,
            untested_max_spend=min_spend,
        )
        classification = classify_ads(match_summary, thresholds)
        add_log("success", f"Winners: {len(classification.winners)} | Average: {len(classification.average)} | Losers: {len(classification.losers)} | Untested: {len(classification.untested)}")

        if len(classification.losers) == 0:
            add_log("warning", "0 losers found — thresholds may be too lenient or ROAS data not present in CSV")

        st.session_state["classification"] = classification

        # Add classification to top_performers_data
        classified_by_task_id = {ad.match.task.task_id: ad for ad in classification.all_classified}
        for item in top_performers_data:
            if item["match_result"]:
                task_id = item["match_result"].task.task_id
                ca = classified_by_task_id.get(task_id)
                item["classification"] = ca.classification.value if ca else None
            else:
                item["classification"] = None
        st.session_state["top_performers_data"] = top_performers_data

        # Step 6: Read scripts
        matched_tasks = [ad.match.task for ad in classification.all_classified if ad.classification.value != "untested"]
        add_log("info", f"Reading scripts from {len(matched_tasks)} classified tasks (Claude extraction)...")
        from analyzer.script_reader import read_all_scripts
        scripts = read_all_scripts(matched_tasks, use_claude=True)
        scripts_dict = {s.task_id: s for s in scripts}
        no_content = sum(1 for s in scripts if s.no_content_found)
        add_log("success", f"Read {len(scripts)} scripts ({no_content} with no content found)")
        st.session_state["scripts"] = scripts_dict

        # Step 7: Pattern analysis
        add_log("info", "Running pattern analysis with Claude...")
        from analyzer.pattern_analyzer import analyze_patterns
        pattern_analysis = analyze_patterns(classification, scripts_dict)
        add_log("success", f"Pattern analysis complete — {len(pattern_analysis.cross_insights)} cross-insights")
        st.session_state["pattern_analysis"] = pattern_analysis

        # Step 8: Generate hypotheses
        add_log("info", "Generating learnings and hypotheses with Claude...")
        from analyzer.hypothesis_generator import generate_hypotheses
        hypothesis_report = generate_hypotheses(pattern_analysis, classification)
        add_log("success", f"Generated {len(hypothesis_report.learnings)} learnings, {len(hypothesis_report.hypotheses)} hypotheses")
        st.session_state["hypothesis_report"] = hypothesis_report

        st.session_state["analysis_done"] = True
        st.session_state["brand_name"] = brand_name
        add_log("success", "✅ Analysis complete!")

    except Exception as e:
        import traceback
        add_log("error", f"Pipeline failed: {e}")
        add_log("error", traceback.format_exc()[:500])
        st.session_state["analysis_error"] = str(e)


# ── Helper: build top_performers for report generator ────────────────────────

def _build_top_performers_for_report(top_performers_data, clf):
    """Convert session top_performers_data into report_generator format."""
    if not top_performers_data:
        return None
    result = []
    for item in top_performers_data:
        mr = item.get("match_result")
        cls = item.get("classification")
        result.append({
            "ad": item["ad"],
            "match_result": mr,
            "classification": cls,
        })
    return result


# ── Reports History ───────────────────────────────────────────────────────────

def render_reports_history():
    st.markdown('<h2 style="color:#fafafa;">📁 Reports History</h2>', unsafe_allow_html=True)

    from analyzer.report_generator import list_reports

    reports = list_reports()
    if not reports:
        st.info("No reports generated yet. Run the full pipeline to create your first report.")
        return

    for r in reports:
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f'<p style="color:#fafafa;margin:0;">{r["name"]}</p>', unsafe_allow_html=True)
            st.markdown(f'<p style="color:#aaa;font-size:12px;margin:0;">{r["created"]} | {r["format"].upper()} | {r["size"] / 1024:.1f} KB</p>', unsafe_allow_html=True)
        with col2:
            report_path = Path(r["path"])
            if report_path.exists():
                mime = "application/pdf" if r["format"] == "pdf" else "text/html"
                st.download_button(
                    "⬇️",
                    report_path.read_bytes(),
                    file_name=report_path.name,
                    mime=mime,
                    key=f"dl_{r['name']}",
                )
        with col3:
            if st.button("🗑️", key=f"del_{r['name']}"):
                Path(r["path"]).unlink(missing_ok=True)
                st.rerun()
        st.markdown('<hr style="border:0;border-top:1px solid #333;margin:4px 0;">', unsafe_allow_html=True)


# ── Dashboard ─────────────────────────────────────────────────────────────────

def render_dashboard():
    st.markdown("## 🔄 Creative Feedback Loop Analyzer")
    st.markdown("Pull creative briefs from ClickUp → Match with Meta Ads → Find winning patterns")

    # ── PART 1: FORM ──────────────────────────────────────────────────────────
    with st.form("analysis_form"):
        col1, col2 = st.columns([2, 1])
        with col1:
            brand_name = st.text_input("Brand Name", placeholder="e.g., Eskiin")
        with col2:
            date_range = st.selectbox(
                "Date Range",
                [None, 7, 14, 30, 60, 90],
                index=3,
                format_func=lambda x: "All time" if x is None else f"Last {x} days",
            )

        uploaded = st.file_uploader("Upload Meta Ads Manager CSV", type=["csv"])

        col1, col2, col3 = st.columns(3)
        with col1:
            winner_roas = st.number_input("Winner ROAS ≥", value=2.0, step=0.1, min_value=0.0)
        with col2:
            loser_roas = st.number_input("Loser ROAS ≤", value=1.0, step=0.1, min_value=0.0)
        with col3:
            min_spend = st.number_input("Min Spend to Count ($)", value=100.0, step=50.0, min_value=0.0)

        submitted = st.form_submit_button("🚀 Run Analysis", use_container_width=True)

    if submitted and brand_name and uploaded is not None:
        # Check env vars
        missing = []
        if not os.environ.get("CLICKUP_API_KEY"):
            missing.append("CLICKUP_API_KEY")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            st.error(f"Missing required environment variables: {', '.join(missing)}")
        else:
            # Clear previous results
            for k in ["analysis_done", "tasks", "space_name", "list_name", "csv_ads",
                       "csv_total_spend", "match_summary", "classification", "scripts",
                       "pattern_analysis", "hypothesis_report", "top_performers_data",
                       "pipeline_log", "brand_name", "analysis_error"]:
                if k in st.session_state:
                    del st.session_state[k]
            init_state()

            csv_bytes = uploaded.read()
            with st.spinner("Running full analysis pipeline..."):
                run_full_pipeline(brand_name, csv_bytes, date_range, winner_roas, loser_roas, min_spend)
            st.rerun()

    # ── PART 2: PIPELINE LOG ──────────────────────────────────────────────────
    if st.session_state.get("pipeline_log"):
        with st.expander("📋 Pipeline Log", expanded=not st.session_state.get("analysis_done")):
            for level, msg in st.session_state["pipeline_log"]:
                color = {"info": "#aaa", "success": "#4CAF50", "warning": "#FF9800", "error": "#F44336"}.get(level, "#aaa")
                icon = "✅" if level == "success" else "⚠️" if level == "warning" else "❌" if level == "error" else "•"
                st.markdown(f'<p style="color:{color};font-size:13px;margin:2px 0;">{icon} {msg}</p>', unsafe_allow_html=True)

    # Show analysis error if set
    if st.session_state.get("analysis_error"):
        st.error(f"Analysis error: {st.session_state['analysis_error']}")

    # ── PART 3: RESULTS ───────────────────────────────────────────────────────
    if not st.session_state.get("analysis_done"):
        return

    clf = st.session_state.get("classification")
    pa = st.session_state.get("pattern_analysis")
    hr = st.session_state.get("hypothesis_report")

    # Threshold display values (use form values if available, else defaults)
    _winner_roas = winner_roas if submitted else 2.0
    _loser_roas = loser_roas if submitted else 1.0
    _min_spend = min_spend if submitted else 100.0

    # ── SECTION A: CLASSIFICATION OVERVIEW ───────────────────────────────────
    st.markdown("---")
    st.markdown("## 📊 Classification Overview")

    if clf:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Winners", f"{len(clf.winners)}", f"{clf.pillar_winners} pillar, {clf.strong_winners} strong")
        col2.metric("Average", len(clf.average))
        col3.metric("Losers", len(clf.losers))
        col4.metric("Untested", len(clf.untested))

        if len(clf.losers) == 0:
            st.warning(f"⚠️ 0 losers detected. Check your ROAS thresholds or CSV data. Current thresholds: Winner ≥ {_winner_roas}x, Loser ≤ {_loser_roas}x, Min spend ${_min_spend}")

        st.markdown("### 💰 Top 10 Ads by Spend (Sanity Check)")
        matched_sorted = sorted(clf.all_classified, key=lambda x: x.match.total_spend, reverse=True)
        for ad in matched_sorted[:10]:
            cls_color = {"winner": "#4CAF50", "average": "#FF9800", "loser": "#F44336", "untested": "#888"}.get(ad.classification.value, "#888")
            st.markdown(f"""
            <div style="background:#1A1D24;border-left:4px solid {cls_color};border-radius:4px;padding:8px 12px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;">
                <span style="color:#fafafa;font-size:13px;flex:1;">{ad.match.task.name[:70]}</span>
                <span style="color:#aaa;font-size:12px;margin:0 12px;">Spend: ${ad.match.total_spend:,.0f} | ROAS: {ad.match.weighted_roas:.2f}x</span>
                <span style="background:{cls_color};color:#0E1117;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:bold;">{ad.classification.value.upper()}</span>
            </div>
            """, unsafe_allow_html=True)

    # ── SECTION B: TOP PERFORMERS COMPARISON ─────────────────────────────────
    st.markdown("---")
    st.markdown("## 🏆 Top Account Performers vs ClickUp")

    top5 = st.session_state.get("top_performers_data", [])
    for i, item in enumerate(top5, 1):
        ad = item["ad"]
        mr = item["match_result"]
        cls = item.get("classification")
        if mr is None:
            st.markdown(f"""
            <div style="background:#1A1D24;border-left:4px solid #FF9800;border-radius:8px;padding:12px 16px;margin-bottom:8px;">
                <p style="color:#FF9800;font-weight:bold;margin:0;">#{i} {ad.ad_name[:80]}</p>
                <p style="color:#fafafa;font-size:13px;margin:4px 0;">Spend: ${ad.spend:,.0f} | ROAS: {ad.roas:.2f}x</p>
                <p style="color:#FF9800;font-size:12px;margin:4px 0;">⚠️ Not matched to any ClickUp task — add manually or check ad naming convention</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            cls_color = {"winner": "#4CAF50", "average": "#FF9800", "loser": "#F44336", "untested": "#888"}.get(cls or "", "#888")
            st.markdown(f"""
            <div style="background:#1A1D24;border-left:4px solid {cls_color};border-radius:8px;padding:12px 16px;margin-bottom:8px;">
                <p style="color:#fafafa;font-weight:bold;margin:0;">#{i} {ad.ad_name[:80]}</p>
                <p style="color:#fafafa;font-size:13px;margin:4px 0;">Spend: ${ad.spend:,.0f} | ROAS: {ad.roas:.2f}x | Classification: <span style="color:{cls_color};font-weight:bold;">{(cls or "").upper()}</span></p>
                <p style="color:#aaa;font-size:12px;margin:4px 0;">ClickUp: {mr.task.name[:80]}</p>
            </div>
            """, unsafe_allow_html=True)

    # ── SECTION C: PATTERN ANALYSIS ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("## 🔬 Pattern Analysis")

    if pa:
        st.markdown(pa.raw_analysis)
        if pa.cross_insights:
            st.markdown("### 🔗 Cross-Pattern Insights")
            for insight in pa.cross_insights:
                st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #6C63FF;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{insight}</p></div>', unsafe_allow_html=True)
    else:
        st.info("Pattern analysis not available")

    # ── SECTION D: MATCH DETAILS ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("## 🔗 Match Details")

    ms = st.session_state.get("match_summary")
    if ms:
        c1, c2, c3 = st.columns(3)
        c1.metric("Matched", ms.total_matched)
        c2.metric("Unmatched Tasks", ms.total_unmatched_tasks)
        c3.metric("Unmatched CSV Rows", ms.total_unmatched_csv)

        total = ms.total_matched + ms.total_unmatched_csv
        if total > 0:
            match_rate = ms.total_matched / total
            if match_rate < 0.5:
                st.warning(f"⚠️ Low match rate ({match_rate*100:.0f}%). Check that CSV ad names follow the same V-number convention as ClickUp task names.")

        if ms.unmatched_csv_rows:
            top_unmatched = sorted(ms.unmatched_csv_rows, key=lambda a: a.spend, reverse=True)[:10]
            with st.expander(f"Unmatched CSV ads — top {min(10, len(top_unmatched))} by spend"):
                for ad in top_unmatched:
                    st.markdown(f"""
                    <div style="background:#1A1D24;border-left:4px solid #888;border-radius:4px;padding:6px 12px;margin-bottom:4px;">
                        <span style="color:#fafafa;font-size:12px;">{ad.ad_name[:80]}</span>
                        <span style="color:#aaa;font-size:11px;margin-left:12px;">Spend: ${ad.spend:,.0f} | ROAS: {ad.roas:.2f}x</span>
                    </div>
                    """, unsafe_allow_html=True)

    # ── SECTION E: LEARNINGS ──────────────────────────────────────────────────
    with st.expander("💡 Key Learnings", expanded=False):
        if hr and hr.learnings:
            for i, learning in enumerate(hr.learnings, 1):
                conf_color = {"HIGH": "#4CAF50", "MEDIUM": "#FF9800", "LOW": "#F44336"}.get(learning.confidence.upper(), "#888")
                evidence = ", ".join(learning.supporting_evidence) if learning.supporting_evidence else "See analysis"
                st.markdown(f"""
                <div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <span style="color:#fafafa;font-weight:bold;">Learning {i}</span>
                        <span style="background:{conf_color};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{learning.confidence}</span>
                    </div>
                    <p style="color:#fafafa;margin:4px 0;">{learning.observation}</p>
                    <p style="color:#aaa;font-size:12px;margin:4px 0;"><strong>Evidence:</strong> {evidence}</p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No learnings generated.")

    # ── SECTION F: HYPOTHESES ─────────────────────────────────────────────────
    with st.expander("🧪 Testable Hypotheses", expanded=False):
        if hr and hr.hypotheses:
            for i, hyp in enumerate(hr.hypotheses, 1):
                pri_color = {"HIGH": "#F44336", "MEDIUM": "#FF9800", "LOW": "#4CAF50"}.get(hyp.priority.upper(), "#888")
                hooks_html = "".join(f"<li style='color:#fafafa;font-size:13px;'>{h}</li>" for h in hyp.suggested_hook_ideas) if hyp.suggested_hook_ideas else "<li style='color:#aaa;'>See analysis</li>"
                st.markdown(f"""
                <div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <span style="color:#fafafa;font-weight:bold;">Hypothesis {i}</span>
                        <span style="background:{pri_color};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{hyp.priority}</span>
                    </div>
                    <p style="color:#aaa;font-size:12px;margin:4px 0;"><em>Based on: {hyp.based_on_learning}</em></p>
                    <p style="color:#fafafa;margin:4px 0;"><strong>Test:</strong> {hyp.independent_variable}</p>
                    <p style="color:#fafafa;margin:4px 0;"><strong>Expected:</strong> {hyp.expected_outcome}</p>
                    <div style="margin-top:8px;padding:12px;background:#0E1117;border-radius:4px;">
                        <p style="color:#6C63FF;margin:0 0 4px 0;font-weight:bold;font-size:13px;">Script Outline</p>
                        <ul style="margin:4px 0;padding-left:16px;">{hooks_html}</ul>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Body:</strong> {hyp.suggested_body_structure or 'See analysis'}</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Format:</strong> {hyp.recommended_format or 'Based on winners'}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No hypotheses generated.")

    # ── SECTION G: ALL AD BREAKDOWNS ──────────────────────────────────────────
    with st.expander("📋 All Classified Ads", expanded=False):
        if clf:
            for ad in clf.all_classified:
                cls_color = {"winner": "#4CAF50", "average": "#FF9800", "loser": "#F44336", "untested": "#888"}.get(ad.classification.value, "#888")
                wt_color = {"pillar": "#FFD700", "strong": "#6C63FF", "normal": "#4CAF50", "minor": "#888"}.get(ad.weight_tier.value, "#888")
                st.markdown(f"""
                <div style="background:#1A1D24;border-left:4px solid {cls_color};border-radius:4px;padding:8px 12px;margin-bottom:4px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span style="color:#fafafa;font-size:12px;">{ad.match.task.name[:70]}</span>
                        <span>
                            <span style="background:{cls_color};color:#0E1117;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;">{ad.classification.value.upper()}</span>
                            <span style="background:{wt_color};color:#0E1117;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;margin-left:4px;">{ad.weight_tier.value.upper()}</span>
                        </span>
                    </div>
                    <p style="color:#aaa;font-size:11px;margin:2px 0;">Spend: ${ad.match.total_spend:,.0f} ({ad.spend_share*100:.1f}%) | ROAS: {ad.match.weighted_roas:.2f}x | Value: ${ad.value_score:,.0f}</p>
                </div>
                """, unsafe_allow_html=True)

    # ── SECTION H: EXPORT ─────────────────────────────────────────────────────
    if clf and pa and hr:
        st.markdown("---")
        st.markdown("### 📥 Export Report")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📄 Export HTML", use_container_width=True):
                from analyzer.report_generator import generate_html_report, save_report
                brand = st.session_state.get("brand_name", "Unknown")
                top_performers_data = st.session_state.get("top_performers_data", [])
                top_perf_for_report = _build_top_performers_for_report(top_performers_data, clf)
                html = generate_html_report(brand, clf, pa, hr, top_performers=top_perf_for_report)
                path = save_report(brand, html, format="html")
                st.success(f"Saved: {path}")
                st.download_button("⬇️ Download HTML", html, file_name=f"{brand}_report.html", mime="text/html")
        with col2:
            if st.button("📑 Export PDF", use_container_width=True):
                from analyzer.report_generator import generate_html_report, save_report
                brand = st.session_state.get("brand_name", "Unknown")
                top_performers_data = st.session_state.get("top_performers_data", [])
                top_perf_for_report = _build_top_performers_for_report(top_performers_data, clf)
                html = generate_html_report(brand, clf, pa, hr, top_performers=top_perf_for_report)
                path = save_report(brand, html, format="pdf")
                if path.suffix == ".pdf":
                    st.success(f"PDF saved: {path}")
                    st.download_button("⬇️ Download PDF", path.read_bytes(), file_name=f"{brand}_report.pdf", mime="application/pdf")
                else:
                    st.warning("PDF export requires Playwright. Saved as HTML instead.")
                    st.download_button("⬇️ Download HTML", html, file_name=f"{brand}_report.html", mime="text/html")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    init_state()

    if not check_login():
        return

    page = render_sidebar()

    if page == "Dashboard":
        render_dashboard()
    elif page == "Reports History":
        render_reports_history()


if __name__ == "__main__":
    main()
else:
    # Streamlit runs the module directly
    main()
