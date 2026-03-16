"""Meta Ads Analyzer — Local Web UI

A Streamlit web app wrapping the meta-ads CLI.

Pages:
  🏠 Home     — Run a new analysis (keyword + optional brand URL)
  📊 Results  — PDF report inline + download, loophole summary
  📁 History  — All previous runs with quick access to outputs
"""

from __future__ import annotations

import json
import os
import shutil
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

# Resolve meta-ads binary: venv first, then PATH (for Docker where it's installed globally)
_venv_bin = PROJECT_ROOT / ".venv" / "bin" / "meta-ads"
_system_bin = shutil.which("meta-ads")
META_ADS_BIN = _venv_bin if _venv_bin.exists() else Path(_system_bin or "/usr/local/bin/meta-ads")

REPORTS_DIR = PROJECT_ROOT / "output" / "reports"
# PDF output dir — env var for Docker (/app/output/reports), Desktop fallback locally
PDF_OUTPUT_DIR = Path(os.environ.get("PDF_OUTPUT_DIR", str(Path.home() / "Desktop" / "reports")))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# Static dir for serving PDFs over HTTP (required for ngrok / HTTPS)
STATIC_DIR = PROJECT_ROOT / "static"
STATIC_DIR.mkdir(exist_ok=True)


def _pdf_iframe(pdf_path: Path) -> None:
    """Render a PDF inline using PDF.js (canvas-based, works in sandboxed iframes on HTTPS/ngrok)."""
    import shutil as _shutil
    import streamlit.components.v1 as components

    dest = STATIC_DIR / pdf_path.name
    if not dest.exists() or dest.stat().st_mtime < pdf_path.stat().st_mtime:
        _shutil.copy2(pdf_path, dest)

    filename = pdf_path.name
    components.html(
        f"""<!DOCTYPE html><html><head>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #525659; font-family: sans-serif; overflow-y: auto; }}
  #loading {{ color: #ccc; padding: 40px; text-align: center; font-size: 14px; }}
  #error   {{ color: #f88; padding: 20px; font-size: 13px; }}
  #pages   {{ display: flex; flex-direction: column; align-items: center; padding: 16px 0; gap: 12px; }}
  canvas   {{ background: white; box-shadow: 0 2px 8px rgba(0,0,0,.5); max-width: 100%; }}
</style>
</head><body>
<div id="loading">Loading PDF…</div>
<div id="error"  style="display:none"></div>
<div id="pages"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script>
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  var base = (window.parent && window.parent.location.origin !== 'null')
             ? window.parent.location.origin
             : window.location.origin;
  var pdfUrl = base + '/app/static/{filename}';

  pdfjsLib.getDocument(pdfUrl).promise.then(function(pdf) {{
    document.getElementById('loading').style.display = 'none';
    var container = document.getElementById('pages');
    var scale = Math.min(1.6, (window.innerWidth - 40) / 612);

    var chain = Promise.resolve();
    for (var i = 1; i <= pdf.numPages; i++) {{
      (function(pageNum) {{
        chain = chain.then(function() {{
          return pdf.getPage(pageNum).then(function(page) {{
            var vp = page.getViewport({{ scale: scale }});
            var canvas = document.createElement('canvas');
            canvas.width  = vp.width;
            canvas.height = vp.height;
            container.appendChild(canvas);
            return page.render({{ canvasContext: canvas.getContext('2d'), viewport: vp }}).promise;
          }});
        }});
      }})(i);
    }}
  }}).catch(function(err) {{
    document.getElementById('loading').style.display = 'none';
    var el = document.getElementById('error');
    el.style.display = 'block';
    el.textContent = 'Could not load PDF: ' + err.message;
  }});
</script>
</body></html>""",
        height=1100,
        scrolling=True,
    )

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
    color: #111;
  }
  .loophole-card strong, .loophole-card span, .loophole-card div {
    color: inherit;
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


# ── Auth ───────────────────────────────────────────────────────────────────────
def _check_auth() -> bool:
    """Return True if authenticated. Show login form and return False if not.

    Auth is skipped entirely when TOOL_PASSWORD is not set (local dev mode).
    """
    if st.session_state.get("authenticated"):
        return True

    expected_user = os.environ.get("TOOL_USERNAME", "admin")
    expected_pass = os.environ.get("TOOL_PASSWORD", "")

    # No password configured — bypass auth (local dev)
    if not expected_pass:
        st.session_state["authenticated"] = True
        return True

    # Centre the login form
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("## 🔐 Meta Ads Analyzer")
        st.markdown("---")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
            if submitted:
                if username == expected_user and password == expected_pass:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
    return False


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
            "🔄 Creative Feedback": "creative_feedback",
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


def _find_pdf_for_market(market_dir: Path) -> Optional[Path]:
    """Find a PDF (blue ocean or strategic) for a market directory."""
    if not PDF_OUTPUT_DIR.exists():
        return None
    name = market_dir.name
    parts = name.split("_")
    if len(parts) < 2:
        return None
    keyword_slug = "_".join(parts[1:-2])[:20].lower()
    slug10 = keyword_slug[:10]
    # Prefer blue ocean PDF; fall back to any matching strategic analysis PDF
    all_pdfs = sorted(PDF_OUTPUT_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    blue_ocean_match = next(
        (p for p in all_pdfs if "blue_ocean" in p.stem and slug10 in p.stem.lower()), None
    )
    if blue_ocean_match:
        return blue_ocean_match
    # Fall back to strategic analysis PDF matching same keyword
    return next(
        (p for p in all_pdfs if slug10 in p.stem.lower() and "blue_ocean" not in p.stem), None
    )


def _load_blue_ocean_result(market_dir: Path) -> Optional[dict]:
    """Load blue_ocean_report.json from a market directory."""
    bo_path = market_dir / "blue_ocean_report.json"
    if bo_path.exists():
        try:
            return json.loads(bo_path.read_text())
        except Exception:
            return None
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
            <strong style="font-size:16px;color:#111;">{medal} {lp.get('title', '')}</strong><br>
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


def _render_blue_ocean_result(bo: dict):
    """Render blue ocean report inline in the Results page."""
    st.markdown("""
    <div style="background:#e1f5fe;border-left:5px solid #0277bd;border-radius:8px;
                padding:14px 18px;margin-bottom:16px;">
      <strong style="color:#0277bd;font-size:16px;">🌊 Blue Ocean Market</strong><br>
      <span style="font-size:13px;color:#333;">No brand has 50+ qualifying ads in this market.
      This is a first-mover opportunity.</span>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Brands Scanned", bo.get("brands_scanned", 0))
    col2.metric("Max Qualifying Ads", bo.get("max_qualifying_ads", 0))
    col3.metric("Focus Brand", bo.get("focus_brand") or "—")

    if bo.get("blue_ocean_summary"):
        st.markdown("### Market Opportunity")
        st.markdown(bo["blue_ocean_summary"])

    # Brand counts
    if bo.get("brand_ad_counts"):
        st.markdown("### Brands Found")
        import pandas as pd
        df = pd.DataFrame(bo["brand_ad_counts"])
        df.columns = ["Brand", "Qualifying Ads"]
        st.dataframe(df, use_container_width=True, hide_index=True)

    # Execution recommendations
    if bo.get("execution_recommendations"):
        st.markdown("### Execution Recommendations")
        for i, rec in enumerate(bo["execution_recommendations"], 1):
            st.markdown(f"**{i}.** {rec}")

    # Ad concepts
    if bo.get("first_5_ad_concepts"):
        st.markdown("### First 5 Ad Concepts")
        for i, concept in enumerate(bo["first_5_ad_concepts"], 1):
            with st.expander(f"Concept {i}: {concept.get('title', '')}"):
                st.markdown(f"**Hook:** *\"{concept.get('hook', '')}\"*")
                cols = st.columns(2)
                with cols[0]:
                    st.markdown(f"**Angle:** {concept.get('angle', '')}")
                    st.markdown(f"**Root Cause:** {concept.get('root_cause', '')}")
                with cols[1]:
                    st.markdown(f"**Mechanism:** {concept.get('mechanism', '')}")
                st.success(concept.get('why_it_works', ''))

    # Testing roadmap
    if bo.get("testing_roadmap"):
        st.markdown("### Testing Roadmap")
        for week in bo["testing_roadmap"]:
            st.markdown(f"**{week.get('week', '')}** — {week.get('focus', '')}")
            for action in week.get("actions", []):
                st.markdown(f"  - {action}")

    # Focus brand deep dive
    if bo.get("focus_brand") and bo.get("focus_brand_ads_analyzed", 0) > 0:
        st.markdown(f"### Focus Brand Deep Dive — {bo['focus_brand']}")
        cols = st.columns(2)
        with cols[0]:
            if bo.get("focus_brand_strengths"):
                st.markdown("**Strengths**")
                for s in bo["focus_brand_strengths"]:
                    st.markdown(f"✓ {s}")
        with cols[1]:
            if bo.get("focus_brand_gaps"):
                st.markdown("**Messaging Gaps**")
                for g in bo["focus_brand_gaps"]:
                    st.markdown(f"✗ {g}")

    # Adjacent keywords
    if bo.get("adjacent_keywords"):
        st.markdown("### Adjacent Markets")
        import pandas as pd
        rows = []
        for kw in bo["adjacent_keywords"]:
            rows.append({
                "Keyword": kw.get("keyword", ""),
                "Total Brands": kw.get("total_brands", 0),
                "Brands 50+ Ads": kw.get("brands_with_50_plus", 0),
                "Max Ads": kw.get("max_ads", 0),
                "Competition": "Yes" if kw.get("has_competition") else "Blue Ocean Too",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def page_results():
    st.markdown('<div class="section-header">📊 Results</div>', unsafe_allow_html=True)

    compare_dirs = _get_compare_dirs()
    market_dirs = _get_market_dirs()

    # Blue ocean market dirs: market runs that have a blue_ocean_report.json
    bo_market_dirs = [d for d in market_dirs if (d / "blue_ocean_report.json").exists()]
    # Thin/normal competition market dirs: have brand reports but no blue ocean file
    comp_market_dirs = [
        d for d in market_dirs
        if not (d / "blue_ocean_report.json").exists()
        and any(d.glob("brand_report_*.json"))
    ]

    if not compare_dirs and not bo_market_dirs and not comp_market_dirs:
        st.info("No results found yet. Run an analysis from the Home page.")
        return

    # Build unified dropdown: compare runs first, then blue ocean market runs
    dir_options: dict[str, tuple[str, Path]] = {}
    for d in compare_dirs[:20]:
        info = _parse_compare_dir(d)
        label = info["keyword"] + " · " + d.name[-15:]
        dir_options[label] = ("compare", d)
    for d in bo_market_dirs[:20]:
        parts = d.name.split("_")
        keyword = " ".join(parts[1:-2]).replace("_", " ")
        date_str = ""
        try:
            from datetime import datetime
            dt = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S")
            date_str = dt.strftime("%b %d %H:%M")
        except Exception:
            date_str = d.name[-15:]
        label = f"🌊 {keyword} · {date_str}"
        dir_options[label] = ("blue_ocean", d)
    for d in comp_market_dirs[:20]:
        parts = d.name.split("_")
        keyword = " ".join(parts[1:-2]).replace("_", " ")
        date_str = ""
        try:
            from datetime import datetime
            dt = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S")
            date_str = dt.strftime("%b %d %H:%M")
        except Exception:
            date_str = d.name[-15:]
        label = f"📊 {keyword} · {date_str}"
        dir_options[label] = ("market_comp", d)

    # Default to last run from session state
    current_dir = st.session_state.get("last_compare_dir")
    default_idx = 0
    for i, (label, (kind, d)) in enumerate(dir_options.items()):
        if d == current_dir:
            default_idx = i
            break

    selected_label = st.selectbox("Select run", options=list(dir_options.keys()), index=default_idx)
    run_kind, selected_dir = dir_options[selected_label]

    st.markdown("---")

    # ── Blue ocean run ────────────────────────────────────────────────────────
    if run_kind == "blue_ocean":
        blue_ocean_data = _load_blue_ocean_result(selected_dir)
        if blue_ocean_data:
            _render_blue_ocean_result(blue_ocean_data)
            bo_pdf = _find_pdf_for_market(selected_dir)
            if bo_pdf and bo_pdf.exists():
                st.markdown("### 📄 Blue Ocean PDF Report")
                with open(bo_pdf, "rb") as f:
                    pdf_bytes = f.read()
                dl_col, nt_col = st.columns([2, 2])
                with dl_col:
                    st.download_button(
                        f"⬇ Download PDF ({bo_pdf.stat().st_size // 1024}KB)",
                        data=pdf_bytes, file_name=bo_pdf.name, mime="application/pdf",
                    )
                with nt_col:
                    st.markdown(f'<a href="app/static/{bo_pdf.name}" target="_blank" style="text-decoration:none;"><button style="padding:6px 14px;background:#444;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;">↗ Open in new tab</button></a>', unsafe_allow_html=True)
                _pdf_iframe(bo_pdf)
        else:
            st.warning("Blue ocean report data not found.")
        return

    # ── Competitive market run (thin competition, no blue ocean file) ─────────
    if run_kind == "market_comp":
        parts = selected_dir.name.split("_")
        keyword = " ".join(parts[1:-2]).replace("_", " ")
        brand_files = sorted(selected_dir.glob("brand_report_*.json"))
        st.markdown(f"### 📊 Market Run — *{keyword}*")
        col1, col2 = st.columns(2)
        col1.metric("Brands Analyzed", len(brand_files))
        col2.metric("Run Dir", selected_dir.name[-20:])

        # PDF section — look for a matching PDF (strategic analysis or blue ocean)
        st.markdown("### 📄 PDF Report")
        pdf_path = _find_pdf_for_market(selected_dir)
        if pdf_path and pdf_path.exists():
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            dl_col, nt_col, info_col = st.columns([2, 2, 3])
            with dl_col:
                st.download_button(
                    label=f"⬇ Download PDF ({pdf_path.stat().st_size // 1024}KB)",
                    data=pdf_bytes,
                    file_name=pdf_path.name,
                    mime="application/pdf",
                )
            with nt_col:
                st.markdown(f'<a href="app/static/{pdf_path.name}" target="_blank" style="text-decoration:none;"><button style="padding:6px 14px;background:#444;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;">↗ Open in new tab</button></a>', unsafe_allow_html=True)
            with info_col:
                st.caption(f"📁 {pdf_path.name}")
            _pdf_iframe(pdf_path)
        else:
            st.info("PDF not found. Market PDF is auto-generated after each run.")
            if st.button("🔄 Refresh"):
                st.rerun()

        # Brand report summaries
        if brand_files:
            st.markdown("### Brand Reports")
            for bf in brand_files:
                try:
                    data = json.loads(bf.read_text())
                    brand = data.get("brand_name") or data.get("page_name") or bf.stem
                    with st.expander(f"📋 {brand}"):
                        if data.get("top_hooks"):
                            st.markdown("**Top Hooks**")
                            for h in data["top_hooks"][:3]:
                                st.markdown(f"> *\"{h}\"*")
                        if data.get("primary_angle"):
                            st.markdown(f"**Primary Angle:** {data['primary_angle']}")
                        if data.get("root_cause"):
                            st.markdown(f"**Root Cause:** {data['root_cause']}")
                        if data.get("mechanism"):
                            st.markdown(f"**Mechanism:** {data['mechanism']}")
                except Exception:
                    pass
        return

    # ── Compare run ───────────────────────────────────────────────────────────
    info = _parse_compare_dir(selected_dir)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Keyword", info["keyword"])
    col2.metric("Brands", info["brands_compared"])
    col3.metric("Loopholes", len(info["loopholes"]))
    col4.metric("Focus Brand", info["focus_brand"] or "—")

    # PDF Section
    st.markdown("### 📄 PDF Report")
    # Use session_state path if it was just generated this session for this dir
    session_pdf = st.session_state.get("last_pdf_path")
    if session_pdf and Path(session_pdf).exists() and str(selected_dir) in str(st.session_state.get("last_compare_dir", "")):
        pdf_path = Path(session_pdf)
    else:
        pdf_path = info.get("pdf_path")

    _, refresh_col = st.columns([8, 1])
    with refresh_col:
        if st.button("🔄", help="Refresh — rescan for new PDF"):
            st.rerun()
    if pdf_path and pdf_path.exists():
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        dl_col, nt_col, info_col = st.columns([2, 2, 3])
        with dl_col:
            st.download_button(
                label=f"⬇ Download PDF ({pdf_path.stat().st_size // 1024}KB)",
                data=pdf_bytes,
                file_name=pdf_path.name,
                mime="application/pdf",
            )
        with nt_col:
            st.markdown(f'<a href="app/static/{pdf_path.name}" target="_blank" style="text-decoration:none;"><button style="padding:6px 14px;background:#444;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;">↗ Open in new tab</button></a>', unsafe_allow_html=True)
        with info_col:
            st.caption(f"📁 {pdf_path.name}")

        # Inline PDF viewer
        _pdf_iframe(pdf_path)
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

                bo_data = _load_blue_ocean_result(d)
                bo_badge = '&nbsp;·&nbsp; <span class="badge badge-pink">🌊 Blue Ocean</span>' if bo_data else ""
                st.markdown(f"""
                <div class="run-card">
                  <div class="run-card-title">{keyword}</div>
                  <div class="run-card-meta">{date_str} &nbsp;·&nbsp; {len(brand_reports)} brand reports{bo_badge}</div>
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
#  PAGE: CREATIVE FEEDBACK LOOP
# ══════════════════════════════════════════════════════════════════════════════
def page_creative_feedback():
    """Creative Feedback Loop Analyzer.

    Integrates all 7 fixes:
    FIX 1: CSV aggregation by ad name before matching
    FIX 2: Separate winner/loser thresholds (defaults: ROAS 1.0, spend $50)
    FIX 3: ROAS=0 with spend = LOSER
    FIX 4: Date range filters CSV, not ClickUp
    FIX 5: Top 50 as separate unfiltered section
    FIX 6: Novelty filter for pattern analysis
    FIX 7: Aggregation stats in pipeline log
    """
    import io
    import logging
    import tempfile
    import pandas as pd

    from creative_feedback_loop.csv_aggregator import load_and_aggregate_csv
    from creative_feedback_loop.classifier import ThresholdConfig, classify_ads
    from creative_feedback_loop.clickup_matcher import ClickUpTask, match_ads_to_clickup
    from creative_feedback_loop.top50 import build_top50
    from creative_feedback_loop.novelty_filter import compute_novelty
    from creative_feedback_loop.pipeline import run_pipeline, _extract_name_patterns

    st.markdown(
        '<div class="section-header">🔄 Creative Feedback Loop</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Upload a Meta Ads Manager CSV export. Ads are aggregated by name across ad sets, "
        "classified as winners/losers, matched to ClickUp tasks, and analyzed for patterns."
    )

    # ── Sidebar config ────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown("### Creative Feedback Config")

        # CSV Upload
        uploaded_csv = st.file_uploader(
            "Meta Ads Manager CSV",
            type=["csv"],
            help="Export from Ads Manager — one row per ad per ad set is fine, we aggregate automatically.",
            key="cfl_csv",
        )

        st.markdown("---")

        # FIX 4: Optional date range (filters CSV, NOT ClickUp)
        st.markdown("**Date Range (Optional)**")
        st.caption(
            "Filter rows within the CSV by date. Leave blank to use all data. "
            "Only works if CSV has a date column."
        )
        cfl_c1, cfl_c2 = st.columns(2)
        with cfl_c1:
            cfl_date_start = st.date_input("Start", value=None, key="cfl_ds")
        with cfl_c2:
            cfl_date_end = st.date_input("End", value=None, key="cfl_de")

        st.markdown("---")

        # FIX 2: Separate winner and loser thresholds
        st.markdown("**Winner Criteria**")
        st.caption("Ads meeting BOTH conditions = winner.")
        cfl_w_roas = st.number_input(
            "ROAS above", min_value=0.0, value=1.0, step=0.1, key="cfl_wr",
            help="Minimum ROAS to be a winner (default: 1.0 = breakeven)",
        )
        cfl_w_spend = st.number_input(
            "AND spend above ($)", min_value=0.0, value=50.0, step=10.0, key="cfl_ws",
        )

        st.markdown("---")

        st.markdown("**Loser Criteria**")
        st.caption("Ads meeting BOTH conditions = loser. ROAS=0 with spend = LOSER.")
        cfl_l_roas = st.number_input(
            "ROAS below", min_value=0.0, value=1.0, step=0.1, key="cfl_lr",
        )
        cfl_l_spend = st.number_input(
            "AND spend above ($)", min_value=0.0, value=50.0, step=10.0, key="cfl_ls",
        )

        st.markdown("---")

        # ClickUp tasks (optional JSON upload)
        clickup_file = st.file_uploader(
            "ClickUp Tasks JSON (optional)",
            type=["json"],
            help="Each task needs 'id', 'name', and optionally 'status', 'script'.",
            key="cfl_clickup",
        )

        cfl_run = st.button("Run Analysis", type="primary", use_container_width=True, key="cfl_run")

    # ── Main content area ─────────────────────────────────────────────────────
    if not uploaded_csv:
        st.info("Upload a Meta Ads Manager CSV in the sidebar to begin.")
        return

    if not cfl_run and "cfl_result" not in st.session_state:
        st.info("Configure thresholds in the sidebar, then click **Run Analysis**.")
        return

    # ── Run pipeline ──────────────────────────────────────────────────────────
    if cfl_run:
        thresholds = ThresholdConfig(
            winner_roas_min=cfl_w_roas,
            winner_spend_min=cfl_w_spend,
            loser_roas_max=cfl_l_roas,
            loser_spend_min=cfl_l_spend,
        )

        # Parse ClickUp tasks
        clickup_tasks = None
        if clickup_file:
            try:
                data = json.loads(clickup_file.getvalue())
                tasks_data = data if isinstance(data, list) else data.get("tasks", data.get("data", []))
                clickup_tasks = [
                    ClickUpTask(
                        task_id=t.get("id", ""),
                        name=t.get("name", ""),
                        status=(
                            t.get("status", {}).get("status", "")
                            if isinstance(t.get("status"), dict)
                            else str(t.get("status", ""))
                        ),
                        script=t.get("script", t.get("description", "")),
                        url=t.get("url", ""),
                    )
                    for t in tasks_data
                ]
            except (json.JSONDecodeError, KeyError) as e:
                st.error(f"Failed to parse ClickUp JSON: {e}")
                return

        # Save CSV to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(uploaded_csv.getvalue())
            csv_path = tmp.name

        # Set up logging capture (FIX 7)
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        cfl_logger = logging.getLogger("creative_feedback_loop")
        cfl_logger.setLevel(logging.INFO)
        cfl_logger.addHandler(handler)

        try:
            with st.spinner("Aggregating CSV rows and running analysis..."):
                result = run_pipeline(
                    csv_path=csv_path,
                    clickup_tasks=clickup_tasks,
                    thresholds=thresholds,
                    date_start=str(cfl_date_start) if cfl_date_start else None,
                    date_end=str(cfl_date_end) if cfl_date_end else None,
                )
                st.session_state["cfl_result"] = result
                st.session_state["cfl_log"] = log_stream.getvalue()
        finally:
            cfl_logger.removeHandler(handler)
            os.unlink(csv_path)

    if "cfl_result" not in st.session_state:
        return

    result = st.session_state["cfl_result"]

    # ── Pipeline Log (FIX 7) ──────────────────────────────────────────────────
    if st.session_state.get("cfl_log"):
        with st.expander("Pipeline Log", expanded=False):
            st.code(st.session_state["cfl_log"])

    # ── Aggregation Summary ───────────────────────────────────────────────────
    st.markdown("### Aggregation Summary")
    agg_cols = st.columns(4)
    with agg_cols[0]:
        st.metric("CSV Rows", f"{result.raw_rows:,}")
    with agg_cols[1]:
        st.metric("Unique Ads", f"{result.unique_ads:,}")
    with agg_cols[2]:
        st.metric("Total Spend", f"${result.total_csv_spend:,.2f}")
    with agg_cols[3]:
        ratio = result.raw_rows / result.unique_ads if result.unique_ads > 0 else 0
        st.metric("Avg Rows/Ad", f"{ratio:.1f}")

    st.caption(
        f"Aggregated **{result.raw_rows:,}** CSV rows into **{result.unique_ads:,}** unique ads"
    )

    # ── Classification Summary ────────────────────────────────────────────────
    st.markdown("### Classification")
    cls_cols = st.columns(4)
    with cls_cols[0]:
        st.metric("Winners", result.winner_count)
    with cls_cols[1]:
        st.metric("Losers", result.loser_count)
    with cls_cols[2]:
        st.metric("Untested", result.untested_count)
    with cls_cols[3]:
        st.metric("Above Spend Min", result.above_spend_threshold)

    t = result.thresholds
    st.caption(
        f"Winner: ROAS >= {t.winner_roas_min} AND spend >= ${t.winner_spend_min} | "
        f"Loser: ROAS < {t.loser_roas_max} AND spend >= ${t.loser_spend_min}"
    )

    # ── Section A: Winners & Losers ───────────────────────────────────────────
    st.markdown("### Section A: Winners & Losers")
    tab_w, tab_l, tab_u = st.tabs(["Winners", "Losers", "Untested"])

    with tab_w:
        _cfl_render_ad_table(
            [m for m in result.matched_ads if m.classified_ad.classification == "winner"],
            "winner",
        )
    with tab_l:
        _cfl_render_ad_table(
            [m for m in result.matched_ads if m.classified_ad.classification == "loser"],
            "loser",
        )
    with tab_u:
        _cfl_render_ad_table(
            [m for m in result.matched_ads if m.classified_ad.classification == "untested"],
            "untested",
        )

    # ── Section B: Top 50 by Spend (FIX 5) ────────────────────────────────────
    st.markdown("### Section B: Top 50 by Spend")
    st.caption(
        "Top 50 ads ranked by total aggregated spend. No winner/loser thresholds — "
        "just profitability classification."
    )

    if result.top50:
        top50_data = []
        for t50 in result.top50:
            row = {
                "Rank": t50.rank,
                "Ad Name": t50.ad.ad_name,
                "Total Spend": f"${t50.ad.total_spend:,.2f}",
                "ROAS": f"{t50.ad.blended_roas:.2f}",
                "Revenue": f"${t50.ad.total_revenue:,.2f}",
                "Impressions": f"{t50.ad.total_impressions:,}",
                "Conversions": t50.ad.total_conversions,
                "Status": _cfl_profitability_label(t50.profitability),
                "ClickUp": t50.clickup_task.name if t50.clickup_task else "—",
            }
            top50_data.append(row)
        st.dataframe(pd.DataFrame(top50_data), use_container_width=True, hide_index=True)
    else:
        st.info("No ads to display.")

    # ── Section C: Pattern Insights with Novelty Filter (FIX 6) ───────────────
    st.markdown("### Section C: Pattern Insights")

    if result.novelty:
        novelty = result.novelty

        if novelty.winner_signals:
            st.markdown("#### Winner Patterns (appear more in winners)")
            for sig in novelty.winner_signals:
                diff_pct = sig.differentiation * 100
                w_pct = sig.winner_rate * 100
                l_pct = sig.loser_rate * 100
                strength_md = {"HIGH": "***", "MEDIUM": "**", "LOW": "*"}.get(sig.signal_strength, "")
                st.markdown(
                    f"- {strength_md}`{sig.pattern}`{strength_md}: "
                    f"{w_pct:.0f}% of winners vs {l_pct:.0f}% of losers "
                    f"(+{diff_pct:.0f}% differentiation — {sig.signal_strength} signal)"
                )

        if novelty.loser_signals:
            st.markdown("#### Loser Patterns (appear more in losers)")
            for sig in novelty.loser_signals:
                diff_pct = abs(sig.differentiation) * 100
                l_pct = sig.loser_rate * 100
                w_pct = sig.winner_rate * 100
                st.markdown(
                    f"- `{sig.pattern}`: "
                    f"{l_pct:.0f}% of losers vs {w_pct:.0f}% of winners "
                    f"(+{diff_pct:.0f}% loser skew — {sig.signal_strength} signal)"
                )

        if novelty.baseline_patterns:
            st.markdown("#### Baseline Patterns (already standard practice)")
            st.caption(
                "These patterns appear in > 85% of ALL analyzed ads. "
                "They don't differentiate winners from losers — they're table stakes."
            )
            for sig in novelty.baseline_patterns:
                st.markdown(
                    f"- `{sig.pattern}` — {sig.total_rate * 100:.0f}% of all ads"
                )
    else:
        st.info(
            "Not enough winners and losers to compute pattern differentiation. "
            "Try lowering thresholds or using a larger CSV export."
        )


def _cfl_render_ad_table(matched_ads: list, classification: str):
    """Render a table of matched ads for the Creative Feedback Loop page."""
    import pandas as pd

    if not matched_ads:
        st.info(f"No {classification} ads found.")
        return

    data = []
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
            row["Match Score"] = f"{m.match_score:.0%}"
            script = m.clickup_task.script
            row["Script"] = (script[:100] + "...") if len(script) > 100 else script
        else:
            row["ClickUp Task"] = "—"
            row["Match Score"] = "—"
            row["Script"] = "—"
        data.append(row)

    data.sort(
        key=lambda r: float(r["Total Spend"].replace("$", "").replace(",", "")),
        reverse=True,
    )
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)


def _cfl_profitability_label(status: str) -> str:
    return {
        "profitable": "Profitable (ROAS >= 1.0)",
        "unprofitable": "Unprofitable (ROAS < 1.0)",
        "no_conversions": "No Conversions (ROAS = 0)",
    }.get(status, status)


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTER
# ══════════════════════════════════════════════════════════════════════════════
def main():
    if not _check_auth():
        return
    sidebar()
    page = st.session_state.page
    if page == "home":
        page_home()
    elif page == "results":
        page_results()
    elif page == "history":
        page_history()
    elif page == "creative_feedback":
        page_creative_feedback()


if __name__ == "__main__":
    main()
