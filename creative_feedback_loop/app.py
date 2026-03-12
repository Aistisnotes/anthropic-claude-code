"""Creative Feedback Loop Analyzer — Streamlit App

Pulls creative briefs from ClickUp, matches with Meta Ads Manager CSV performance data,
generates pattern analysis + learnings + hypotheses across winners vs losers.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

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
    /* Force dark backgrounds */
    .stApp { background-color: #0E1117; }
    .stSidebar { background-color: #1A1D24; }
    /* All text white */
    .stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp td, .stApp th {
        color: #fafafa !important;
    }
    /* Headers */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #fafafa !important; }
    /* Input fields */
    .stTextInput input, .stNumberInput input, .stSelectbox select {
        background-color: #1A1D24 !important;
        color: #fafafa !important;
    }
    /* Buttons */
    .stButton > button {
        background-color: #6C63FF !important;
        color: #fafafa !important;
        border: none !important;
        border-radius: 8px !important;
    }
    .stButton > button:hover {
        background-color: #5A52E0 !important;
    }
    /* Tabs */
    .stTabs [data-baseweb="tab"] { color: #fafafa !important; }
    .stTabs [aria-selected="true"] { border-bottom-color: #6C63FF !important; }
    /* Metrics */
    [data-testid="stMetricValue"] { color: #6C63FF !important; }
    [data-testid="stMetricLabel"] { color: #aaa !important; }
    /* Expander */
    .streamlit-expanderHeader { color: #fafafa !important; }
    /* File uploader */
    [data-testid="stFileUploader"] label { color: #fafafa !important; }
    /* Progress */
    .stProgress > div > div { background-color: #6C63FF !important; }
    /* Alert boxes */
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


def check_env_vars() -> list[str]:
    """Check required environment variables."""
    missing = []
    if not os.environ.get("CLICKUP_API_KEY"):
        missing.append("CLICKUP_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    return missing


# ── Session state init ────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "tasks": None,
        "space_name": None,
        "list_name": None,
        "scripts": None,
        "csv_ads": None,
        "match_summary": None,
        "classification": None,
        "pattern_analysis": None,
        "hypothesis_report": None,
        "step": 1,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown('<h2 style="color:#fafafa;">🔄 Creative Feedback Loop</h2>', unsafe_allow_html=True)
        st.markdown('<p style="color:#aaa;font-size:13px;">Pull creative briefs → Match performance → Find patterns</p>', unsafe_allow_html=True)
        st.markdown("---")

        page = st.radio(
            "Navigation",
            ["Dashboard", "Reports History"],
            label_visibility="collapsed",
        )

        st.markdown("---")
        st.markdown('<p style="color:#aaa;font-size:12px;">Pipeline Progress</p>', unsafe_allow_html=True)

        steps = [
            ("1. Pull ClickUp Tasks", st.session_state.get("tasks") is not None),
            ("2. Upload Meta CSV", st.session_state.get("csv_ads") is not None),
            ("3. Match & Classify", st.session_state.get("classification") is not None),
            ("4. Read Scripts", st.session_state.get("scripts") is not None),
            ("5. Pattern Analysis", st.session_state.get("pattern_analysis") is not None),
            ("6. Hypotheses", st.session_state.get("hypothesis_report") is not None),
        ]
        for label, done in steps:
            icon = "✅" if done else "⬜"
            st.markdown(f'<p style="color:#fafafa;font-size:13px;margin:2px 0;">{icon} {label}</p>', unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🔄 Reset Pipeline", use_container_width=True):
            for k in ["tasks", "space_name", "list_name", "scripts", "csv_ads",
                       "match_summary", "classification", "pattern_analysis",
                       "hypothesis_report"]:
                st.session_state[k] = None
            st.session_state["step"] = 1
            st.rerun()

    return page


# ── Step 1: Pull ClickUp Tasks ───────────────────────────────────────────────

def render_step1():
    st.markdown('<h2 style="color:#fafafa;">Step 1: Pull Creative Tasks from ClickUp</h2>', unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        brand_name = st.text_input(
            "Brand Name",
            placeholder="e.g., Eskiin",
            help="Fuzzy matches to ClickUp Space name",
        )
    with col2:
        date_range = st.selectbox(
            "Date Range (days)",
            [None, 7, 14, 30, 60, 90],
            index=0,
            format_func=lambda x: "All time" if x is None else f"Last {x} days",
        )

    if st.button("🔍 Find Brand & Pull Tasks", use_container_width=True, disabled=not brand_name):
        missing = check_env_vars()
        if "CLICKUP_API_KEY" in missing:
            st.error("Set CLICKUP_API_KEY environment variable first")
            return

        from analyzer.clickup_client import find_brand_and_pull_tasks

        with st.spinner(f"Searching for '{brand_name}' in ClickUp..."):
            space_name, list_name, tasks = find_brand_and_pull_tasks(
                brand_name,
                date_range_days=date_range,
                fetch_comments=True,
            )

        if not space_name:
            st.error(f"Could not find a space matching '{brand_name}'. Check spelling or try a different name.")
            return
        if not list_name:
            st.error(f"Found space '{space_name}' but could not find a Creative Team list.")
            return

        st.session_state["tasks"] = tasks
        st.session_state["space_name"] = space_name
        st.session_state["list_name"] = list_name
        st.session_state["brand_name"] = brand_name
        st.success(f"Found **{space_name}** → **{list_name}** — Pulled **{len(tasks)}** tasks")
        st.rerun()

    # Show pulled tasks
    if st.session_state.get("tasks"):
        tasks = st.session_state["tasks"]
        st.markdown(f'<p style="color:#fafafa;">📋 <strong>{len(tasks)} tasks</strong> from '
                     f'<strong>{st.session_state["space_name"]}</strong> → '
                     f'<strong>{st.session_state["list_name"]}</strong></p>', unsafe_allow_html=True)

        # Sample tasks
        with st.expander(f"Preview tasks ({min(10, len(tasks))} of {len(tasks)})"):
            for task in tasks[:10]:
                cf_display = ", ".join(f"{k}: {v}" for k, v in task.custom_fields.items() if v) or "None"
                doc_count = len(task.gdoc_links)
                comment_count = len(task.comments)
                folder_count = len(task.gdrive_folder_links)

                st.markdown(f"""
                <div style="background:#1A1D24;border-radius:8px;padding:12px;margin-bottom:8px;">
                    <p style="color:#6C63FF;font-weight:bold;margin:0;">{task.name}</p>
                    <p style="color:#aaa;font-size:12px;margin:2px 0;">Status: {task.status} | Created: {task.date_created.strftime('%Y-%m-%d') if task.date_created else 'N/A'} | Launched: {task.date_launched.strftime('%Y-%m-%d') if task.date_launched else 'N/A'}</p>
                    <p style="color:#aaa;font-size:12px;margin:2px 0;">Custom fields: {cf_display}</p>
                    <p style="color:#aaa;font-size:12px;margin:2px 0;">📄 {doc_count} Google Docs | 💬 {comment_count} comments | 📁 {folder_count} folder links</p>
                    <p style="color:#888;font-size:11px;margin:2px 0;">Description: {(task.description or 'None')[:200]}...</p>
                </div>
                """, unsafe_allow_html=True)


# ── Step 2: Upload Meta CSV ──────────────────────────────────────────────────

def render_step2():
    st.markdown('<h2 style="color:#fafafa;">Step 2: Upload Meta Ads Manager CSV</h2>', unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Upload CSV export from Meta Ads Manager",
        type=["csv"],
        help="Export from Meta Ads Manager with ad-level data",
    )

    if uploaded:
        from analyzer.csv_matcher import parse_meta_csv

        try:
            content = uploaded.read()
            ads, total_spend = parse_meta_csv(content)
            st.session_state["csv_ads"] = ads
            st.session_state["csv_total_spend"] = total_spend
            st.success(f"Parsed **{len(ads)}** ads from CSV — Total spend: **${total_spend:,.2f}**")

            # Preview
            with st.expander(f"Preview CSV ads ({min(10, len(ads))} of {len(ads)})"):
                for ad in ads[:10]:
                    st.markdown(f"""
                    <div style="background:#1A1D24;border-radius:8px;padding:8px;margin-bottom:4px;">
                        <p style="color:#fafafa;margin:0;font-size:13px;">{ad.ad_name}</p>
                        <p style="color:#aaa;font-size:11px;margin:2px 0;">Spend: ${ad.spend:,.2f} | ROAS: {ad.roas:.2f}x | CTR: {ad.ctr:.2f}% | Conversions: {ad.conversions}</p>
                    </div>
                    """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Failed to parse CSV: {e}")


# ── Step 3: Match & Classify ─────────────────────────────────────────────────

def render_step3():
    st.markdown('<h2 style="color:#fafafa;">Step 3: Match & Classify</h2>', unsafe_allow_html=True)

    tasks = st.session_state.get("tasks")
    csv_ads = st.session_state.get("csv_ads")

    if not tasks or not csv_ads:
        st.warning("Complete Steps 1 and 2 first.")
        return

    # Threshold controls
    st.markdown('<h4 style="color:#fafafa;">Classification Thresholds</h4>', unsafe_allow_html=True)
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        winner_roas = st.number_input("Winner ROAS ≥", value=1.5, step=0.1, min_value=0.0)
    with col2:
        winner_spend = st.number_input("Winner min spend $", value=500.0, step=100.0, min_value=0.0)
    with col3:
        loser_roas = st.number_input("Loser ROAS ≤", value=0.8, step=0.1, min_value=0.0)
    with col4:
        loser_spend = st.number_input("Loser min spend $", value=500.0, step=100.0, min_value=0.0)
    with col5:
        untested_spend = st.number_input("Untested max spend $", value=100.0, step=50.0, min_value=0.0)

    if st.button("🔗 Match & Classify", use_container_width=True):
        from analyzer.csv_matcher import match_tasks_to_csv
        from analyzer.classifier import Thresholds, classify_ads

        total_spend = st.session_state.get("csv_total_spend", 0)

        with st.spinner("Matching tasks to CSV ads..."):
            match_summary = match_tasks_to_csv(tasks, csv_ads, total_spend)

        st.session_state["match_summary"] = match_summary

        # Classify
        thresholds = Thresholds(
            winner_roas=winner_roas,
            winner_min_spend=winner_spend,
            loser_roas=loser_roas,
            loser_min_spend=loser_spend,
            untested_max_spend=untested_spend,
        )

        classification = classify_ads(match_summary, thresholds)
        st.session_state["classification"] = classification
        st.rerun()

    # Display results
    if st.session_state.get("match_summary"):
        ms = st.session_state["match_summary"]
        st.markdown('<h4 style="color:#fafafa;">Match Summary</h4>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Matched", ms.total_matched)
        c2.metric("Unmatched Tasks", ms.total_unmatched_tasks)
        c3.metric("Unmatched CSV", ms.total_unmatched_csv)

    if st.session_state.get("classification"):
        clf = st.session_state["classification"]
        st.markdown('<h4 style="color:#fafafa;">Classification Results</h4>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Winners", f"{len(clf.winners)} ({clf.pillar_winners} pillar, {clf.strong_winners} strong)")
        c2.metric("Average", len(clf.average))
        c3.metric("Losers", len(clf.losers))
        c4.metric("Untested", len(clf.untested))

        # Detailed table
        with st.expander("View all classified ads"):
            for ad in clf.all_classified:
                cls_color = {"winner": "#4CAF50", "average": "#FF9800", "loser": "#F44336", "untested": "#888"}.get(ad.classification.value, "#888")
                wt_color = {"pillar": "#FFD700", "strong": "#6C63FF", "normal": "#4CAF50", "minor": "#888"}.get(ad.weight_tier.value, "#888")
                st.markdown(f"""
                <div style="background:#1A1D24;border-left:4px solid {cls_color};border-radius:4px;padding:8px 12px;margin-bottom:4px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span style="color:#fafafa;font-size:13px;">{ad.match.task.name[:60]}</span>
                        <span>
                            <span style="background:{cls_color};color:#0E1117;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;">{ad.classification.value.upper()}</span>
                            <span style="background:{wt_color};color:#0E1117;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;margin-left:4px;">{ad.weight_tier.value.upper()}</span>
                        </span>
                    </div>
                    <p style="color:#aaa;font-size:11px;margin:2px 0;">Spend: ${ad.match.total_spend:,.0f} ({ad.spend_share*100:.1f}%) | ROAS: {ad.match.weighted_roas:.2f}x | Value: ${ad.value_score:,.0f}</p>
                </div>
                """, unsafe_allow_html=True)


# ── Step 4: Read Scripts ──────────────────────────────────────────────────────

def render_step4():
    st.markdown('<h2 style="color:#fafafa;">Step 4: Read Scripts & Briefs</h2>', unsafe_allow_html=True)

    classification = st.session_state.get("classification")
    if not classification:
        st.warning("Complete Step 3 first.")
        return

    missing = check_env_vars()
    if "ANTHROPIC_API_KEY" in missing:
        st.error("Set ANTHROPIC_API_KEY environment variable first")
        return

    # Only read scripts for matched ads (winners + losers + average)
    matched_tasks = [ad.match.task for ad in classification.all_classified
                     if ad.classification.value != "untested"]

    st.markdown(f'<p style="color:#fafafa;">Will read scripts from <strong>{len(matched_tasks)}</strong> classified tasks (excluding untested)</p>', unsafe_allow_html=True)

    if st.button("📖 Read All Scripts (Claude extraction)", use_container_width=True):
        from analyzer.script_reader import read_all_scripts

        progress_bar = st.progress(0)
        status_text = st.empty()

        def progress_cb(i, total, name):
            progress_bar.progress((i + 1) / total)
            status_text.markdown(f'<p style="color:#aaa;font-size:12px;">Reading {i+1}/{total}: {name[:50]}...</p>', unsafe_allow_html=True)

        with st.spinner("Reading scripts and extracting components with Claude..."):
            scripts = read_all_scripts(matched_tasks, use_claude=True, progress_callback=progress_cb)

        # Store as dict: task_id → ScriptContent
        scripts_dict = {s.task_id: s for s in scripts}
        st.session_state["scripts"] = scripts_dict

        # Summary
        no_content = sum(1 for s in scripts if s.no_content_found)
        manual_review = sum(1 for s in scripts if s.manual_review_links)
        folder_links = sum(1 for s in scripts if s.folder_links)

        st.success(f"Read {len(scripts)} scripts. {no_content} with no content, {manual_review} need manual review.")
        if folder_links:
            st.info(f"{folder_links} tasks have Google Drive folder links — open manually to find brief docs.")

        progress_bar.empty()
        status_text.empty()
        st.rerun()

    # Show results
    if st.session_state.get("scripts"):
        scripts = st.session_state["scripts"]
        no_content = [s for s in scripts.values() if s.no_content_found]
        manual_review = [s for s in scripts.values() if s.manual_review_links]

        if no_content:
            with st.expander(f"⚠️ {len(no_content)} tasks with no brief/script found"):
                for s in no_content:
                    st.markdown(f'<p style="color:#fafafa;">⚠️ <strong>{s.task_name}</strong> — No brief/script found. <a href="https://app.clickup.com/t/{s.task_id}" style="color:#6C63FF;">Check task</a></p>', unsafe_allow_html=True)

        if manual_review:
            with st.expander(f"📋 {len(manual_review)} tasks need manual doc review"):
                for s in manual_review:
                    for link in s.manual_review_links:
                        st.markdown(f'<p style="color:#fafafa;">📋 <strong>{s.task_name}</strong> — Private doc: <a href="{link}" style="color:#6C63FF;">{link[:60]}...</a></p>', unsafe_allow_html=True)

        # Sample extracted scripts
        with_content = [s for s in scripts.values() if not s.no_content_found]
        if with_content:
            with st.expander(f"Preview extracted scripts ({min(5, len(with_content))} of {len(with_content)})"):
                for s in list(with_content)[:5]:
                    hooks_display = " | ".join(s.hooks[:3]) if s.hooks else "None extracted"
                    st.markdown(f"""
                    <div style="background:#1A1D24;border-radius:8px;padding:12px;margin-bottom:8px;">
                        <p style="color:#6C63FF;font-weight:bold;margin:0;">{s.task_name}</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Hooks:</strong> {hooks_display}</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Pain point:</strong> {s.pain_point or 'N/A'}</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Root cause:</strong> {s.root_cause or 'N/A'} ({s.root_cause_depth or '?'})</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Mechanism:</strong> UMP: {s.mechanism_ump or 'N/A'} | UMS: {s.mechanism_ums or 'N/A'}</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Format:</strong> {s.ad_format or 'N/A'} | <strong>Awareness:</strong> {s.awareness_level or 'N/A'} | <strong>Lead:</strong> {s.lead_type or 'N/A'}</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Avatar:</strong> {(s.avatar or 'N/A')[:200]}</p>
                        <p style="color:#fafafa;font-size:12px;margin:2px 0;"><strong>Emotional triggers:</strong> {', '.join(s.emotional_triggers[:5]) if s.emotional_triggers else 'N/A'}</p>
                    </div>
                    """, unsafe_allow_html=True)


# ── Step 5: Pattern Analysis ─────────────────────────────────────────────────

def render_step5():
    st.markdown('<h2 style="color:#fafafa;">Step 5: Pattern Analysis</h2>', unsafe_allow_html=True)

    classification = st.session_state.get("classification")
    scripts = st.session_state.get("scripts")

    if not classification or not scripts:
        st.warning("Complete Steps 3 and 4 first.")
        return

    if st.button("🔬 Run Pattern Analysis (Claude)", use_container_width=True):
        from analyzer.pattern_analyzer import analyze_patterns

        with st.spinner("Claude is analyzing patterns across all classified ads..."):
            pattern_analysis = analyze_patterns(classification, scripts)

        st.session_state["pattern_analysis"] = pattern_analysis
        st.rerun()

    if st.session_state.get("pattern_analysis"):
        pa = st.session_state["pattern_analysis"]

        # Display raw analysis (already formatted by Claude)
        st.markdown(pa.raw_analysis)

        if pa.cross_insights:
            st.markdown('<h3 style="color:#fafafa;">Key Cross-Pattern Insights</h3>', unsafe_allow_html=True)
            for insight in pa.cross_insights:
                st.markdown(f'<div style="background:#1A1D24;border-left:4px solid #6C63FF;padding:8px 12px;margin-bottom:6px;border-radius:4px;"><p style="color:#fafafa;margin:0;">{insight}</p></div>', unsafe_allow_html=True)


# ── Step 6: Hypotheses ────────────────────────────────────────────────────────

def render_step6():
    st.markdown('<h2 style="color:#fafafa;">Step 6: Learnings & Hypotheses</h2>', unsafe_allow_html=True)

    pattern_analysis = st.session_state.get("pattern_analysis")
    classification = st.session_state.get("classification")

    if not pattern_analysis or not classification:
        st.warning("Complete Step 5 first.")
        return

    if st.button("💡 Generate Hypotheses (Claude)", use_container_width=True):
        from analyzer.hypothesis_generator import generate_hypotheses

        with st.spinner("Claude is generating learnings and hypotheses..."):
            report = generate_hypotheses(pattern_analysis, classification)

        st.session_state["hypothesis_report"] = report
        st.rerun()

    if st.session_state.get("hypothesis_report"):
        hr = st.session_state["hypothesis_report"]

        # Learnings
        st.markdown('<h3 style="color:#fafafa;">Key Learnings</h3>', unsafe_allow_html=True)
        for i, learning in enumerate(hr.learnings, 1):
            conf_color = {"HIGH": "#4CAF50", "MEDIUM": "#FF9800", "LOW": "#F44336"}.get(learning.confidence.upper(), "#888")
            evidence = ", ".join(learning.supporting_evidence) if learning.supporting_evidence else "See analysis"
            st.markdown(f"""
            <div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <span style="color:#fafafa;font-weight:bold;font-size:15px;">Learning {i}</span>
                    <span style="background:{conf_color};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{learning.confidence}</span>
                </div>
                <p style="color:#fafafa;margin:4px 0;">{learning.observation}</p>
                <p style="color:#aaa;font-size:12px;margin:4px 0;"><strong>Evidence:</strong> {evidence}</p>
            </div>
            """, unsafe_allow_html=True)

        # Hypotheses
        st.markdown('<h3 style="color:#fafafa;">Testable Hypotheses</h3>', unsafe_allow_html=True)
        for i, hyp in enumerate(hr.hypotheses, 1):
            pri_color = {"HIGH": "#F44336", "MEDIUM": "#FF9800", "LOW": "#4CAF50"}.get(hyp.priority.upper(), "#888")
            hooks_html = "".join(f"<li style='color:#fafafa;font-size:13px;'>{h}</li>" for h in hyp.suggested_hook_ideas) if hyp.suggested_hook_ideas else "<li style='color:#aaa;'>See analysis</li>"
            st.markdown(f"""
            <div style="background:#1A1D24;border-radius:8px;padding:16px;margin-bottom:12px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <span style="color:#fafafa;font-weight:bold;font-size:15px;">Hypothesis {i}</span>
                    <span style="background:{pri_color};color:#fafafa;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{hyp.priority}</span>
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
            </div>
            """, unsafe_allow_html=True)


# ── Step 7: Report ────────────────────────────────────────────────────────────

def render_report_export():
    st.markdown('<h3 style="color:#fafafa;">Export Report</h3>', unsafe_allow_html=True)

    classification = st.session_state.get("classification")
    pattern_analysis = st.session_state.get("pattern_analysis")
    hypothesis_report = st.session_state.get("hypothesis_report")

    if not all([classification, pattern_analysis, hypothesis_report]):
        st.info("Complete all analysis steps to export a report.")
        return

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📄 Export HTML Report", use_container_width=True):
            from analyzer.report_generator import generate_html_report, save_report

            brand = st.session_state.get("brand_name", "Unknown")
            html = generate_html_report(brand, classification, pattern_analysis, hypothesis_report)
            path = save_report(brand, html, format="html")
            st.success(f"Report saved: {path}")
            st.download_button("⬇️ Download HTML", html, file_name=f"{brand}_report.html", mime="text/html")

    with col2:
        if st.button("📑 Export PDF Report", use_container_width=True):
            from analyzer.report_generator import generate_html_report, save_report

            brand = st.session_state.get("brand_name", "Unknown")
            html = generate_html_report(brand, classification, pattern_analysis, hypothesis_report)
            path = save_report(brand, html, format="pdf")
            if path.suffix == ".pdf":
                st.success(f"PDF saved: {path}")
                st.download_button("⬇️ Download PDF", path.read_bytes(), file_name=f"{brand}_report.pdf", mime="application/pdf")
            else:
                st.warning("PDF export requires `weasyprint`. Saved as HTML instead.")
                st.download_button("⬇️ Download HTML", html, file_name=f"{brand}_report.html", mime="text/html")


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


# ── Main Dashboard ────────────────────────────────────────────────────────────

def render_dashboard():
    st.markdown('<h1 style="color:#fafafa;">🔄 Creative Feedback Loop Analyzer</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#aaa;">Pull creative briefs from ClickUp → Match with Meta Ads performance → Find winning patterns → Generate hypotheses</p>', unsafe_allow_html=True)
    st.markdown("---")

    render_step1()
    st.markdown("---")
    render_step2()
    st.markdown("---")
    render_step3()
    st.markdown("---")
    render_step4()
    st.markdown("---")
    render_step5()
    st.markdown("---")
    render_step6()
    st.markdown("---")
    render_report_export()


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
