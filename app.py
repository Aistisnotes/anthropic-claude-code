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
        "run_start_time": None,
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
        brand_pdfs = list(PDF_OUTPUT_DIR.glob("*_brand_analysis.pdf"))
        st.metric("Compare Runs", len(compare_dirs))
        st.metric("Market Runs", len(market_dirs))
        st.metric("Brand Reports", len(brand_pdfs))


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


def _find_pdf_for_brand(brand_name: str) -> Optional[Path]:
    """Find a brand_analysis PDF in PDF_OUTPUT_DIR matching a brand name."""
    if not PDF_OUTPUT_DIR.exists():
        return None
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", brand_name.lower()).strip("_")[:20]
    all_pdfs = sorted(
        PDF_OUTPUT_DIR.glob("*_brand_analysis.pdf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return next((p for p in all_pdfs if slug[:10] in p.stem.lower()), None)


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
def _force_stop():
    """Force-kill the running pipeline process and reset all state."""
    import os
    import signal
    proc = st.session_state.get("process")
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    st.session_state.running = False
    st.session_state._spawned = False
    st.session_state.process = None
    st.session_state.run_start_time = None


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
    st.session_state.run_start_time = time.time()  # Set in main thread — reliable
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
                start_new_session=True,
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
                        start_new_session=True,
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


def _run_pipeline_direct(brands_text: str, keyword: str, ads_per_brand: int, run_compare: bool):
    """Execute direct brand URL pipeline in a background thread."""
    if st.session_state.running or st.session_state._spawned:
        return
    st.session_state.running = True
    st.session_state._spawned = True
    st.session_state.run_start_time = time.time()  # Set in main thread — reliable

    log = st.session_state.run_log
    log.clear()

    def _log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        log.append(f"[{ts}] {msg}")

    def _run():
        st.session_state.last_compare_dir = None
        st.session_state.last_pdf_path = None

        try:
            lines = [l.strip() for l in brands_text.strip().splitlines() if l.strip()]
            _log(f"Direct analysis: {len(lines)} brand(s), topic: {keyword or 'direct'}")

            # Build CLI args: each line becomes one argument
            cmd = [str(META_ADS_BIN), "direct"] + lines + [
                "--ads-per-brand", str(ads_per_brand),
            ]
            if keyword.strip():
                cmd += ["--keyword", keyword.strip()]
            if not run_compare:
                cmd += ["--no-compare"]

            _log(f"Command: meta-ads direct ({len(lines)} brands)")
            _log("─" * 50)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(PROJECT_ROOT),
                start_new_session=True,
            )
            st.session_state.process = proc

            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    import re as _re
                    clean = _re.sub(r'\x1b\[[0-9;]*m', '', line)
                    _log(clean)

            proc.wait()
            _log("─" * 50)

            if proc.returncode == 0:
                _log("✓ Direct analysis complete")

                # Find latest market dir (direct runs use market_ prefix)
                market_dirs = _get_market_dirs()
                if market_dirs:
                    latest = market_dirs[0]
                    st.session_state.last_compare_dir = latest

                # Find latest compare dir if compare ran
                compare_dirs = _get_compare_dirs()
                if compare_dirs and run_compare:
                    latest_cmp = compare_dirs[0]
                    st.session_state.last_compare_dir = latest_cmp
                    loophole_path = latest_cmp / "strategic_loophole_doc.json"
                    if loophole_path.exists():
                        _log("Generating PDF report...")
                        try:
                            from meta_ads_analyzer.reporter.pdf_generator import generate_pdf_sync
                            pdf_path = generate_pdf_sync(
                                loophole_doc_path=loophole_path,
                                market_map_path=latest_cmp / "strategic_market_map.json",
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

    tab_direct, tab_keyword = st.tabs(["🔗 Direct Brand URLs", "🔍 Keyword Search"])

    # ── Tab 1: Direct Brand URLs (primary) ───────────────────────────────────
    with tab_direct:
        st.markdown(
            "Enter the **domain** of each brand you want to analyze — one per line. "
            "This searches all active ads running to that domain across every advertiser page, "
            "sorted by impressions."
        )

        col1, col2 = st.columns([3, 2])

        with col1:
            brands_text = st.text_area(
                "Brand domains",
                placeholder=(
                    "My Brand: elarebeauty.com\n"
                    "Competitor A: sculptique.com\n"
                    "Competitor B: trylumine.com"
                ),
                height=160,
                label_visibility="collapsed",
                key="input_direct_brands",
            )
            keyword_direct = st.text_input(
                "Research topic (optional — for report naming)",
                placeholder="collagen eye mask, vertigo supplement, ...",
                key="input_direct_keyword",
            )

        with col2:
            st.markdown("#### Options")
            ads_direct = st.slider("Ads per brand", 10, 100, 50, key="direct_ads")
            compare_direct = st.checkbox("Run compare after analysis", value=True, key="direct_compare")
            st.caption(
                "Format: `Brand Name: domain.com` or just `domain.com`.\n\n"
                "Captures ads from the brand's own pages **and** 3rd party affiliates/influencers — "
                "all sorted by impressions so the highest-reach ads get analyzed first."
            )

        st.markdown("---")
        run_col, stop_col, _ = st.columns([2, 1, 4])
        with run_col:
            if st.button("▶ Run Direct Analysis", disabled=st.session_state.running, use_container_width=True, key="btn_direct"):
                if not brands_text.strip():
                    st.error("Please enter at least one brand domain.")
                else:
                    _run_pipeline_direct(
                        brands_text=brands_text.strip(),
                        keyword=keyword_direct.strip(),
                        ads_per_brand=ads_direct,
                        run_compare=compare_direct,
                    )
                    st.rerun()
        with stop_col:
            if st.button("⏹ Stop", key="stop_direct", disabled=not st.session_state.running):
                _force_stop()
                st.rerun()

    # ── Tab 2: Keyword Search (secondary) ────────────────────────────────────
    with tab_keyword:
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
            top_brands = st.slider("Top brands", 3, 15, 8, key="kw_top_brands")
            ads_per_brand = st.slider("Ads per brand", 10, 50, 30, key="kw_ads_per_brand")
            run_compare = True
            if mode == "Market Research + Compare":
                run_compare = st.checkbox("Auto-run compare after market", value=True, key="kw_run_compare")

        st.markdown("---")
        run_col, stop_col, _ = st.columns([2, 1, 4])
        with run_col:
            if st.button("▶ Run Analysis", disabled=st.session_state.running, use_container_width=True, key="btn_keyword"):
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
            if st.button("⏹ Stop", key="stop_keyword", disabled=not st.session_state.running):
                _force_stop()
                st.rerun()

    # Progress + log (shared across both tabs)
    if st.session_state.running or st.session_state.run_log:
        import re as _pre

        # Parse current brand progress from log lines
        _cur, _tot = 0, 0
        for _ln in st.session_state.run_log:
            _m = _pre.search(r'Brand\s+(\d+)/(\d+)', _ln)
            if _m:
                _cur, _tot = int(_m.group(1)), int(_m.group(2))

        _elapsed = 0.0
        if st.session_state.run_start_time:
            _elapsed = time.time() - st.session_state.run_start_time

        if st.session_state.running:
            _e_str = f"{int(_elapsed // 60)}m {int(_elapsed % 60)}s elapsed"
            if _tot > 0:
                # Progress bar: complete brand = 1.0, in-progress brand counts as 0.5
                _frac = max(0.0, min(1.0, (_cur - 0.5) / _tot))
                st.progress(_frac, text=f"Brand {_cur} / {_tot}")
                if _cur > 1:
                    _avg = _elapsed / (_cur - 1)
                    _rem = (_tot - _cur + 1) * _avg
                    _r_str = f"{int(_rem // 60)}m {int(_rem % 60)}s left"
                else:
                    _r_str = "estimating…"
                st.caption(f"{_e_str}  ·  ~{_r_str}")
            else:
                st.progress(0.0, text="Starting pipeline…")
                st.caption(_e_str)

        with st.expander("🔍 Pipeline Output", expanded=False):
            _log_text = "\n".join(st.session_state.run_log[-200:]) or "(waiting for output…)"
            st.code(_log_text, language=None)

    # Auto-refresh while running
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
                    pr = data.get("pattern_report", {})
                    adv = data.get("advertiser", {})
                    brand_name = adv.get("page_name") or data.get("brand_name") or bf.stem
                    brand_pdf = _find_pdf_for_brand(brand_name)
                    col_exp, col_pdf = st.columns([5, 1])
                    with col_exp:
                        with st.expander(f"📋 {brand_name}"):
                            if pr.get("competitive_verdict"):
                                st.markdown(f"**Verdict:** {pr['competitive_verdict']}")
                            if pr.get("executive_summary"):
                                st.caption(pr["executive_summary"][:300])
                            if pr.get("key_insights"):
                                st.markdown("**Key Insights**")
                                for ins in pr["key_insights"][:3]:
                                    st.markdown(f"- {ins}")
                    with col_pdf:
                        if brand_pdf and brand_pdf.exists():
                            with open(brand_pdf, "rb") as f:
                                st.download_button(
                                    "PDF",
                                    data=f.read(),
                                    file_name=brand_pdf.name,
                                    mime="application/pdf",
                                    key=f"dl_brand_{bf.name}",
                                )
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
        pdf_reports = sorted(PDF_OUTPUT_DIR.glob("*_brand_analysis.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not pdf_reports:
            st.info("No brand reports yet.")
        else:
            st.caption(f"{len(pdf_reports)} brand reports")
            search = st.text_input("Filter by brand name", placeholder="Elare, Sculptique...")
            for rpt in pdf_reports[:100]:
                if search and search.lower() not in rpt.stem.lower():
                    continue
                # Parse filename: {brand_slug}_{keyword_slug}_{YYYYMMDD}_brand_analysis.pdf
                stem = rpt.stem  # e.g. elare_collagen_20260309_brand_analysis
                parts = stem.split("_")
                date_str = ""
                label = stem.replace("_brand_analysis", "").replace("_", " ").title()
                # Try to extract date (3rd from last part before "brand_analysis")
                for i, p in enumerate(parts):
                    if len(p) == 8 and p.isdigit():
                        try:
                            dt = datetime.strptime(p, "%Y%m%d")
                            date_str = dt.strftime("%b %d, %Y")
                            label = " ".join(parts[:i]).replace("_", " ").title()
                        except ValueError:
                            pass
                        break
                col1, col2, col3 = st.columns([5, 1, 1])
                with col1:
                    st.markdown(f"""
                    <div class="run-card" style="border-left-color:#e91e8c;">
                      <div class="run-card-title">{label}</div>
                      <div class="run-card-meta">{date_str} &nbsp;·&nbsp; {rpt.stat().st_size // 1024}KB</div>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    with open(rpt, "rb") as f:
                        st.download_button(
                            "PDF",
                            data=f.read(),
                            file_name=rpt.name,
                            mime="application/pdf",
                            key=f"dl_rpt_{rpt.name}",
                        )
                with col3:
                    # Copy to static dir and offer new-tab link
                    dest = STATIC_DIR / rpt.name
                    if not dest.exists():
                        import shutil as _shutil2
                        _shutil2.copy2(rpt, dest)
                    st.markdown(f'<a href="app/static/{rpt.name}" target="_blank" style="text-decoration:none;"><button style="padding:4px 10px;background:#444;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px;">↗</button></a>', unsafe_allow_html=True)


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


if __name__ == "__main__":
    main()
