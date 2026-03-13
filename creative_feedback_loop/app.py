"""Creative Feedback Loop Analyzer — Streamlit App

Tabs:
  1. Recent Creative — analysis of recently launched ads (filtered by date + thresholds)
  2. Top 50 Account Ads — top 50 by spend, all-time, ROAS-only classification
  3. Recent vs All-Time Comparison — drift detection
  4. Reports — history and export
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Creative Feedback Loop",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
)

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


def check_login() -> bool:
    password = os.environ.get("CFL_PASSWORD", "")
    if not password:
        return True
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


def check_env_vars() -> list[str]:
    missing = []
    if not os.environ.get("CLICKUP_API_KEY"):
        missing.append("CLICKUP_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    return missing


def init_state():
    defaults = {
        "tasks": None, "space_name": None, "list_name": None, "brand_name": None,
        "csv_ads": None, "csv_total_spend": 0, "csv_diagnostics": None,
        "match_summary": None, "classification": None,
        "scripts": None, "pattern_analysis": None, "hypothesis_report": None,
        "top50_match_summary": None, "top50_classification": None,
        "top50_scripts": None, "top50_pattern_analysis": None, "top50_hypothesis_report": None,
        "comparison_analysis": None,
        "thresholds_set": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def render_sidebar():
    with st.sidebar:
        st.markdown('<h2 style="color:#fafafa;">🔄 Creative Feedback Loop</h2>', unsafe_allow_html=True)
        st.markdown('<p style="color:#aaa;font-size:13px;">Pull briefs → Match performance → Find patterns → Detect drift</p>', unsafe_allow_html=True)
        st.markdown("---")

        st.markdown('<p style="color:#aaa;font-size:12px;">Data Ingestion</p>', unsafe_allow_html=True)
        for label, key in [("ClickUp Tasks", "tasks"), ("Meta CSV", "csv_ads")]:
            icon = "✅" if st.session_state.get(key) is not None else "⬜"
            st.markdown(f'<p style="color:#fafafa;font-size:13px;margin:2px 0;">{icon} {label}</p>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<p style="color:#aaa;font-size:12px;">Recent Creative</p>', unsafe_allow_html=True)
        for label, key in [("Match & Classify", "classification"), ("Read Scripts", "scripts"),
                           ("Patterns", "pattern_analysis"), ("Hypotheses", "hypothesis_report")]:
            icon = "✅" if st.session_state.get(key) is not None else "⬜"
            st.markdown(f'<p style="color:#fafafa;font-size:13px;margin:2px 0;">{icon} {label}</p>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<p style="color:#aaa;font-size:12px;">Top 50 All-Time</p>', unsafe_allow_html=True)
        for label, key in [("Match & Classify", "top50_classification"), ("Read Scripts", "top50_scripts"),
                           ("Patterns", "top50_pattern_analysis")]:
            icon = "✅" if st.session_state.get(key) is not None else "⬜"
            st.markdown(f'<p style="color:#fafafa;font-size:13px;margin:2px 0;">{icon} {label}</p>', unsafe_allow_html=True)

        st.markdown("---")
        icon = "✅" if st.session_state.get("comparison_analysis") is not None else "⬜"
        st.markdown(f'<p style="color:#fafafa;font-size:13px;margin:2px 0;">{icon} Comparison</p>', unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🔄 Reset All", use_container_width=True):
            for k in list(st.session_state.keys()):
                if k != "authenticated":
                    del st.session_state[k]
            st.rerun()


# ── Data Ingestion ────────────────────────────────────────────────────────────

def render_data_ingestion():
    st.markdown('<h2 style="color:#fafafa;">Data Ingestion</h2>', unsafe_allow_html=True)
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<h4 style="color:#fafafa;">ClickUp Tasks</h4>', unsafe_allow_html=True)
        if st.session_state.get("tasks") is not None:
            tasks = st.session_state["tasks"]
            st.markdown(f'<p style="color:#4CAF50;">✅ {len(tasks)} tasks from {st.session_state.get("space_name", "?")} → {st.session_state.get("list_name", "?")}</p>', unsafe_allow_html=True)
        else:
            c1, c2 = st.columns([2, 1])
            with c1:
                brand_name = st.text_input("Brand Name", placeholder="e.g., Eskiin", key="brand_input")
            with c2:
                date_range = st.selectbox("Date Range", [None, 7, 14, 30, 60, 90], index=0,
                                          format_func=lambda x: "All time" if x is None else f"Last {x}d", key="date_range_input")
            if st.button("🔍 Pull Tasks", use_container_width=True, disabled=not brand_name, key="pull_tasks_btn"):
                if "CLICKUP_API_KEY" not in check_env_vars():
                    from analyzer.clickup_client import find_brand_and_pull_tasks
                    with st.spinner(f"Searching for '{brand_name}'..."):
                        space_name, list_name, tasks = find_brand_and_pull_tasks(brand_name, date_range_days=date_range, fetch_comments=True)
                    if not space_name:
                        st.error(f"No space matching '{brand_name}'")
                    elif not list_name:
                        st.error(f"Found '{space_name}' but no Creative Team list")
                    else:
                        st.session_state.update({"tasks": tasks, "space_name": space_name, "list_name": list_name, "brand_name": brand_name, "date_range_str": f"{date_range} days" if date_range else "all time"})
                        st.rerun()
                else:
                    st.error("Set CLICKUP_API_KEY")

    with col_right:
        st.markdown('<h4 style="color:#fafafa;">Meta Ads CSV</h4>', unsafe_allow_html=True)
        if st.session_state.get("csv_ads") is not None:
            ads = st.session_state["csv_ads"]
            st.markdown(f'<p style="color:#4CAF50;">✅ {len(ads)} ads parsed — ${st.session_state.get("csv_total_spend", 0):,.0f} total spend</p>', unsafe_allow_html=True)
            # Show diagnostics
            diag = st.session_state.get("csv_diagnostics")
            if diag:
                with st.expander("📊 CSV Diagnostics (column mapping + data distribution)"):
                    st.markdown('<p style="color:#6C63FF;font-weight:bold;">Column Mapping</p>', unsafe_allow_html=True)
                    for our_field, csv_col in diag.column_mapping.items():
                        status = f'<span style="color:#4CAF50;">→ "{csv_col}"</span>' if csv_col else '<span style="color:#F44336;">NOT FOUND</span>'
                        st.markdown(f'<p style="color:#fafafa;font-size:12px;margin:1px 0;">{our_field}: {status}</p>', unsafe_allow_html=True)

                    st.markdown(f'<p style="color:#aaa;font-size:11px;margin-top:8px;">All CSV columns: {", ".join(diag.column_names)}</p>', unsafe_allow_html=True)

                    if diag.spend_stats:
                        st.markdown('<p style="color:#6C63FF;font-weight:bold;margin-top:12px;">Spend Distribution</p>', unsafe_allow_html=True)
                        st.markdown(f'<p style="color:#fafafa;font-size:12px;">Min: ${diag.spend_stats["min"]:,.2f} | Max: ${diag.spend_stats["max"]:,.2f} | Median: ${diag.spend_stats["median"]:,.2f} | Avg: ${diag.spend_stats["avg"]:,.2f}</p>', unsafe_allow_html=True)

                    if diag.roas_stats:
                        st.markdown('<p style="color:#6C63FF;font-weight:bold;margin-top:12px;">ROAS Distribution (non-zero only)</p>', unsafe_allow_html=True)
                        st.markdown(f'<p style="color:#fafafa;font-size:12px;">Min: {diag.roas_stats["min"]:.2f}x | Max: {diag.roas_stats["max"]:.2f}x | Median: {diag.roas_stats["median"]:.2f}x | Avg: {diag.roas_stats["avg"]:.2f}x</p>', unsafe_allow_html=True)

                    st.markdown('<p style="color:#6C63FF;font-weight:bold;margin-top:12px;">ROAS Breakdown</p>', unsafe_allow_html=True)
                    for label, count in diag.roas_below_threshold.items():
                        st.markdown(f'<p style="color:#fafafa;font-size:12px;margin:1px 0;">ROAS {label}: {count} ads</p>', unsafe_allow_html=True)

                    st.markdown('<p style="color:#6C63FF;font-weight:bold;margin-top:12px;">Spend Breakdown</p>', unsafe_allow_html=True)
                    for label, count in diag.spend_above_threshold.items():
                        st.markdown(f'<p style="color:#fafafa;font-size:12px;margin:1px 0;">Spend {label}: {count} ads</p>', unsafe_allow_html=True)

                    st.markdown('<p style="color:#6C63FF;font-weight:bold;margin-top:12px;">Combined Checks (potential winners/losers)</p>', unsafe_allow_html=True)
                    for label, count in diag.combined_checks.items():
                        st.markdown(f'<p style="color:#fafafa;font-size:12px;margin:1px 0;">{label}: {count} ads</p>', unsafe_allow_html=True)
        else:
            uploaded = st.file_uploader("Upload CSV", type=["csv"], key="csv_upload")
            if uploaded:
                from analyzer.csv_matcher import parse_meta_csv
                try:
                    content = uploaded.read()
                    ads, total_spend, diag = parse_meta_csv(content)
                    st.session_state["csv_ads"] = ads
                    st.session_state["csv_total_spend"] = total_spend
                    st.session_state["csv_diagnostics"] = diag
                    st.rerun()
                except Exception as e:
                    st.error(f"CSV parse failed: {e}")


# ── Shared display helpers ────────────────────────────────────────────────────

def render_classification_summary(classification):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Winners", f"{len(classification.winners)} ({classification.pillar_winners}P, {classification.strong_winners}S)")
    c2.metric("Average", len(classification.average))
    c3.metric("Losers", len(classification.losers))
    c4.metric("Untested", len(classification.untested))

    with st.expander(f"View all {len(classification.all_classified)} classified ads"):
        for ad in classification.all_classified:
            cls_c = {"winner": "#4CAF50", "average": "#FF9800", "loser": "#F44336", "untested": "#888"}.get(ad.classification.value, "#888")
            wt_c = {"pillar": "#FFD700", "strong": "#6C63FF", "normal": "#4CAF50", "minor": "#888"}.get(ad.weight_tier.value, "#888")
            st.markdown(f"""<div style="background:#1A1D24;border-left:4px solid {cls_c};border-radius:4px;padding:8px 12px;margin-bottom:4px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#fafafa;font-size:13px;">{ad.match.task.name[:60]}</span>
                    <span>
                        <span style="background:{cls_c};color:#0E1117;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;">{ad.classification.value.upper()}</span>
                        <span style="background:{wt_c};color:#0E1117;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;margin-left:4px;">{ad.weight_tier.value.upper()}</span>
                    </span>
                </div>
                <p style="color:#aaa;font-size:11px;margin:2px 0;">Spend: ${ad.match.total_spend:,.0f} ({ad.spend_share*100:.1f}%) | ROAS: {ad.match.weighted_roas:.2f}x | Value: ${ad.value_score:,.0f}</p>
            </div>""", unsafe_allow_html=True)

    # Show classification log
    if classification.classification_log:
        with st.expander("📋 Classification Log (debug)"):
            for line in classification.classification_log:
                color = "#fafafa"
                if line.startswith("WINNER"):
                    color = "#4CAF50"
                elif line.startswith("LOSER"):
                    color = "#F44336"
                elif line.startswith("AVERAGE"):
                    color = "#FF9800"
                elif line.startswith("UNTESTED"):
                    color = "#888"
                st.markdown(f'<p style="color:{color};font-size:11px;font-family:monospace;margin:1px 0;">{line}</p>', unsafe_allow_html=True)


def render_match_log(match_summary):
    if match_summary.match_log:
        with st.expander("📋 Match Log (debug)"):
            for line in match_summary.match_log:
                color = "#fafafa"
                if line.startswith("MATCH:"):
                    color = "#4CAF50"
                elif line.startswith("NO MATCH:"):
                    color = "#F44336"
                elif line.startswith("SKIP:"):
                    color = "#888"
                st.markdown(f'<p style="color:{color};font-size:11px;font-family:monospace;margin:1px 0;">{line}</p>', unsafe_allow_html=True)


def render_pattern_analysis_display(pa):
    st.markdown(pa.raw_analysis)
    if pa.cross_insights:
        st.markdown('<h4 style="color:#fafafa;">Key Cross-Pattern Insights</h4>', unsafe_allow_html=True)
        for insight in pa.cross_insights:
            st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #6C63FF;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{insight}</p></div>', unsafe_allow_html=True)


def render_hypotheses_display(hr):
    st.markdown('<h4 style="color:#fafafa;">Key Learnings</h4>', unsafe_allow_html=True)
    for i, learning in enumerate(hr.learnings, 1):
        conf_c = {"HIGH": "#4CAF50", "MEDIUM": "#FF9800", "LOW": "#F44336"}.get(learning.confidence.upper(), "#888")
        evidence = ", ".join(learning.supporting_evidence) if learning.supporting_evidence else "See analysis"
        st.markdown(f"""<div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="color:#fafafa;font-weight:bold;font-size:15px;">Learning {i}</span>
                <span style="background:{conf_c};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{learning.confidence}</span>
            </div>
            <p style="color:#fafafa;margin:4px 0;">{learning.observation}</p>
            <p style="color:#aaa;font-size:12px;margin:4px 0;"><strong>Evidence:</strong> {evidence}</p>
        </div>""", unsafe_allow_html=True)

    st.markdown('<h4 style="color:#fafafa;">Testable Hypotheses</h4>', unsafe_allow_html=True)
    for i, hyp in enumerate(hr.hypotheses, 1):
        pri_c = {"HIGH": "#F44336", "MEDIUM": "#FF9800", "LOW": "#4CAF50"}.get(hyp.priority.upper(), "#888")
        hooks_html = "".join(f"<li style='color:#fafafa;font-size:13px;'>{h}</li>" for h in hyp.suggested_hook_ideas) if hyp.suggested_hook_ideas else "<li style='color:#aaa;'>See analysis</li>"
        st.markdown(f"""<div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="color:#fafafa;font-weight:bold;font-size:15px;">Hypothesis {i}</span>
                <span style="background:{pri_c};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{hyp.priority}</span>
            </div>
            <p style="color:#aaa;font-size:12px;margin:4px 0;"><em>Based on: {hyp.based_on_learning}</em></p>
            <p style="color:#fafafa;margin:4px 0;"><strong>Test:</strong> {hyp.independent_variable}</p>
            <p style="color:#fafafa;margin:4px 0;"><strong>Expected:</strong> {hyp.expected_outcome}</p>
            <div style="margin-top:8px;padding:12px;background:#0E1117;border-radius:4px;">
                <p style="color:#6C63FF;margin:0 0 4px 0;font-weight:bold;font-size:13px;">Suggested Script Outline</p>
                <ul style="margin:4px 0;padding-left:16px;">{hooks_html}</ul>
                <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Body:</strong> {hyp.suggested_body_structure or 'See analysis'}</p>
                <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Format:</strong> {hyp.recommended_format or 'Based on winners'}</p>
            </div>
        </div>""", unsafe_allow_html=True)


def render_scripts_display(scripts):
    no_content = [s for s in scripts.values() if s.no_content_found]
    manual_review = [s for s in scripts.values() if s.manual_review_links]
    if no_content:
        with st.expander(f"⚠️ {len(no_content)} tasks — no brief/script found"):
            for s in no_content:
                st.markdown(f'<p style="color:#fafafa;">⚠️ <strong>{s.task_name}</strong> — <a href="https://app.clickup.com/t/{s.task_id}" style="color:#6C63FF;">Check task</a></p>', unsafe_allow_html=True)
    if manual_review:
        with st.expander(f"📋 {len(manual_review)} tasks — manual doc review needed"):
            for s in manual_review:
                for link in s.manual_review_links:
                    st.markdown(f'<p style="color:#fafafa;">📋 <strong>{s.task_name}</strong> — <a href="{link}" style="color:#6C63FF;">{link[:60]}...</a></p>', unsafe_allow_html=True)
    with_content = [s for s in scripts.values() if not s.no_content_found]
    if with_content:
        with st.expander(f"Preview scripts ({min(5, len(with_content))} of {len(with_content)})"):
            for s in list(with_content)[:5]:
                hooks_display = " | ".join(s.hooks[:3]) if s.hooks else "None"
                st.markdown(f"""<div style="background:#1A1D24;border-radius:8px;padding:12px;margin-bottom:8px;">
                    <p style="color:#6C63FF;font-weight:bold;margin:0;">{s.task_name}</p>
                    <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Hooks:</strong> {hooks_display}</p>
                    <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Pain point:</strong> {s.pain_point or 'N/A'} | <strong>Root cause:</strong> {s.root_cause or 'N/A'} ({s.root_cause_depth or '?'})</p>
                    <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Format:</strong> {s.ad_format or 'N/A'} | <strong>Awareness:</strong> {s.awareness_level or 'N/A'} | <strong>Lead:</strong> {s.lead_type or 'N/A'}</p>
                </div>""", unsafe_allow_html=True)


# ── Tab 1: Recent Creative ───────────────────────────────────────────────────

def render_tab_recent():
    st.markdown('<h2 style="color:#fafafa;">Section A — Recent Creative Analysis</h2>', unsafe_allow_html=True)
    st.markdown('<p style="color:#aaa;">What\'s working and what\'s failing in recent launches?</p>', unsafe_allow_html=True)

    tasks = st.session_state.get("tasks")
    csv_ads = st.session_state.get("csv_ads")
    if not tasks or not csv_ads:
        st.warning("Upload ClickUp tasks and Meta CSV first (Data Ingestion above).")
        return

    # Thresholds for recent (with spend minimums)
    st.markdown('<h4 style="color:#fafafa;">Classification Thresholds</h4>', unsafe_allow_html=True)
    with st.expander("Set thresholds", expanded=not st.session_state.get("thresholds_set")):
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            wr = st.number_input("Winner ROAS ≥", value=1.5, step=0.1, min_value=0.0, key="r_wr")
        with c2:
            ws = st.number_input("Winner min $", value=500.0, step=100.0, min_value=0.0, key="r_ws")
        with c3:
            lr = st.number_input("Loser ROAS ≤", value=0.8, step=0.1, min_value=0.0, key="r_lr")
        with c4:
            ls = st.number_input("Loser min $", value=500.0, step=100.0, min_value=0.0, key="r_ls")
        with c5:
            us = st.number_input("Untested max $", value=100.0, step=50.0, min_value=0.0, key="r_us")

    # Step 1: Match & Classify
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">1. Match & Classify</h3>', unsafe_allow_html=True)

    if st.session_state.get("classification"):
        ms = st.session_state["match_summary"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Matched", ms.total_matched)
        c2.metric("Unmatched Tasks", ms.total_unmatched_tasks)
        c3.metric("Unmatched CSV", ms.total_unmatched_csv)
        render_match_log(ms)
        render_classification_summary(st.session_state["classification"])
    else:
        if st.button("🔗 Match & Classify Recent Ads", use_container_width=True, key="recent_classify"):
            from analyzer.csv_matcher import match_tasks_to_csv
            from analyzer.classifier import Thresholds, classify_ads
            total_spend = st.session_state.get("csv_total_spend", 0)
            with st.spinner("Matching..."):
                ms = match_tasks_to_csv(tasks, csv_ads, total_spend)
            st.session_state["match_summary"] = ms
            t = Thresholds(winner_roas=wr, winner_min_spend=ws, loser_roas=lr, loser_min_spend=ls, untested_max_spend=us)
            clf = classify_ads(ms, t)
            st.session_state["classification"] = clf
            st.session_state["thresholds_set"] = True
            st.rerun()
        return

    # Step 2: Read Scripts
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">2. Read Scripts</h3>', unsafe_allow_html=True)
    classification = st.session_state["classification"]
    if st.session_state.get("scripts"):
        render_scripts_display(st.session_state["scripts"])
    else:
        if "ANTHROPIC_API_KEY" in check_env_vars():
            st.error("Set ANTHROPIC_API_KEY"); return
        matched_tasks = [ad.match.task for ad in classification.all_classified if ad.classification.value != "untested"]
        st.markdown(f'<p style="color:#fafafa;">{len(matched_tasks)} tasks to read</p>', unsafe_allow_html=True)
        if st.button("📖 Read Scripts (Claude)", use_container_width=True, key="recent_scripts"):
            from analyzer.script_reader import read_all_scripts
            progress = st.progress(0)
            status = st.empty()
            def cb(i, t, n):
                progress.progress((i+1)/t)
                status.markdown(f'<p style="color:#aaa;font-size:12px;">{i+1}/{t}: {n[:50]}...</p>', unsafe_allow_html=True)
            with st.spinner("Reading scripts..."):
                scripts = read_all_scripts(matched_tasks, use_claude=True, progress_callback=cb)
            st.session_state["scripts"] = {s.task_id: s for s in scripts}
            progress.empty(); status.empty()
            st.rerun()
        return

    # Step 3: Pattern Analysis
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">3. Pattern Analysis</h3>', unsafe_allow_html=True)
    if st.session_state.get("pattern_analysis"):
        render_pattern_analysis_display(st.session_state["pattern_analysis"])
    else:
        if st.button("🔬 Run Pattern Analysis (Claude)", use_container_width=True, key="recent_patterns"):
            from analyzer.pattern_analyzer import analyze_patterns
            with st.spinner("Analyzing patterns..."):
                pa = analyze_patterns(classification, st.session_state["scripts"])
            st.session_state["pattern_analysis"] = pa
            st.rerun()
        return

    # Step 4: Hypotheses
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">4. Learnings & Hypotheses</h3>', unsafe_allow_html=True)
    if st.session_state.get("hypothesis_report"):
        render_hypotheses_display(st.session_state["hypothesis_report"])
    else:
        if st.button("💡 Generate Hypotheses (Claude)", use_container_width=True, key="recent_hyp"):
            from analyzer.hypothesis_generator import generate_hypotheses
            with st.spinner("Generating hypotheses..."):
                hr = generate_hypotheses(st.session_state["pattern_analysis"], classification)
            st.session_state["hypothesis_report"] = hr
            st.rerun()


# ── Tab 2: Top 50 Account Ads ────────────────────────────────────────────────

def render_tab_top50():
    st.markdown('<h2 style="color:#fafafa;">Section B — Top 50 All-Time Spenders</h2>', unsafe_allow_html=True)
    st.markdown('<p style="color:#aaa;">Top 50 ads by spend across the entire CSV. No date filter, no spend minimum. ROAS-only classification.</p>', unsafe_allow_html=True)

    tasks = st.session_state.get("tasks")
    csv_ads = st.session_state.get("csv_ads")
    if not tasks or not csv_ads:
        st.warning("Upload ClickUp tasks and Meta CSV first.")
        return

    # ROAS thresholds only (no spend min for top 50)
    with st.expander("ROAS Thresholds (no spend minimum for top 50)", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            t50_wr = st.number_input("Winner ROAS ≥", value=1.5, step=0.1, min_value=0.0, key="t50_wr")
        with c2:
            t50_lr = st.number_input("Loser ROAS ≤", value=0.8, step=0.1, min_value=0.0, key="t50_lr")

    # Step 1: Get Top 50 & Match & Classify
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">1. Top 50 by Spend — Match & Classify</h3>', unsafe_allow_html=True)

    if st.session_state.get("top50_classification"):
        ms = st.session_state["top50_match_summary"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Top 50 Ads", len(st.session_state.get("top50_ads", [])))
        c2.metric("Matched to ClickUp", ms.total_matched)
        c3.metric("Unmatched (no task)", ms.total_unmatched_csv)
        top50_spend = sum(a.spend for a in st.session_state.get("top50_ads", []))
        c4.metric("Top 50 Total Spend", f"${top50_spend:,.0f}")
        render_match_log(ms)
        render_classification_summary(st.session_state["top50_classification"])
    else:
        if st.button("🔗 Get Top 50 & Classify", use_container_width=True, key="top50_classify"):
            from analyzer.csv_matcher import get_top_ads_by_spend, match_tasks_to_csv
            from analyzer.classifier import classify_top50

            top50_ads = get_top_ads_by_spend(csv_ads, top_n=50)
            st.session_state["top50_ads"] = top50_ads
            total_spend = st.session_state.get("csv_total_spend", 0)

            with st.spinner("Matching top 50 ads to ClickUp tasks..."):
                ms = match_tasks_to_csv(tasks, top50_ads, total_spend)
            st.session_state["top50_match_summary"] = ms

            # ROAS-only classification — no spend minimum
            clf = classify_top50(ms, winner_roas=t50_wr, loser_roas=t50_lr)
            st.session_state["top50_classification"] = clf
            st.rerun()
        return

    # Step 2: Read Scripts
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">2. Read Scripts</h3>', unsafe_allow_html=True)
    classification = st.session_state["top50_classification"]
    if st.session_state.get("top50_scripts"):
        render_scripts_display(st.session_state["top50_scripts"])
    else:
        if "ANTHROPIC_API_KEY" in check_env_vars():
            st.error("Set ANTHROPIC_API_KEY"); return
        matched_tasks = [ad.match.task for ad in classification.all_classified]
        existing_scripts = st.session_state.get("scripts", {}) or {}
        new_tasks = [t for t in matched_tasks if t.task_id not in existing_scripts]
        reused = len(matched_tasks) - len(new_tasks)
        st.markdown(f'<p style="color:#fafafa;">{len(matched_tasks)} tasks ({reused} reused, {len(new_tasks)} new)</p>', unsafe_allow_html=True)
        if st.button("📖 Read Scripts (Claude)", use_container_width=True, key="top50_scripts_btn"):
            from analyzer.script_reader import read_all_scripts
            progress = st.progress(0)
            status = st.empty()
            def cb(i, t, n):
                progress.progress((i+1)/t)
                status.markdown(f'<p style="color:#aaa;font-size:12px;">{i+1}/{t}: {n[:50]}...</p>', unsafe_allow_html=True)
            if new_tasks:
                with st.spinner("Reading scripts..."):
                    new_scripts = read_all_scripts(new_tasks, use_claude=True, progress_callback=cb)
                new_dict = {s.task_id: s for s in new_scripts}
            else:
                new_dict = {}
            merged = dict(existing_scripts)
            merged.update(new_dict)
            top50_task_ids = {ad.match.task.task_id for ad in classification.all_classified}
            st.session_state["top50_scripts"] = {k: v for k, v in merged.items() if k in top50_task_ids}
            progress.empty(); status.empty()
            st.rerun()
        return

    # Step 3: Pattern Analysis
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">3. Pattern Analysis</h3>', unsafe_allow_html=True)
    if st.session_state.get("top50_pattern_analysis"):
        render_pattern_analysis_display(st.session_state["top50_pattern_analysis"])
    else:
        if st.button("🔬 Run Pattern Analysis (Claude)", use_container_width=True, key="top50_patterns"):
            from analyzer.pattern_analyzer import analyze_patterns
            with st.spinner("Analyzing top 50 patterns..."):
                pa = analyze_patterns(classification, st.session_state["top50_scripts"])
            st.session_state["top50_pattern_analysis"] = pa
            st.rerun()
        return

    # Step 4: Hypotheses
    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">4. Learnings & Hypotheses</h3>', unsafe_allow_html=True)
    if st.session_state.get("top50_hypothesis_report"):
        render_hypotheses_display(st.session_state["top50_hypothesis_report"])
    else:
        if st.button("💡 Generate Hypotheses (Claude)", use_container_width=True, key="top50_hyp"):
            from analyzer.hypothesis_generator import generate_hypotheses
            with st.spinner("Generating hypotheses..."):
                hr = generate_hypotheses(st.session_state["top50_pattern_analysis"], classification)
            st.session_state["top50_hypothesis_report"] = hr
            st.rerun()


# ── Tab 3: Comparison ────────────────────────────────────────────────────────

def render_tab_comparison():
    st.markdown('<h2 style="color:#fafafa;">Section C — Recent vs All-Time Comparison</h2>', unsafe_allow_html=True)
    st.markdown('<p style="color:#aaa;">Is your creative team getting better or worse? Where are they drifting from proven patterns?</p>', unsafe_allow_html=True)

    recent_pa = st.session_state.get("pattern_analysis")
    alltime_pa = st.session_state.get("top50_pattern_analysis")
    if not recent_pa or not alltime_pa:
        st.warning("Complete pattern analysis in both 'Recent Creative' and 'Top 50 Account Ads' tabs first.")
        missing = []
        if not recent_pa:
            missing.append("Recent Creative → Pattern Analysis")
        if not alltime_pa:
            missing.append("Top 50 Account Ads → Pattern Analysis")
        for m in missing:
            st.markdown(f'<p style="color:#F44336;">⬜ {m}</p>', unsafe_allow_html=True)
        return

    if st.session_state.get("comparison_analysis"):
        comp = st.session_state["comparison_analysis"]
        st.markdown(comp.raw_comparison)
        if comp.drift_alerts:
            st.markdown("---")
            st.markdown('<h3 style="color:#F44336;">Pattern Drifts</h3>', unsafe_allow_html=True)
            for d in comp.drift_alerts:
                st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #F44336;padding:10px 14px;margin-bottom:8px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{d}</p></div>', unsafe_allow_html=True)
        if comp.consistent_patterns:
            with st.expander("✅ Consistent Patterns", expanded=False):
                for c in comp.consistent_patterns:
                    st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #4CAF50;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{c}</p></div>', unsafe_allow_html=True)
        if comp.new_patterns:
            with st.expander("🆕 New Patterns", expanded=False):
                for n in comp.new_patterns:
                    st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #FF9800;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{n}</p></div>', unsafe_allow_html=True)
        if comp.recommendations:
            st.markdown("---")
            st.markdown('<h3 style="color:#6C63FF;">Recommendations</h3>', unsafe_allow_html=True)
            for r in comp.recommendations:
                st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #6C63FF;padding:10px 14px;margin-bottom:8px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{r}</p></div>', unsafe_allow_html=True)
    else:
        date_range = st.session_state.get("date_range_str", "30 days")
        if st.button("🔍 Run Comparison Analysis (Claude)", use_container_width=True, key="run_comparison"):
            from analyzer.pattern_analyzer import compare_patterns
            with st.spinner("Comparing patterns..."):
                comp = compare_patterns(recent_pa, alltime_pa, date_range=date_range)
            st.session_state["comparison_analysis"] = comp
            st.rerun()


# ── Tab 4: Reports ────────────────────────────────────────────────────────────

def render_tab_reports():
    st.markdown('<h2 style="color:#fafafa;">Reports</h2>', unsafe_allow_html=True)
    classification = st.session_state.get("classification")
    pattern_analysis = st.session_state.get("pattern_analysis")
    hypothesis_report = st.session_state.get("hypothesis_report")
    has_recent = all([classification, pattern_analysis, hypothesis_report])

    if has_recent:
        st.markdown('<h3 style="color:#fafafa;">Export Full Report</h3>', unsafe_allow_html=True)
        sections = ["A: Recent"]
        if st.session_state.get("top50_pattern_analysis"):
            sections.append("B: Top 50")
        if st.session_state.get("comparison_analysis"):
            sections.append("C: Comparison")
        st.markdown(f'<p style="color:#aaa;">Includes: {" + ".join(sections)}</p>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📄 Export HTML", use_container_width=True, key="export_html"):
                from analyzer.report_generator import generate_html_report, save_report
                brand = st.session_state.get("brand_name", "Unknown")
                html = generate_html_report(
                    brand, classification, pattern_analysis, hypothesis_report,
                    date_range=st.session_state.get("date_range_str"),
                    alltime_classification=st.session_state.get("top50_classification"),
                    alltime_pattern_analysis=st.session_state.get("top50_pattern_analysis"),
                    alltime_hypothesis_report=st.session_state.get("top50_hypothesis_report"),
                    comparison=st.session_state.get("comparison_analysis"),
                )
                path = save_report(brand, html, format="html")
                st.success(f"Saved: {path}")
                st.download_button("⬇️ Download", html, file_name=f"{brand}_report.html", mime="text/html", key="dl_html")
        with col2:
            if st.button("📑 Export PDF", use_container_width=True, key="export_pdf"):
                from analyzer.report_generator import generate_html_report, save_report
                brand = st.session_state.get("brand_name", "Unknown")
                html = generate_html_report(
                    brand, classification, pattern_analysis, hypothesis_report,
                    date_range=st.session_state.get("date_range_str"),
                    alltime_classification=st.session_state.get("top50_classification"),
                    alltime_pattern_analysis=st.session_state.get("top50_pattern_analysis"),
                    alltime_hypothesis_report=st.session_state.get("top50_hypothesis_report"),
                    comparison=st.session_state.get("comparison_analysis"),
                )
                path = save_report(brand, html, format="pdf")
                if path.suffix == ".pdf":
                    st.success(f"PDF saved: {path}")
                    st.download_button("⬇️ Download", path.read_bytes(), file_name=f"{brand}_report.pdf", mime="application/pdf", key="dl_pdf")
                else:
                    st.warning("PDF requires `weasyprint`. Saved as HTML.")
                    st.download_button("⬇️ Download", html, file_name=f"{brand}_report.html", mime="text/html", key="dl_pdf_fb")
    else:
        st.info("Complete Recent Creative analysis to enable export.")

    st.markdown("---")
    st.markdown('<h3 style="color:#fafafa;">Reports History</h3>', unsafe_allow_html=True)
    from analyzer.report_generator import list_reports
    reports = list_reports()
    if not reports:
        st.markdown('<p style="color:#aaa;">No reports yet.</p>', unsafe_allow_html=True)
        return
    for r in reports:
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f'<p style="color:#fafafa;margin:0;">{r["name"]}</p>', unsafe_allow_html=True)
            st.markdown(f'<p style="color:#aaa;font-size:12px;margin:0;">{r["created"]} | {r["format"].upper()} | {r["size"]/1024:.1f} KB</p>', unsafe_allow_html=True)
        with col2:
            rp = Path(r["path"])
            if rp.exists():
                mime = "application/pdf" if r["format"] == "pdf" else "text/html"
                st.download_button("⬇️", rp.read_bytes(), file_name=rp.name, mime=mime, key=f"dl_{r['name']}")
        with col3:
            if st.button("🗑️", key=f"del_{r['name']}"):
                Path(r["path"]).unlink(missing_ok=True)
                st.rerun()
        st.markdown('<hr style="border:0;border-top:1px solid #333;margin:4px 0;">', unsafe_allow_html=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_state()
    if not check_login():
        return
    render_sidebar()
    st.markdown('<h1 style="color:#fafafa;">🔄 Creative Feedback Loop Analyzer</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#aaa;">Pull creative briefs → Match performance → Find patterns → Detect drift</p>', unsafe_allow_html=True)
    render_data_ingestion()
    st.markdown("---")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Recent Creative", "🏆 Top 50 Account Ads", "🔄 Recent vs All-Time", "📁 Reports"])
    with tab1:
        render_tab_recent()
    with tab2:
        render_tab_top50()
    with tab3:
        render_tab_comparison()
    with tab4:
        render_tab_reports()


if __name__ == "__main__":
    main()
else:
    main()
