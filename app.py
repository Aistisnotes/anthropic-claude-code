"""Meta Ads Analyzer — Local Web UI

A Streamlit web app wrapping the meta-ads CLI.

Pages:
  🏠 Home     — Run a new analysis (keyword + optional brand URL)
  📊 Results  — PDF report inline + download, loophole summary
  📁 History  — All previous runs with quick access to outputs
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st

# ── Project paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
META_ADS_BIN = PROJECT_ROOT / ".venv" / "bin" / "meta-ads"
REPORTS_DIR = PROJECT_ROOT / "output" / "reports"
PDF_OUTPUT_DIR = Path.home() / "Desktop" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Meta Ads Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main .block-container { padding-top: 1.5rem; max-width: 1100px; }
  div[data-testid="stSidebarNav"] { display: none; }

  /* Pink accent theme */
  .stButton > button {
    background: #e91e8c !important;
    color: white !important;
    border: none !important;
    font-weight: 700 !important;
    border-radius: 8px !important;
  }
  .stButton > button:hover { background: #c2185b !important; }

  /* Cards */
  .run-card {
    background: #f8f8f8;
    border: 1px solid #e0e0e0;
    border-left: 4px solid #e91e8c;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 10px;
    cursor: pointer;
  }
  .run-card:hover { background: #fce4ec; border-color: #e91e8c; }
  .run-card-title { font-weight: 700; font-size: 15px; color: #111; }
  .run-card-meta { font-size: 12px; color: #666; margin-top: 3px; }
  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    margin-right: 4px;
  }
  .badge-pink { background: #fce4ec; color: #e91e8c; }
  .badge-green { background: #e8f5e9; color: #2e7d32; }
  .badge-yellow { background: #fff8e1; color: #b7840a; }
  .badge-gray { background: #f0f0f0; color: #555; }

  /* Section headers */
  .section-header {
    font-size: 22px;
    font-weight: 800;
    color: #e91e8c;
    border-bottom: 3px solid #e91e8c;
    padding-bottom: 6px;
    margin-bottom: 16px;
  }
  .loophole-card {
    border: 1px solid #e0e0e0;
    border-left: 5px solid #e91e8c;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 16px;
    background: white;
  }
  .score-badge {
    display: inline-block;
    background: #e91e8c;
    color: white;
    border-radius: 20px;
    padding: 4px 12px;
    font-size: 14px;
    font-weight: 800;
    float: right;
  }
</style>
""", unsafe_allow_html=True)


# ── Session state init ─────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "page": "home",
        "running": False,
        "run_log": [],
        "last_compare_dir": None,
        "last_pdf_path": None,
        "process": None,
        "_spawned": False,  # synchronous guard — prevents duplicate thread launches
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Sidebar Navigation ─────────────────────────────────────────────────────────
def sidebar():
    with st.sidebar:
        st.markdown("## 📊 Meta Ads Analyzer")
        st.markdown("---")

        pages = {
            "🏠 New Run": "home",
            "📊 Results": "results",
            "📁 History": "history",
        }
        for label, key in pages.items():
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                st.session_state.page = key
                st.rerun()

        st.markdown("---")
        # Quick stats
        compare_dirs = _get_compare_dirs()
        market_dirs = _get_market_dirs()
        brand_reports = list(REPORTS_DIR.glob("*.md"))
        st.metric("Compare Runs", len(compare_dirs))
        st.metric("Market Runs", len(market_dirs))
        st.metric("Brand Reports", len(brand_reports))


