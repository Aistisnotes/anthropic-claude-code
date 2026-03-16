"""Creative Feedback Loop Analyzer — Streamlit App

Single-form pipeline: brand name + CSV upload -> full analysis in one click.

All 7 fixes integrated:
- FIX 1: CSV aggregated by ad name before matching (load_and_aggregate_csv)
- FIX 2: Separate winner/loser spend thresholds
- FIX 3: ROAS=0 with spend -> loser (handled by classifier since 0 < loser_roas)
- FIX 4: Date range filters CSV only, not ClickUp task pull
- FIX 5: Top 50 by spend section (no threshold filters, just rank)
- FIX 6: Novelty signals -- winner/loser/baseline pattern differentiation
- FIX 7: Aggregation stats in pipeline log (raw rows -> unique ads)
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import streamlit as st

# -- Page config (must be first Streamlit call) --------------------------------
st.set_page_config(
    page_title="Creative Feedback Loop",
    page_icon="\U0001f504",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -- Dark mode CSS -------------------------------------------------------------
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
    .stButton > button:hover { background-color: #5A52E0 !important; }
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


# -- Login gate ----------------------------------------------------------------

def check_login() -> bool:
    password = os.environ.get("CFL_PASSWORD", "")
    if not password:
        return True
    if st.session_state.get("authenticated"):
        return True
    st.markdown('<h1 style="color:#fafafa;text-align:center;">\U0001f504 Creative Feedback Loop</h1>', unsafe_allow_html=True)
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


# -- Session state init --------------------------------------------------------

def init_state():
    defaults = {
        "analysis_done": False,
        "tasks": None,
        "space_name": None,
        "list_name": None,
        "csv_ads": None,
        "csv_total_spend": 0.0,
        "aggregated_ads": None,
        "csv_stats": None,
        "match_summary": None,
        "classification": None,
        "scripts": None,
        "pattern_analysis": None,
        "hypothesis_report": None,
        "top_performers_data": None,
        "novelty": None,
        "all_classified": [],
        "all_counts": {},
        "pipeline_log": [],
        "brand_name": "",
        "analysis_error": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# -- Sidebar -------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.markdown('<h2 style="color:#fafafa;">\U0001f504 Creative Feedback</h2>', unsafe_allow_html=True)
        st.markdown('<p style="color:#aaa;font-size:13px;">Find winning patterns in your creative</p>', unsafe_allow_html=True)
        st.markdown("---")
        page = st.radio("Navigation", ["Dashboard", "Reports History"], label_visibility="collapsed")
        if st.session_state.get("analysis_done"):
            st.markdown("---")
            brand = st.session_state.get("brand_name", "")
            space = st.session_state.get("space_name", "")
            all_counts_sb = st.session_state.get("all_counts", {})
            csv_stats = st.session_state.get("csv_stats")
            if all_counts_sb:
                st.markdown(f'<p style="color:#aaa;font-size:12px;">Brand: <strong style="color:#fafafa;">{brand}</strong></p>', unsafe_allow_html=True)
                st.markdown(f'<p style="color:#aaa;font-size:12px;">Space: {space}</p>', unsafe_allow_html=True)
                st.markdown(f'<p style="color:#4CAF50;font-size:12px;">\u2705 {all_counts_sb.get("winner", 0)} winners</p>', unsafe_allow_html=True)
                st.markdown(f'<p style="color:#F44336;font-size:12px;">\u274c {all_counts_sb.get("loser", 0)} losers</p>', unsafe_allow_html=True)
            if csv_stats:
                st.markdown(
                    f'<p style="color:#aaa;font-size:11px;">{csv_stats["raw_rows"]:,} rows \u2192 {csv_stats["unique_ads"]:,} unique ads</p>',
                    unsafe_allow_html=True,
                )
        st.markdown("---")
        if st.button("\U0001f504 Reset", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
    return page


# -- CSV helpers ---------------------------------------------------------------

def _load_aggregated_csv(csv_bytes: bytes, date_start, date_end):
    from creative_feedback_loop.csv_aggregator import load_and_aggregate_csv
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(csv_bytes)
        csv_path = tmp.name
    try:
        return load_and_aggregate_csv(csv_path, date_start=date_start, date_end=date_end)
    finally:
        os.unlink(csv_path)


def _aggregated_to_metrics(aggregated_ads):
    from analyzer.csv_matcher import AdMetrics
    return [
        AdMetrics(
            ad_name=ad.ad_name,
            spend=ad.total_spend,
            roas=ad.blended_roas,
            impressions=ad.total_impressions,
            conversions=ad.total_conversions,
        )
        for ad in aggregated_ads
    ]


# -- Novelty pattern extraction ------------------------------------------------

def _extract_patterns_for_novelty(classified_ads_old: list) -> dict:
    format_keywords = [
        "ugc", "static", "video", "carousel", "story", "reel",
        "testimonial", "review", "before after", "demo", "unboxing",
        "founder", "talking head", "slideshow", "gif",
    ]
    hook_keywords = [
        "hook", "problem", "solution", "question", "stat",
        "shocking", "mistake", "secret", "hack", "tip",
        "vs", "comparison", "transformation",
    ]
    patterns: dict = {}
    for ca in classified_ads_old:
        # Support both new ClassifiedAd (ca.ad.ad_name) and old (ca.match.task.name)
        name_lower = (ca.ad.ad_name if hasattr(ca, "ad") else ca.match.task.name).lower()
        for kw in format_keywords:
            if kw in name_lower:
                key = f"format:{kw}"
                patterns[key] = patterns.get(key, 0) + 1
        for kw in hook_keywords:
            if kw in name_lower:
                key = f"hook:{kw}"
                patterns[key] = patterns.get(key, 0) + 1
        if re.search(r"v\d+", name_lower):
            patterns["has_version"] = patterns.get("has_version", 0) + 1
        if any(ord(c) > 127 for c in ca.match.task.name):
            patterns["has_emoji_or_unicode"] = patterns.get("has_emoji_or_unicode", 0) + 1
    return patterns


# -- Pipeline ------------------------------------------------------------------

def run_full_pipeline(
    brand_name: str,
    csv_bytes: bytes,
    date_start,
    date_end,
    winner_roas: float,
    winner_spend: float,
    loser_roas: float,
    loser_spend: float,
):
    log = []

    def add_log(level: str, msg: str):
        log.append((level, msg))
        st.session_state["pipeline_log"] = log[:]

    try:
        # Step 1: Pull ClickUp tasks (FIX 4: no date filter on ClickUp)
        add_log("info", f"Searching ClickUp for '{brand_name}'...")
        from analyzer.clickup_client import find_brand_and_pull_tasks
        space_name, list_name, tasks = find_brand_and_pull_tasks(brand_name, fetch_comments=True)

        if not space_name:
            add_log("error", f"Could not find ClickUp space matching '{brand_name}'")
            st.session_state["analysis_error"] = f"Could not find ClickUp space matching '{brand_name}'"
            return
        if not list_name:
            add_log("error", f"Found space '{space_name}' but no Creative Team or Media Buying list")
            st.session_state["analysis_error"] = "No Creative Team or Media Buying list found"
            return

        add_log("success", f"Found '{space_name}' -> {list_name} -- {len(tasks)} tasks")
        st.session_state["tasks"] = tasks
        st.session_state["space_name"] = space_name
        st.session_state["list_name"] = list_name

        # Step 2: Load & aggregate CSV (FIX 1 + FIX 4 + FIX 7)
        date_label = f" [{date_start or '...'} -> {date_end or '...'}]" if (date_start or date_end) else ""
        add_log("info", f"Loading and aggregating Meta Ads CSV{date_label}...")

        aggregated_ads, csv_stats = _load_aggregated_csv(csv_bytes, date_start, date_end)

        raw = csv_stats["raw_rows"]
        unique = csv_stats["unique_ads"]
        total_spend = csv_stats["total_spend"]
        avg_rows = raw / unique if unique > 0 else 0
        add_log(
            "success",
            f"Aggregated {raw:,} CSV rows -> {unique:,} unique ads -- "
            f"Total spend: ${total_spend:,.2f} | Avg {avg_rows:.1f} rows/ad",
        )
        if raw > unique:
            add_log("info", f"Deduplication: {raw - unique:,} duplicate rows removed (same ad across ad sets)")

        csv_ads = _aggregated_to_metrics(aggregated_ads)
        st.session_state["csv_ads"] = csv_ads
        st.session_state["csv_total_spend"] = total_spend
        st.session_state["aggregated_ads"] = aggregated_ads
        st.session_state["csv_stats"] = csv_stats

        # Step 3: Classify ALL aggregated ads (CRITICAL: before ClickUp matching)
        # This gives winners/losers for all 461 ads, not just the ~4 matched ones.
        from creative_feedback_loop.classifier import ThresholdConfig, classify_ads as classify_all_ads
        threshold_config = ThresholdConfig(
            winner_roas_min=winner_roas,
            winner_spend_min=winner_spend,
            loser_roas_max=loser_roas,
            loser_spend_min=loser_spend,
        )
        all_classified, all_counts = classify_all_ads(aggregated_ads, threshold_config)
        # DEBUG: diagnose classification counts
        print(f"DEBUG THRESHOLDS: winner_roas_min={threshold_config.winner_roas_min}, winner_spend_min={threshold_config.winner_spend_min}, loser_roas_max={threshold_config.loser_roas_max}, loser_spend_min={threshold_config.loser_spend_min}")
        print(f"DEBUG TOTAL ADS PASSED TO CLASSIFIER: {len(aggregated_ads)}")
        _spend_ge_winner = sum(1 for a in aggregated_ads if a.total_spend >= threshold_config.winner_spend_min)
        _spend_ge_loser = sum(1 for a in aggregated_ads if a.total_spend >= threshold_config.loser_spend_min)
        print(f"DEBUG SPEND >= winner_spend_min ({threshold_config.winner_spend_min}): {_spend_ge_winner}")
        print(f"DEBUG SPEND >= loser_spend_min ({threshold_config.loser_spend_min}): {_spend_ge_loser}")
        _manual_winners = sum(1 for a in aggregated_ads if a.blended_roas >= threshold_config.winner_roas_min and a.total_spend >= threshold_config.winner_spend_min)
        _manual_losers = sum(1 for a in aggregated_ads if a.blended_roas < threshold_config.loser_roas_max and a.total_spend >= threshold_config.loser_spend_min)
        print(f"DEBUG MANUAL COUNT winners (roas>={threshold_config.winner_roas_min} AND spend>={threshold_config.winner_spend_min}): {_manual_winners}")
        print(f"DEBUG MANUAL COUNT losers (roas<{threshold_config.loser_roas_max} AND spend>={threshold_config.loser_spend_min}): {_manual_losers}")
        print(f"DEBUG ACTUAL COUNTS from classify_all_ads: {all_counts}")
        _untested_5 = [(ca.ad.ad_name, ca.ad.total_spend, ca.ad.blended_roas, ca.reason) for ca in all_classified if ca.classification == "untested"][:5]
        print(f"DEBUG FIRST 5 UNTESTED ADS: {_untested_5}")
        add_log(
            "success",
            f"Classified ALL {len(aggregated_ads):,} ads: "
            f"{all_counts['winner']} winners, {all_counts['loser']} losers, "
            f"{all_counts['untested']} untested",
        )
        st.session_state["all_classified"] = all_classified
        st.session_state["all_counts"] = all_counts

        # Step 4: Match ClickUp tasks to CSV ads (V/B number matching — for script reading)
        add_log("info", "Matching ClickUp tasks to CSV ads (V/B number matching)...")
        from analyzer.csv_matcher import match_tasks_to_csv, get_top_account_ads
        match_summary = match_tasks_to_csv(tasks, csv_ads, total_spend)
        add_log(
            "success",
            f"Matched {match_summary.total_matched} tasks | "
            f"Unmatched: {match_summary.total_unmatched_tasks} tasks, "
            f"{match_summary.total_unmatched_csv} CSV rows",
        )
        total_csv = match_summary.total_matched + match_summary.total_unmatched_csv
        if total_csv > 0 and match_summary.total_matched / total_csv < 0.5:
            add_log("warning", f"Low match rate: {match_summary.total_matched/total_csv*100:.0f}% -- check V/B naming convention")
        st.session_state["match_summary"] = match_summary

        # Step 5: Top account performers
        top5 = get_top_account_ads(csv_ads, n=5)
        matched_lookup = {mad.ad_name: mr for mr in match_summary.matched for mad in mr.matched_ads}
        top_performers_data = [{"ad": ad, "match_result": matched_lookup.get(ad.ad_name)} for ad in top5]
        unmatched_top = sum(1 for x in top_performers_data if x["match_result"] is None)
        if unmatched_top > 0:
            add_log("warning", f"{unmatched_top} of top 5 account ads not matched to ClickUp")
        st.session_state["top_performers_data"] = top_performers_data

        # Step 6: Classify matched ads only (for Claude deep analysis — scripts/patterns/hypotheses)
        add_log(
            "info",
            f"Classifying (Winner: ROAS>={winner_roas}x & spend>=${winner_spend:,.0f} | "
            f"Loser: ROAS<{loser_roas}x & spend>=${loser_spend:,.0f})...",
        )
        from analyzer.classifier import Thresholds, classify_ads
        thresholds = Thresholds(
            winner_roas=winner_roas,
            winner_min_spend=winner_spend,
            loser_roas=loser_roas,
            loser_min_spend=loser_spend,
            untested_max_spend=min(winner_spend, loser_spend),
        )
        classification = classify_ads(match_summary, thresholds)
        add_log(
            "success",
            f"Winners: {len(classification.winners)} | "
            f"Average: {len(classification.average)} | "
            f"Losers: {len(classification.losers)} | "
            f"Untested: {len(classification.untested)}",
        )
        if len(classification.losers) == 0:
            add_log("warning", "0 losers found -- ROAS data may be missing or thresholds too lenient")
        st.session_state["classification"] = classification

        # Attach classification from all_classified (all 461 ads) by ad_name
        classified_by_ad_name = {ca.ad.ad_name: ca for ca in all_classified}
        for item in top_performers_data:
            ca = classified_by_ad_name.get(item["ad"].ad_name)
            item["classification"] = ca.classification if ca else None
        st.session_state["top_performers_data"] = top_performers_data

        # Step 7: Read scripts
        matched_tasks = [ad.match.task for ad in classification.all_classified if ad.classification.value != "untested"]
        add_log("info", f"Reading scripts from {len(matched_tasks)} classified tasks (Claude extraction)...")
        from analyzer.script_reader import read_all_scripts
        scripts = read_all_scripts(matched_tasks, use_claude=True)
        scripts_dict = {s.task_id: s for s in scripts}
        no_content = sum(1 for s in scripts if s.no_content_found)
        add_log("success", f"Read {len(scripts)} scripts ({no_content} with no content found)")
        st.session_state["scripts"] = scripts_dict

        # Step 8: Pattern analysis
        add_log("info", "Running pattern analysis with Claude...")
        from analyzer.pattern_analyzer import analyze_patterns
        pattern_analysis = analyze_patterns(classification, scripts_dict)
        add_log("success", f"Pattern analysis complete -- {len(pattern_analysis.cross_insights)} cross-insights")
        st.session_state["pattern_analysis"] = pattern_analysis

        # Step 9: Hypotheses
        add_log("info", "Generating learnings and hypotheses with Claude...")
        from analyzer.hypothesis_generator import generate_hypotheses
        hypothesis_report = generate_hypotheses(pattern_analysis, classification)
        add_log("success", f"Generated {len(hypothesis_report.learnings)} learnings, {len(hypothesis_report.hypotheses)} hypotheses")
        st.session_state["hypothesis_report"] = hypothesis_report

        # Step 10: Novelty signals (FIX 6)
        try:
            from creative_feedback_loop.novelty_filter import compute_novelty
            all_winners = [ca for ca in all_classified if ca.classification == "winner"]
            all_losers = [ca for ca in all_classified if ca.classification == "loser"]
            winner_pats = _extract_patterns_for_novelty(all_winners)
            loser_pats = _extract_patterns_for_novelty(all_losers)
            if all_winners or all_losers:
                novelty = compute_novelty(
                    winner_pats, loser_pats,
                    total_winners=len(all_winners),
                    total_losers=len(all_losers),
                )
                st.session_state["novelty"] = novelty
                add_log(
                    "success",
                    f"Novelty signals: {len(novelty.winner_signals)} winner, "
                    f"{len(novelty.loser_signals)} loser, "
                    f"{len(novelty.baseline_patterns)} baseline",
                )
        except Exception as e:
            add_log("warning", f"Novelty analysis skipped: {e}")

        st.session_state["analysis_done"] = True
        st.session_state["brand_name"] = brand_name
        add_log("success", "\u2705 Analysis complete!")

    except Exception as e:
        import traceback
        add_log("error", f"Pipeline failed: {e}")
        add_log("error", traceback.format_exc()[:500])
        st.session_state["analysis_error"] = str(e)


# -- Report helper -------------------------------------------------------------

def _build_top_performers_for_report(top_performers_data, clf):
    if not top_performers_data:
        return None
    return [
        {"ad": item["ad"], "match_result": item.get("match_result"), "classification": item.get("classification")}
        for item in top_performers_data
    ]


# -- Reports History -----------------------------------------------------------

def render_reports_history():
    st.markdown('<h2 style="color:#fafafa;">\U0001f4c1 Reports History</h2>', unsafe_allow_html=True)
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
                st.download_button("\u2b07\ufe0f", report_path.read_bytes(), file_name=report_path.name, mime=mime, key=f'dl_{r["name"]}')
        with col3:
            if st.button("\U0001f5d1\ufe0f", key=f'del_{r["name"]}'):
                Path(r["path"]).unlink(missing_ok=True)
                st.rerun()
        st.markdown('<hr style="border:0;border-top:1px solid #333;margin:4px 0;">', unsafe_allow_html=True)


# -- Dashboard -----------------------------------------------------------------

def render_dashboard():
    st.markdown("## \U0001f504 Creative Feedback Loop Analyzer")
    st.markdown("Pull creative briefs from ClickUp -> Match with Meta Ads -> Find winning patterns")

    with st.form("analysis_form"):
        brand_name = st.text_input("Brand Name", placeholder="e.g., Eskiin")
        uploaded = st.file_uploader("Upload Meta Ads Manager CSV", type=["csv"])

        # FIX 4: CSV date filter (not ClickUp)
        st.markdown("**CSV Date Filter** -- optional, filters rows within the CSV only (not ClickUp)")
        d1, d2 = st.columns(2)
        with d1:
            date_start = st.date_input("Start date", value=None, key="form_date_start")
        with d2:
            date_end = st.date_input("End date", value=None, key="form_date_end")

        # FIX 2: Separate winner/loser thresholds
        st.markdown("**Classification Thresholds**")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            winner_roas = st.number_input("Winner ROAS >=", value=2.0, step=0.1, min_value=0.0)
        with c2:
            winner_spend = st.number_input("Winner min spend ($)", value=100.0, step=50.0, min_value=0.0)
        with c3:
            loser_roas = st.number_input("Loser ROAS <", value=1.0, step=0.1, min_value=0.0)
        with c4:
            loser_spend = st.number_input("Loser min spend ($)", value=100.0, step=50.0, min_value=0.0)

        submitted = st.form_submit_button("\U0001f680 Run Analysis", use_container_width=True)

    if submitted and brand_name and uploaded is not None:
        missing = [k for k in ["CLICKUP_API_KEY", "ANTHROPIC_API_KEY"] if not os.environ.get(k)]
        if missing:
            st.error(f"Missing required environment variables: {', '.join(missing)}")
        else:
            reset_keys = [
                "analysis_done", "tasks", "space_name", "list_name", "csv_ads",
                "csv_total_spend", "aggregated_ads", "csv_stats", "match_summary",
                "classification", "scripts", "pattern_analysis", "hypothesis_report",
                "top_performers_data", "novelty", "all_classified", "all_counts",
                "pipeline_log", "brand_name", "analysis_error",
            ]
            for k in reset_keys:
                st.session_state.pop(k, None)
            init_state()
            with st.spinner("Running full analysis pipeline..."):
                run_full_pipeline(
                    brand_name,
                    uploaded.read(),
                    str(date_start) if date_start else None,
                    str(date_end) if date_end else None,
                    winner_roas, winner_spend,
                    loser_roas, loser_spend,
                )
            st.rerun()

    # Pipeline log (FIX 7)
    if st.session_state.get("pipeline_log"):
        with st.expander("\U0001f4cb Pipeline Log", expanded=not st.session_state.get("analysis_done")):
            for level, msg in st.session_state["pipeline_log"]:
                color = {"info": "#aaa", "success": "#4CAF50", "warning": "#FF9800", "error": "#F44336"}.get(level, "#aaa")
                icon = {"success": "\u2705", "warning": "\u26a0\ufe0f", "error": "\u274c"}.get(level, "\u2022")
                st.markdown(f'<p style="color:{color};font-size:13px;margin:2px 0;">{icon} {msg}</p>', unsafe_allow_html=True)

    if st.session_state.get("analysis_error"):
        st.error(f"Analysis error: {st.session_state['analysis_error']}")

    if not st.session_state.get("analysis_done"):
        return

    all_classified = st.session_state.get("all_classified", [])
    all_counts = st.session_state.get("all_counts", {})
    clf = st.session_state.get("classification")  # for Claude analysis sections only
    pa = st.session_state.get("pattern_analysis")
    hr = st.session_state.get("hypothesis_report")

    # Aggregation summary (FIX 7)
    csv_stats = st.session_state.get("csv_stats")
    if csv_stats:
        st.markdown("---")
        st.markdown("## \U0001f4ca Aggregation Summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("CSV Rows", f"{csv_stats['raw_rows']:,}")
        c2.metric("Unique Ads", f"{csv_stats['unique_ads']:,}")
        c3.metric("Total Spend", f"${csv_stats['total_spend']:,.2f}")
        ratio = csv_stats["raw_rows"] / csv_stats["unique_ads"] if csv_stats["unique_ads"] > 0 else 0
        c4.metric("Avg Rows/Ad", f"{ratio:.1f}")
        st.caption(
            f"Aggregated **{csv_stats['raw_rows']:,}** CSV rows (one per ad per ad set) "
            f"into **{csv_stats['unique_ads']:,}** unique ads before classification."
        )

    # Section A: Classification overview (ALL ads from CSV)
    st.markdown("---")
    st.markdown("## \U0001f4ca Classification Overview")
    if all_counts:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Winners", all_counts.get("winner", 0))
        col2.metric("Losers", all_counts.get("loser", 0))
        col3.metric("Untested", all_counts.get("untested", 0))
        col4.metric("Total Ads", len(all_classified))
        if all_counts.get("loser", 0) == 0:
            st.warning("\u26a0\ufe0f 0 losers detected. Check your ROAS thresholds or CSV data.")
        st.markdown("### \U0001f4b0 Top 10 Ads by Spend (Sanity Check)")
        for ca in sorted(all_classified, key=lambda x: x.ad.total_spend, reverse=True)[:10]:
            cls_color = {"winner": "#4CAF50", "loser": "#F44336", "untested": "#888"}.get(ca.classification, "#888")
            st.markdown(f"""
            <div style="background:#1A1D24;border-left:4px solid {cls_color};border-radius:4px;padding:8px 12px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;">
                <span style="color:#fafafa;font-size:13px;flex:1;">{ca.ad.ad_name[:70]}</span>
                <span style="color:#aaa;font-size:12px;margin:0 12px;">Spend: ${ca.ad.total_spend:,.0f} | ROAS: {ca.ad.blended_roas:.2f}x</span>
                <span style="background:{cls_color};color:#0E1117;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:bold;">{ca.classification.upper()}</span>
            </div>
            """, unsafe_allow_html=True)
    # Section B: Top performers
    st.markdown("---")
    st.markdown("## \U0001f3c6 Top Account Performers vs ClickUp")
    for i, item in enumerate(st.session_state.get("top_performers_data", []), 1):
        ad = item["ad"]
        mr = item["match_result"]
        cls = item.get("classification")
        if mr is None:
            st.markdown(f"""
            <div style="background:#1A1D24;border-left:4px solid #FF9800;border-radius:8px;padding:12px 16px;margin-bottom:8px;">
                <p style="color:#FF9800;font-weight:bold;margin:0;">#{i} {ad.ad_name[:80]}</p>
                <p style="color:#fafafa;font-size:13px;margin:4px 0;">Spend: ${ad.spend:,.0f} | ROAS: {ad.roas:.2f}x</p>
                <p style="color:#FF9800;font-size:12px;margin:4px 0;">\u26a0\ufe0f Not matched to any ClickUp task</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            cls_color = {"winner": "#4CAF50", "average": "#FF9800", "loser": "#F44336", "untested": "#888"}.get(cls or "", "#888")
            st.markdown(f"""
            <div style="background:#1A1D24;border-left:4px solid {cls_color};border-radius:8px;padding:12px 16px;margin-bottom:8px;">
                <p style="color:#fafafa;font-weight:bold;margin:0;">#{i} {ad.ad_name[:80]}</p>
                <p style="color:#fafafa;font-size:13px;margin:4px 0;">Spend: ${ad.spend:,.0f} | ROAS: {ad.roas:.2f}x | <span style="color:{cls_color};font-weight:bold;">{(cls or "").upper()}</span></p>
                <p style="color:#aaa;font-size:12px;margin:4px 0;">ClickUp: {mr.task.name[:80]}</p>
            </div>
            """, unsafe_allow_html=True)

    # Section C: Pattern analysis
    st.markdown("---")
    st.markdown("## \U0001f52c Pattern Analysis")
    if pa:
        st.markdown(pa.raw_analysis)
        if pa.cross_insights:
            st.markdown("### \U0001f517 Cross-Pattern Insights")
            for insight in pa.cross_insights:
                st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #6C63FF;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{insight}</p></div>', unsafe_allow_html=True)
    else:
        st.info("Pattern analysis not available")

    # Section D: Novelty signals (FIX 6)
    novelty = st.session_state.get("novelty")
    if novelty:
        st.markdown("---")
        st.markdown("## \U0001f9ec Pattern Novelty Signals")
        st.caption("Patterns differentiated between winners and losers. Baseline = table stakes (>85% of all ads).")
        if novelty.winner_signals:
            st.markdown("### \u2705 Winner Patterns")
            for sig in novelty.winner_signals:
                strength_icon = {"HIGH": "\U0001f534", "MEDIUM": "\U0001f7e1", "LOW": "\U0001f7e2"}.get(sig.signal_strength, "")
                st.markdown(
                    f"- {strength_icon} **`{sig.pattern}`** -- "
                    f"{sig.winner_rate*100:.0f}% winners vs {sig.loser_rate*100:.0f}% losers "
                    f"(+{sig.differentiation*100:.0f}% -- {sig.signal_strength})"
                )
        if novelty.loser_signals:
            st.markdown("### \u274c Loser Patterns")
            for sig in novelty.loser_signals:
                st.markdown(
                    f"- **`{sig.pattern}`** -- "
                    f"{sig.loser_rate*100:.0f}% losers vs {sig.winner_rate*100:.0f}% winners "
                    f"(+{abs(sig.differentiation)*100:.0f}% loser skew -- {sig.signal_strength})"
                )
        if novelty.baseline_patterns:
            with st.expander("\U0001f4cb Baseline Patterns (already standard -- >85% of all ads)"):
                for sig in novelty.baseline_patterns:
                    st.markdown(f"- `{sig.pattern}` -- {sig.total_rate*100:.0f}% of all ads")

    # Section E: Match details
    st.markdown("---")
    st.markdown("## \U0001f517 Match Details")
    ms = st.session_state.get("match_summary")
    if ms:
        c1, c2, c3 = st.columns(3)
        c1.metric("Matched", ms.total_matched)
        c2.metric("Unmatched Tasks", ms.total_unmatched_tasks)
        c3.metric("Unmatched CSV Rows", ms.total_unmatched_csv)
        total = ms.total_matched + ms.total_unmatched_csv
        if total > 0 and ms.total_matched / total < 0.5:
            st.warning(f"\u26a0\ufe0f Low match rate ({ms.total_matched/total*100:.0f}%). Check that CSV ad names use the V/B-number convention.")
        if ms.unmatched_csv_rows:
            top_unmatched = sorted(ms.unmatched_csv_rows, key=lambda a: a.spend, reverse=True)[:10]
            with st.expander(f"Unmatched CSV ads -- top {len(top_unmatched)} by spend"):
                for ad in top_unmatched:
                    st.markdown(f"""
                    <div style="background:#1A1D24;border-left:4px solid #888;border-radius:4px;padding:6px 12px;margin-bottom:4px;">
                        <span style="color:#fafafa;font-size:12px;">{ad.ad_name[:80]}</span>
                        <span style="color:#aaa;font-size:11px;margin-left:12px;">Spend: ${ad.spend:,.0f} | ROAS: {ad.roas:.2f}x</span>
                    </div>
                    """, unsafe_allow_html=True)

    # Section F: Top 50 by spend (FIX 5)
    aggregated_ads = st.session_state.get("aggregated_ads", [])
    if aggregated_ads:
        st.markdown("---")
        st.markdown("## \U0001f4c8 Top 50 Ads by Spend")
        st.caption("All ads ranked by total aggregated spend. No winner/loser thresholds -- simple profitability (ROAS >= 1.0).")
        import pandas as pd
        from creative_feedback_loop.top50 import build_top50
        profitability_labels = {
            "profitable": "Profitable (ROAS >= 1.0)",
            "unprofitable": "Unprofitable (ROAS < 1.0)",
            "no_conversions": "No Conversions (ROAS = 0)",
        }
        top50_rows = [
            {
                "Rank": t.rank,
                "Ad Name": t.ad.ad_name,
                "Total Spend": f"${t.ad.total_spend:,.2f}",
                "ROAS": f"{t.ad.blended_roas:.2f}",
                "Revenue": f"${t.ad.total_revenue:,.2f}",
                "Impressions": f"{t.ad.total_impressions:,}",
                "Conversions": t.ad.total_conversions,
                "Status": profitability_labels.get(t.profitability, t.profitability),
            }
            for t in build_top50(aggregated_ads, clickup_tasks=None)
        ]
        st.dataframe(pd.DataFrame(top50_rows), use_container_width=True, hide_index=True)

    # Section G: Learnings
    with st.expander("\U0001f4a1 Key Learnings", expanded=False):
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

    # Section H: Hypotheses
    with st.expander("\U0001f9ea Testable Hypotheses", expanded=False):
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

    # Section I: All classified ads (all from CSV, not just ClickUp-matched)
    with st.expander(f"\U0001f4cb All Classified Ads ({len(all_classified):,})", expanded=False):
        if all_classified:
            for ca in sorted(all_classified, key=lambda x: x.ad.total_spend, reverse=True):
                cls_color = {"winner": "#4CAF50", "loser": "#F44336", "untested": "#888"}.get(ca.classification, "#888")
                st.markdown(f"""
                <div style="background:#1A1D24;border-left:4px solid {cls_color};border-radius:4px;padding:6px 12px;margin-bottom:3px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span style="color:#fafafa;font-size:12px;">{ca.ad.ad_name[:70]}</span>
                        <span style="background:{cls_color};color:#0E1117;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;">{ca.classification.upper()}</span>
                    </div>
                    <p style="color:#aaa;font-size:11px;margin:2px 0;">Spend: ${ca.ad.total_spend:,.0f} | ROAS: {ca.ad.blended_roas:.2f}x | {ca.reason}</p>
                </div>
                """, unsafe_allow_html=True)
    # Section J: Export
    if all_counts and pa and hr:
        st.markdown("---")
        st.markdown("### \U0001f4e5 Export Report")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("\U0001f4c4 Export HTML", use_container_width=True):
                from analyzer.report_generator import generate_html_report, save_report
                brand = st.session_state.get("brand_name", "Unknown")
                html = generate_html_report(brand, clf, pa, hr, top_performers=_build_top_performers_for_report(st.session_state.get("top_performers_data", []), clf))
                path = save_report(brand, html, format="html")
                st.success(f"Saved: {path}")
                st.download_button("\u2b07\ufe0f Download HTML", html, file_name=f"{brand}_report.html", mime="text/html")
        with col2:
            if st.button("\U0001f4d1 Export PDF", use_container_width=True):
                from analyzer.report_generator import generate_html_report, save_report
                brand = st.session_state.get("brand_name", "Unknown")
                html = generate_html_report(brand, clf, pa, hr, top_performers=_build_top_performers_for_report(st.session_state.get("top_performers_data", []), clf))
                path = save_report(brand, html, format="pdf")
                if path.suffix == ".pdf":
                    st.success(f"PDF saved: {path}")
                    st.download_button("\u2b07\ufe0f Download PDF", path.read_bytes(), file_name=f"{brand}_report.pdf", mime="application/pdf")
                else:
                    st.warning("PDF export requires Playwright. Saved as HTML instead.")
                    st.download_button("\u2b07\ufe0f Download HTML", html, file_name=f"{brand}_report.html", mime="text/html")


# -- Entry point ---------------------------------------------------------------

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
    main()