# ── Data helpers ───────────────────────────────────────────────────────────────
def _get_compare_dirs() -> list[Path]:
    dirs = sorted(REPORTS_DIR.glob("compare_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [d for d in dirs if d.is_dir()]


def _get_market_dirs() -> list[Path]:
    dirs = sorted(REPORTS_DIR.glob("market_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [d for d in dirs if d.is_dir()]


def _parse_compare_dir(d: Path) -> dict:
    """Extract metadata from a compare directory."""
    name = d.name  # compare_aged_garlic_supplement_20260217_222505
    parts = name.split("_")
    # Last two parts are date and time
    date_str = ""
    keyword = name
    if len(parts) >= 3:
        try:
            date_part = parts[-2]  # YYYYMMDD
            time_part = parts[-1]  # HHMMSS
            dt = datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S")
            date_str = dt.strftime("%b %d, %Y %H:%M")
            keyword = " ".join(parts[1:-2]).replace("_", " ")
        except ValueError:
            pass

    loophole_path = d / "strategic_loophole_doc.json"
    market_map_path = d / "strategic_market_map.json"

    meta = {}
    loopholes = []
    if loophole_path.exists():
        try:
            data = json.loads(loophole_path.read_text())
            meta = data.get("meta", {})
            loopholes = data.get("loopholes", [])
        except Exception:
            pass

    # Check for PDF
    pdf_path = _find_pdf_for_compare(d)

    return {
        "dir": d,
        "keyword": meta.get("keyword", keyword),
        "focus_brand": meta.get("focus_brand"),
        "brands_compared": meta.get("brands_compared", 0),
        "date_str": date_str,
        "loopholes": loopholes,
        "loophole_path": loophole_path if loophole_path.exists() else None,
        "market_map_path": market_map_path if market_map_path.exists() else None,
        "pdf_path": pdf_path,
        "has_loopholes": loophole_path.exists(),
    }


def _find_pdf_for_compare(compare_dir: Path) -> Optional[Path]:
    """Find a PDF in ~/Desktop/reports that matches this compare dir."""
    if not PDF_OUTPUT_DIR.exists():
        return None
    name = compare_dir.name  # compare_aged_garlic_supplement_20260217_222505
    parts = name.split("_")
    if len(parts) >= 3:
        keyword_slug = "_".join(parts[1:-2])[:30]
        for pdf in PDF_OUTPUT_DIR.glob("*.pdf"):
            if keyword_slug[:15] in pdf.stem:
                return pdf
    return None


# ── Run pipeline ───────────────────────────────────────────────────────────────
def _run_pipeline(keyword: str, brand_url: Optional[str], mode: str,
                  top_brands: int, ads_per_brand: int, run_compare: bool):
    """Execute the meta-ads pipeline in a background thread, streaming logs."""
    # ── Duplicate-launch guard ──────────────────────────────────────────────
    # Set running=True synchronously (in main thread) so the button is
    # immediately disabled on the next rerun — before the thread even starts.
    if st.session_state.running or st.session_state._spawned:
        return
    st.session_state.running = True
    st.session_state._spawned = True
    # ───────────────────────────────────────────────────────────────────────

    log = st.session_state.run_log
    log.clear()

    def _log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        log.append(f"[{ts}] {msg}")

    def _run():
        st.session_state.last_compare_dir = None
        st.session_state.last_pdf_path = None

        try:
            _log(f"Starting {mode} run for: {keyword}")

            if mode == "brand":
                cmd = [str(META_ADS_BIN), "run", brand_url or keyword,
                       "--brand", keyword, "--max-ads", "100"]
            elif mode == "market":
                cmd = [str(META_ADS_BIN), "market", keyword,
                       "--top-brands", str(top_brands),
                       "--ads-per-brand", str(ads_per_brand)]
            elif mode == "compare":
                cmd = [str(META_ADS_BIN), "compare", keyword,
                       "--enhance"]
                if brand_url:
                    cmd += ["--brand", brand_url]
            else:
                _log(f"Unknown mode: {mode}")
                return

            _log(f"Command: {' '.join(cmd)}")
            _log("─" * 50)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            st.session_state.process = proc

            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    # Strip ANSI escape codes
                    import re
                    clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                    _log(clean)

            proc.wait()
            _log("─" * 50)

            if proc.returncode == 0:
                _log(f"✓ {mode.capitalize()} run complete")

                # If market + compare, run compare automatically
                if mode == "market" and run_compare:
                    _log("")
                    _log("Running compare with --enhance...")
                    cmp_cmd = [str(META_ADS_BIN), "compare", keyword, "--enhance"]
                    if brand_url:
                        cmp_cmd += ["--brand", brand_url]
                    cmp_proc = subprocess.Popen(
                        cmp_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        cwd=str(PROJECT_ROOT),
                    )
                    for line in cmp_proc.stdout:
                        line = line.rstrip()
                        if line:
                            import re
                            clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                            _log(clean)
                    cmp_proc.wait()

                # Find the latest compare dir
                compare_dirs = _get_compare_dirs()
                if compare_dirs:
                    latest = compare_dirs[0]
                    st.session_state.last_compare_dir = latest
                    _log(f"Output: {latest}")

                    # Generate PDF
                    loophole_path = latest / "strategic_loophole_doc.json"
                    if loophole_path.exists():
                        _log("Generating PDF report...")
                        try:
                            from meta_ads_analyzer.reporter.pdf_generator import generate_pdf_sync
                            pdf_path = generate_pdf_sync(
                                loophole_doc_path=loophole_path,
                                market_map_path=latest / "strategic_market_map.json",
                                output_dir=PDF_OUTPUT_DIR,
                            )
                            st.session_state.last_pdf_path = pdf_path
                            _log(f"✓ PDF saved: {pdf_path}")
                        except Exception as e:
                            _log(f"⚠ PDF generation failed: {e}")

            else:
                _log(f"✗ Process exited with code {proc.returncode}")

        except Exception as e:
            _log(f"✗ Error: {e}")
        finally:
            st.session_state.running = False
            st.session_state._spawned = False
            st.session_state.process = None

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: HOME
# ══════════════════════════════════════════════════════════════════════════════
def page_home():
    st.markdown('<div class="section-header">🏠 New Analysis Run</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("#### Market Keyword")
        keyword = st.text_input(
            "Keyword",
            placeholder="aged garlic supplement",
            label_visibility="collapsed",
            key="input_keyword",
        )

        st.markdown("#### Brand URL (optional)")
        brand_url = st.text_input(
            "Brand URL",
            placeholder="TryElare or tryelarE.com",
            label_visibility="collapsed",
            key="input_brand",
        )

        st.markdown("#### Run Mode")
        mode = st.radio(
            "Mode",
            ["Market Research + Compare", "Compare Only", "Brand Analysis"],
            label_visibility="collapsed",
            horizontal=True,
            key="input_mode",
        )

    with col2:
        st.markdown("#### Options")
        top_brands = st.slider("Top brands", 3, 15, 8)
        ads_per_brand = st.slider("Ads per brand", 10, 50, 30)
        run_compare = True
        if mode == "Market Research + Compare":
            run_compare = st.checkbox("Auto-run compare after market", value=True)

    st.markdown("---")

    # Run button + stop button
    run_col, stop_col, _ = st.columns([2, 1, 4])
    with run_col:
        if st.button("▶ Run Analysis", disabled=st.session_state.running, use_container_width=True):
            if not keyword.strip():
                st.error("Please enter a keyword.")
            else:
                _mode_map = {
                    "Market Research + Compare": "market",
                    "Compare Only": "compare",
                    "Brand Analysis": "brand",
                }
                _run_pipeline(
                    keyword=keyword.strip(),
                    brand_url=brand_url.strip() or None,
                    mode=_mode_map[mode],
                    top_brands=top_brands,
                    ads_per_brand=ads_per_brand,
                    run_compare=run_compare,
                )
                st.rerun()

    with stop_col:
        if st.button("⏹ Stop", disabled=not st.session_state.running, use_container_width=True):
            proc = st.session_state.get("process")
            if proc:
                proc.terminate()
                st.session_state.running = False
                st.session_state.run_log.append("[STOPPED]")
                st.rerun()

    # Progress log
    if st.session_state.running or st.session_state.run_log:
        st.markdown("#### Pipeline Output")
        log_placeholder = st.empty()
        log_text = "\n".join(st.session_state.run_log[-200:]) or "(waiting for output...)"
        log_placeholder.code(log_text, language=None)

    # Auto-refresh while running — always checked, not nested inside the log block
    if st.session_state.running:
        time.sleep(1.5)
        st.rerun()

    # Show "View Results" button when done
    if not st.session_state.running and st.session_state.last_compare_dir:
        st.success("Run complete!")
        if st.button("📊 View Results →", use_container_width=False):
            st.session_state.page = "results"
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: RESULTS
# ══════════════════════════════════════════════════════════════════════════════
def _render_loopholes(loopholes: list):
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
    for i, lp in enumerate(loopholes):
        medal = medals[i] if i < len(medals) else "●"
        score = lp.get("priority_score", 0)
        competition = lp.get("meta_competition", "?")
        tam = lp.get("tam_size", "?")
        risk = lp.get("risk_level", "?")
        timeline = lp.get("timeline", "")

        # Color badges
        comp_color = {"none": "green", "low": "yellow", "medium": "pink"}.get(competition, "gray")
        risk_color = {"low": "green", "medium": "yellow", "high": "pink"}.get(risk, "gray")

        st.markdown(f"""
        <div class="loophole-card">
          <div>
            <span class="score-badge">{score}/100</span>
            <strong style="font-size:16px;">{medal} {lp.get('title', '')}</strong><br>
            <span style="font-size:11px;color:#888;">{lp.get('loophole_id','')} &nbsp;·&nbsp;
              <span class="badge badge-gray">{tam.upper()} TAM</span>
              <span class="badge badge-{comp_color}">{competition.upper()} COMPETITION</span>
              <span class="badge badge-{risk_color}">{risk.upper()} RISK</span>
              {f'<span class="badge badge-pink">{timeline}</span>' if timeline else ''}
            </span>
          </div>
          <div style="margin-top:10px;font-size:13.5px;color:#333;line-height:1.65;">
            <strong style="font-size:10px;text-transform:uppercase;color:#888;">THE GAP</strong><br>
            {lp.get('the_gap', '')}
          </div>
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"↳ Full strategy: {lp.get('title', '')[:60]}"):
            cols = st.columns(2)
            with cols[0]:
                st.markdown(f"**Root Cause:** {lp.get('root_cause', '—')}")
                st.markdown(f"**Mechanism:** {lp.get('mechanism', '—')}")
                st.markdown(f"**Target Avatar:** {lp.get('target_avatar', '—')}")
            with cols[1]:
                st.markdown(f"**Pain Point:** {lp.get('pain_point', '—')}")
                st.markdown(f"**Mass Desire:** {lp.get('mass_desire', '—')}")

            if lp.get("hook_examples"):
                st.markdown("**Hook Examples:**")
                for hook in lp["hook_examples"]:
                    st.markdown(f"> *\"{hook}\"*")

            if lp.get("proof_strategy"):
                st.markdown(f"**Proof Strategy:** {lp['proof_strategy']}")
            if lp.get("objection_handling"):
                st.markdown(f"**Objections:** {lp['objection_handling']}")
            if lp.get("defensibility"):
                st.markdown(f"*{lp['defensibility']}*")


def page_results():
    st.markdown('<div class="section-header">📊 Results</div>', unsafe_allow_html=True)

    # Source selector
    compare_dirs = _get_compare_dirs()
    if not compare_dirs:
        st.info("No compare runs found yet. Run an analysis from the Home page.")
        return

    # Default to last run or session state
    current_dir = st.session_state.get("last_compare_dir")
    dir_options = {_parse_compare_dir(d)["keyword"] + " · " + d.name[-15:]: d for d in compare_dirs[:20]}
    default_key = None
    if current_dir:
        for k, v in dir_options.items():
            if v == current_dir:
                default_key = k
                break

    selected_label = st.selectbox(
        "Select run",
        options=list(dir_options.keys()),
        index=0 if not default_key else list(dir_options.keys()).index(default_key),
    )
    selected_dir = dir_options[selected_label]
    info = _parse_compare_dir(selected_dir)

    # Header meta
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Keyword", info["keyword"])
    col2.metric("Brands", info["brands_compared"])
    col3.metric("Loopholes", len(info["loopholes"]))
    col4.metric("Focus Brand", info["focus_brand"] or "—")

    st.markdown("---")

    # PDF Section
    st.markdown("### 📄 PDF Report")
    pdf_path = info.get("pdf_path")
    if pdf_path and pdf_path.exists():
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        dl_col, info_col = st.columns([2, 3])
        with dl_col:
            st.download_button(
                label=f"⬇ Download PDF ({pdf_path.stat().st_size // 1024}KB)",
                data=pdf_bytes,
                file_name=pdf_path.name,
                mime="application/pdf",
            )
        with info_col:
            st.caption(f"📁 {pdf_path}")

        # Inline PDF viewer
        import base64
        b64 = base64.b64encode(pdf_bytes).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="900px" style="border:1px solid #e0e0e0;border-radius:8px;"></iframe>',
            unsafe_allow_html=True,
        )
    else:
        if info["loophole_path"]:
            if st.button("🔄 Generate PDF for this run"):
                with st.spinner("Generating PDF..."):
                    try:
                        from meta_ads_analyzer.reporter.pdf_generator import generate_pdf_sync
                        pdf_path = generate_pdf_sync(
                            loophole_doc_path=info["loophole_path"],
                            market_map_path=info["market_map_path"],
                            output_dir=PDF_OUTPUT_DIR,
                        )
                        st.success(f"PDF saved: {pdf_path}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"PDF generation failed: {e}")
        else:
            st.info("No loophole document found for this run.")

    st.markdown("---")

    # Loopholes section
    if info["loopholes"]:
        st.markdown("### 🎯 Validated Loopholes")
        _render_loopholes(info["loopholes"])

    # Competitive landscape
    if info["loophole_path"]:
        data = json.loads(info["loophole_path"].read_text())
        comp = data.get("competitive_landscape", [])
        if comp:
            st.markdown("### 🏆 Competitive Landscape")
            import pandas as pd
            df = pd.DataFrame(comp)
            st.dataframe(df, use_container_width=True, hide_index=True)

        wntd = data.get("what_not_to_do", [])
        if wntd:
            st.markdown("### ⛔ What Not To Do")
            for item in wntd:
                clean = item.replace("DON'T ", "").replace("DON\u2019T ", "")
                st.markdown(f"❌ {clean}")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE: HISTORY
# ══════════════════════════════════════════════════════════════════════════════
def page_history():
    st.markdown('<div class="section-header">📁 Run History</div>', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["Compare Runs", "Market Runs", "Brand Reports"])

    with tab1:
        compare_dirs = _get_compare_dirs()
        if not compare_dirs:
            st.info("No compare runs yet.")
        else:
            st.caption(f"{len(compare_dirs)} compare runs found")
            for d in compare_dirs[:50]:
                info = _parse_compare_dir(d)
                has_pdf = info["pdf_path"] and info["pdf_path"].exists()
                has_loopholes = info["has_loopholes"]

                col1, col2, col3 = st.columns([5, 1, 1])
                with col1:
                    st.markdown(f"""
                    <div class="run-card">
                      <div class="run-card-title">
                        {info['keyword']}
                        {f'<span class="badge badge-pink">⚑ {info["focus_brand"]}</span>' if info["focus_brand"] else ''}
                      </div>
                      <div class="run-card-meta">
                        {info['date_str']} &nbsp;·&nbsp;
                        {info['brands_compared']} brands &nbsp;·&nbsp;
                        {len(info['loopholes'])} loopholes
                        {'&nbsp;·&nbsp; <span class="badge badge-green">PDF ✓</span>' if has_pdf else ''}
                      </div>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    if has_loopholes:
                        if st.button("View", key=f"view_{d.name}"):
                            st.session_state.last_compare_dir = d
                            st.session_state.page = "results"
                            st.rerun()
                with col3:
                    if has_pdf and info["pdf_path"]:
                        with open(info["pdf_path"], "rb") as f:
                            st.download_button(
                                "PDF",
                                data=f.read(),
                                file_name=info["pdf_path"].name,
                                mime="application/pdf",
                                key=f"dl_{d.name}",
                            )
                    elif has_loopholes:
                        if st.button("→PDF", key=f"pdf_{d.name}"):
                            with st.spinner("Generating..."):
                                try:
                                    from meta_ads_analyzer.reporter.pdf_generator import generate_pdf_sync
                                    pdf_path = generate_pdf_sync(
                                        loophole_doc_path=info["loophole_path"],
                                        market_map_path=info["market_map_path"],
                                        output_dir=PDF_OUTPUT_DIR,
                                    )
                                    st.success(f"Saved: {pdf_path.name}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(str(e))

    with tab2:
        market_dirs = _get_market_dirs()
        if not market_dirs:
            st.info("No market runs yet.")
        else:
            st.caption(f"{len(market_dirs)} market runs found")
            for d in market_dirs[:50]:
                name = d.name
                brand_reports = list(d.glob("brand_report_*.json"))
                # Parse date from name
                parts = name.split("_")
                date_str = ""
                keyword = name
                if len(parts) >= 3:
                    try:
                        dt = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S")
                        date_str = dt.strftime("%b %d %H:%M")
                        keyword = " ".join(parts[1:-2]).replace("_", " ")
                    except ValueError:
                        pass

                st.markdown(f"""
                <div class="run-card">
                  <div class="run-card-title">{keyword}</div>
                  <div class="run-card-meta">{date_str} &nbsp;·&nbsp; {len(brand_reports)} brand reports</div>
                </div>
                """, unsafe_allow_html=True)

    with tab3:
        md_reports = sorted(REPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not md_reports:
            st.info("No brand reports yet.")
        else:
            st.caption(f"{len(md_reports)} brand reports")
            search = st.text_input("Filter by brand name", placeholder="Elare, Sculptique...")
            for rpt in md_reports[:100]:
                if search and search.lower() not in rpt.stem.lower():
                    continue
                # Parse filename: YYYYMMDD_HHMMSS_keyword_Brand_hash.md
                stem = rpt.stem
                parts = stem.split("_")
                date_str = ""
                label = stem
                if len(parts) >= 3:
                    try:
                        dt = datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M%S")
                        date_str = dt.strftime("%b %d %H:%M")
                        label = " ".join(parts[2:-1]).replace("_", " ")
                    except ValueError:
                        pass
                col1, col2 = st.columns([6, 1])
                with col1:
                    st.markdown(f"""
                    <div class="run-card" style="border-left-color:#666;">
                      <div class="run-card-title">{label}</div>
                      <div class="run-card-meta">{date_str}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    with open(rpt) as f:
                        st.download_button(
                            "MD",
                            data=f.read(),
                            file_name=rpt.name,
                            key=f"dl_rpt_{rpt.name}",
                        )


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTER
# ══════════════════════════════════════════════════════════════════════════════
def main():
    sidebar()
    page = st.session_state.page
    if page == "home":
        page_home()
    elif page == "results":
        page_results()
    elif page == "history":
        page_history()


if __name__ == "__main__":
    main()
