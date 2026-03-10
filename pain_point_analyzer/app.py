"""Pain Point Analyzer — Streamlit Web UI.

Takes a product page URL, extracts ingredients, discovers pain points,
validates with Meta Ad Library, runs scientific research, and builds
root cause + mechanism positioning for the top 3 pain points.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from pathlib import Path

import streamlit as st

# ── Project paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH = PROJECT_ROOT / "config" / "default.toml"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = OUTPUT_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_INDEX = REPORTS_DIR / "reports_index.json"

# Add project root to path
sys.path.insert(0, str(PROJECT_ROOT.parent))

# Load .env file if present
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _load_config() -> dict:
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


# ── Auth ───────────────────────────────────────────────────────────────────────
def _check_auth() -> bool:
    """Return True if authenticated. Bypass if TOOL_PASSWORD not set."""
    if st.session_state.get("authenticated"):
        return True

    expected_user = os.environ.get("TOOL_USERNAME", "admin")
    expected_pass = os.environ.get("TOOL_PASSWORD", "")

    if not expected_pass:
        st.session_state["authenticated"] = True
        return True

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("## Pain Point Analyzer")
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


# ── Time estimation ───────────────────────────────────────────────────────────
def _estimate_time(num_pain_points: int, num_cached: int, num_top: int = 3) -> str:
    """Estimate total pipeline time in minutes."""
    step1 = 30  # ingredient extraction
    step2 = 45  # pain point discovery
    step3 = (num_pain_points - num_cached) * 20  # Meta Ad Library (cached = 0s)
    step4 = num_top * 60  # scientific research
    step5 = num_top * 90  # positioning
    step6 = 30  # report generation
    total = step1 + step2 + step3 + step4 + step5 + step6
    minutes = total / 60
    return f"~{minutes:.0f} minutes"


def _format_elapsed(seconds: float) -> str:
    """Format seconds as M:SS."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


# ── Pipeline runner ────────────────────────────────────────────────────────────
async def _run_pipeline(url: str, config: dict, status_placeholder):
    """Run the full 6-step pipeline."""
    from analyzer.ingredient_extractor import IngredientExtractor

    progress_bar = status_placeholder.progress(0, text="Starting analysis...")

    def update(msg: str, pct: float | None = None):
        if pct is not None:
            progress_bar.progress(pct, text=msg)
        else:
            status_placeholder.text(msg)

    # Step 1: Extract ingredients
    update("Step 1/6: Extracting ingredients...", 0.05)
    extractor = IngredientExtractor(config)
    try:
        extraction = await extractor.extract(
            url, progress_cb=lambda m: update(f"Step 1/6: {m}", 0.10)
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logging.error(f"Ingredient extraction failed: {tb}")
        update(f"Extraction error: {e}", 0.15)
        extraction = None

    if extraction is None:
        st.error("Ingredient extraction failed. Check that Playwright is installed "
                 "(`python3 -m playwright install chromium`) and your ANTHROPIC_API_KEY is set.")
        return None

    st.session_state["extraction"] = extraction

    # Show any warnings from extraction
    for w in extraction.warnings:
        st.warning(w)

    if len(extraction.ingredients) == 0:
        st.session_state["needs_manual_input"] = True
        st.session_state["pipeline_paused"] = True
        sources_info = ", ".join(
            f"{k}: {len(v)} chars" for k, v in extraction.raw_sources.items()
        ) if extraction.raw_sources else "none"
        logging.warning(f"No ingredients found. Raw sources: {sources_info}")
        update(f"No ingredients found (sources: {sources_info}). Please provide them manually.", 0.15)
        return None

    return await _run_remaining_pipeline(
        extraction, config, url, update
    )


async def _run_pipeline_from_text(
    product_name: str,
    brand_name: str,
    ingredient_text: str,
    config: dict,
    status_placeholder,
):
    """Run the pipeline starting from pasted ingredient text (no scraping)."""
    from analyzer.ingredient_extractor import (
        ExtractionResult,
        IngredientExtractor,
        ProductInfo,
    )

    progress_bar = status_placeholder.progress(0, text="Starting analysis...")

    def update(msg: str, pct: float | None = None):
        if pct is not None:
            progress_bar.progress(pct, text=msg)
        else:
            status_placeholder.text(msg)

    # Step 1: Parse pasted ingredients with Claude
    update("Step 1/6: Parsing ingredients...", 0.05)
    extractor = IngredientExtractor(config)
    ingredients = await extractor.extract_from_text(ingredient_text)
    update(f"Step 1/6: Found {len(ingredients)} ingredients", 0.15)

    extraction = ExtractionResult(
        product=ProductInfo(
            product_name=product_name,
            brand_name=brand_name,
        ),
        ingredients=ingredients,
    )

    if len(ingredients) < 1:
        status_placeholder.error("No ingredients could be parsed from the text.")
        return None

    return await _run_remaining_pipeline(extraction, config, "", update)


async def _run_remaining_pipeline(extraction, config, url, update):
    """Run steps 2-6 after ingredients are confirmed."""
    from analyzer.pain_point_discovery import PainPointDiscovery
    from analyzer.trends_validator import TrendsValidator, _get_cached
    from analyzer.scientific_researcher import ScientificResearcher
    from analyzer.positioning_engine import PositioningEngine
    from analyzer.report_generator import ReportGenerator

    pipeline_start = time.time()
    log_entries = []

    def log_and_update(msg: str, pct: float | None = None, level: str = "info"):
        elapsed = time.time() - pipeline_start
        timestamp = _format_elapsed(elapsed)
        log_entries.append({"time": timestamp, "msg": msg, "level": level})
        if pct is not None:
            update(msg, pct)
        else:
            update(msg)

    include_single = st.session_state.get("include_single_ingredient", False)

    # Step 2: Discover pain points
    log_and_update("Step 2/6: Discovering pain points...", 0.20)
    discovery_engine = PainPointDiscovery(config)
    discovery = await discovery_engine.discover(
        extraction.ingredients,
        progress_cb=lambda m: log_and_update(f"Step 2/6: {m}", 0.30),
    )

    # Count cached pain points for time estimate
    num_pp = len(discovery.pain_points)
    num_cached = sum(
        1 for pp in discovery.pain_points if _get_cached(pp.name)
    )
    est = _estimate_time(num_pp, num_cached)
    log_and_update(f"Estimated remaining time: {est}", 0.32)

    # Step 3: Meta Ad Library demand validation
    log_and_update("Step 3/6: Validating demand via Meta Ad Library...", 0.35)
    trends_engine = TrendsValidator(config)
    trends = await trends_engine.validate(
        discovery.pain_points,
        progress_cb=lambda m: log_and_update(f"Step 3/6: {m}", 0.50),
        include_single_ingredient=include_single,
    )

    # Step 4: Scientific research
    log_and_update("Step 4/6: Running scientific research...", 0.55)
    researcher = ScientificResearcher(config)
    research = await researcher.research(
        trends.top_results,
        extraction.ingredients,
        progress_cb=lambda m: log_and_update(f"Step 4/6: {m}", 0.65),
    )

    # Step 5: Positioning
    log_and_update("Step 5/6: Building positioning...", 0.75)
    positioning_engine = PositioningEngine(config)
    positioning = await positioning_engine.build_positioning(
        trends.top_results,
        research.reports,
        extraction.ingredients,
        progress_cb=lambda m: log_and_update(f"Step 5/6: {m}", 0.85),
    )

    # Step 6: Generate report
    log_and_update("Step 6/6: Generating report...", 0.90)
    reporter = ReportGenerator(config)
    report = reporter.generate(
        extraction, discovery, trends, research, positioning, url
    )

    # Try PDF
    pdf_path = reporter.generate_pdf(report)
    report["_pdf_path"] = str(pdf_path) if pdf_path else None

    elapsed = time.time() - pipeline_start
    log_and_update(f"Analysis complete in {_format_elapsed(elapsed)}", 1.0)

    report["_pipeline_log"] = log_entries
    report["_elapsed"] = elapsed
    return report


# ── Global CSS ────────────────────────────────────────────────────────────────
GLOBAL_CSS = """
<style>
/* ═══════════════════════════════════════════════════════════════════════════
   PERMANENT TEXT COLOR FIX — uses !important on ALL elements to prevent
   dynamic Streamlit re-renders from overriding colors.
   ═══════════════════════════════════════════════════════════════════════════ */

/* Force dark text on ALL Streamlit markdown containers */
.stMarkdown div[data-testid="stMarkdownContainer"],
.stMarkdown div[data-testid="stMarkdownContainer"] *,
.stMarkdown p,
.stMarkdown li,
.stMarkdown td,
.stMarkdown th,
.stMarkdown span,
.stMarkdown div {
    color: #1a1a1a !important;
}

/* Metric labels/values */
[data-testid="stMetricValue"] { color: #1a1a1a !important; }
[data-testid="stMetricLabel"] { color: #444444 !important; }
[data-testid="stMetricDelta"] { color: #555555 !important; }

/* All table cells */
.stDataFrame td, .stDataFrame th,
table td, table th,
.dataframe td, .dataframe th {
    color: #1a1a1a !important;
}

/* All paragraph, list, header text */
.element-container p,
.element-container li,
.element-container h1,
.element-container h2,
.element-container h3,
.element-container h4,
.element-container h5 {
    color: #1a1a1a !important;
}

/* Expander text */
.streamlit-expanderContent p,
.streamlit-expanderContent li,
.streamlit-expanderContent div,
.streamlit-expanderContent span,
.streamlit-expanderContent td,
.streamlit-expanderContent th {
    color: #1a1a1a !important;
}

/* ── Tier badges ───────────────────────────────────────────────────────── */
.tier-badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 12px;
    font-size: 0.8em;
    font-weight: 700;
    letter-spacing: 0.3px;
}
.tier-open {
    background: #4caf50 !important;
    color: #ffffff !important;
}
.tier-solid {
    background: #f9a825 !important;
    color: #000000 !important;
}
.tier-saturated {
    background: #ff9800 !important;
    color: #ffffff !important;
}
.tier-super-saturated {
    background: #ef5350 !important;
    color: #ffffff !important;
}
.tier-unknown {
    background: #9e9e9e !important;
    color: #ffffff !important;
}

/* ── Result cards ──────────────────────────────────────────────────────── */
.pp-card {
    background: #fafafa !important;
    padding: 12px 16px !important;
    margin-bottom: 8px !important;
    border-radius: 0 6px 6px 0 !important;
}
.pp-card strong,
.pp-card span,
.pp-card div,
.pp-card p {
    color: #1a1a1a !important;
}
/* Override for specific colored spans inside cards */
.pp-card .tier-badge.tier-open,
.pp-card .tier-badge.tier-saturated,
.pp-card .tier-badge.tier-super-saturated,
.pp-card .tier-badge.tier-unknown {
    color: #ffffff !important;
}
.pp-card .tier-badge.tier-solid {
    color: #000000 !important;
}
.pp-card .top3-badge {
    background: #1565c0 !important;
    color: #ffffff !important;
    font-size: 0.75em !important;
    padding: 2px 8px !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
}
.pp-card .cache-tag {
    color: #888888 !important;
    font-size: 0.85em !important;
}
.pp-card .kw-display {
    font-size: 0.85em !important;
    color: #555555 !important;
    margin-top: 2px !important;
}
.pp-card .skip-display {
    font-size: 0.85em !important;
    color: #888888 !important;
    margin-top: 2px !important;
}
.pp-card .error-display {
    color: #c62828 !important;
    font-weight: 700 !important;
}

/* ── Skipped section ───────────────────────────────────────────────────── */
.skipped-section summary {
    cursor: pointer;
    color: #666666 !important;
    font-size: 0.9em !important;
    padding: 8px 0 !important;
}
.skipped-section .pp-card {
    background: #f5f5f5 !important;
    border-left-color: #9e9e9e !important;
    opacity: 0.85;
}

/* ── Pipeline log ──────────────────────────────────────────────────────── */
.pipeline-log {
    font-family: monospace !important;
    font-size: 0.85em !important;
    background: #fafafa !important;
    border: 1px solid #e0e0e0 !important;
    border-radius: 6px !important;
    padding: 12px !important;
    max-height: 400px !important;
    overflow-y: auto !important;
    color: #333333 !important;
}
.pipeline-log .log-error { color: #c62828 !important; font-weight: 700 !important; }
.pipeline-log .log-cached { color: #888888 !important; }
.pipeline-log .log-info { color: #333333 !important; }

/* ── Tier warning flags ────────────────────────────────────────────────── */
.flag-saturated {
    color: #e65100 !important;
    font-weight: 700 !important;
    font-size: 0.9em !important;
}
.flag-super-saturated {
    color: #c62828 !important;
    font-weight: 700 !important;
    font-size: 0.9em !important;
}

/* ── Reports tab text fix ──────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-panel"] p,
.stTabs [data-baseweb="tab-panel"] li,
.stTabs [data-baseweb="tab-panel"] td,
.stTabs [data-baseweb="tab-panel"] th,
.stTabs [data-baseweb="tab-panel"] span,
.stTabs [data-baseweb="tab-panel"] div,
.stTabs [data-baseweb="tab-panel"] strong,
.stTabs [data-baseweb="tab-panel"] h1,
.stTabs [data-baseweb="tab-panel"] h2,
.stTabs [data-baseweb="tab-panel"] h3 {
    color: #1a1a1a !important;
}

/* Deep-dive sections */
.stExpander p,
.stExpander li,
.stExpander span,
.stExpander div,
.stExpander td,
.stExpander th {
    color: #1a1a1a !important;
}
</style>
"""


def _tier_badge_class(tier: int) -> str:
    """Return the CSS class for a tier badge."""
    return {
        0: "tier-unknown",
        1: "tier-open",
        2: "tier-solid",
        3: "tier-saturated",
        4: "tier-super-saturated",
    }.get(tier, "tier-unknown")


# ── Results display ────────────────────────────────────────────────────────────
def _show_results(report: dict):
    """Display the analysis results inline."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    # Completion banner
    elapsed = report.get("_elapsed")
    if elapsed:
        st.success(f"Analysis complete in {_format_elapsed(elapsed)}")

    # Pipeline log (collapsed)
    log_entries = report.get("_pipeline_log", [])
    if log_entries:
        with st.expander("Pipeline Log (click to expand)", expanded=False):
            log_html = '<div class="pipeline-log">'
            for entry in log_entries:
                level = entry.get("level", "info")
                if "error" in entry.get("msg", "").lower() or level == "error":
                    css_class = "log-error"
                elif "cached" in entry.get("msg", "").lower():
                    css_class = "log-cached"
                else:
                    css_class = "log-info"
                log_html += (
                    f'<div class="{css_class}">'
                    f'[{entry["time"]}] {entry["msg"]}'
                    f'</div>'
                )
            log_html += '</div>'
            st.markdown(log_html, unsafe_allow_html=True)

    product = report["product"]

    # PDF download at the top
    pdf_path_str = report.get("_pdf_path")
    pdf_path = Path(pdf_path_str) if pdf_path_str else None

    if pdf_path and pdf_path.exists():
        # Copy to reports dir so it shows in Reports tab
        reports_copy = REPORTS_DIR / pdf_path.name
        if not reports_copy.exists():
            try:
                reports_copy.write_bytes(pdf_path.read_bytes())
            except Exception:
                pass

        pdf_bytes = pdf_path.read_bytes()
        st.download_button(
            label="Export PDF",
            data=pdf_bytes,
            file_name=pdf_path.name,
            mime="application/pdf",
            use_container_width=True,
            key="pdf_download_top",
        )
        st.success(f"PDF ready — click above to download ({pdf_path.name})")
    else:
        # Try to generate PDF on the fly
        if st.button("Generate PDF", use_container_width=True, key="gen_pdf_top"):
            with st.spinner("Generating PDF..."):
                try:
                    config = _load_config()
                    from analyzer.report_generator import ReportGenerator
                    reporter = ReportGenerator(config)
                    new_pdf = reporter.generate_pdf(report)
                    if new_pdf and new_pdf.exists():
                        report["_pdf_path"] = str(new_pdf)
                        st.session_state["report"]["_pdf_path"] = str(new_pdf)
                        # Copy to reports dir
                        reports_copy = REPORTS_DIR / new_pdf.name
                        if not reports_copy.exists():
                            reports_copy.write_bytes(new_pdf.read_bytes())
                        st.success(f"PDF saved and downloading... ({new_pdf.name})")
                        st.download_button(
                            label="Download PDF",
                            data=new_pdf.read_bytes(),
                            file_name=new_pdf.name,
                            mime="application/pdf",
                            use_container_width=True,
                            key="pdf_download_generated",
                        )
                    else:
                        st.error(
                            "PDF generation failed. Ensure Playwright is installed: "
                            "`python3 -m playwright install chromium`"
                        )
                except Exception as e:
                    st.error(f"PDF generation error: {e}")

    st.markdown(f"## {product['name']}")
    st.markdown(f"**Brand:** {product['brand']}")
    if product.get("description"):
        st.markdown(f"> {product['description']}")

    # Ingredients table
    st.markdown("### Ingredients")
    ing_data = []
    for ing in product["ingredients"]:
        amount = f"{ing['amount']} {ing['unit'] or ''}" if ing["amount"] else "—"
        ing_data.append({
            "Ingredient": ing["name"],
            "Amount": amount,
            "Sources": ", ".join(ing["sources"]),
        })
    st.dataframe(ing_data, use_container_width=True)

    # Pain points overview
    st.markdown("### All Pain Points Discovered")
    pp_data = []
    for pp in report["all_pain_points"]:
        pp_data.append({
            "Pain Point": pp["name"],
            "Category": pp["category"],
            "# Ingredients": pp["ingredient_count"],
            "Supporting": ", ".join(pp["supporting_ingredients"]),
        })
    st.dataframe(pp_data, use_container_width=True)

    # Meta Ad Library Demand Validation
    st.markdown("### Meta Ad Library — Market Demand")

    # Check if meta was unreachable
    meta_reachable = report.get("_meta_reachable", True)
    if not meta_reachable:
        st.warning(
            "Meta Ad Library is unreachable from this network. "
            "Ad count validation was skipped. Tier classification unavailable. "
            "Try from a different network or wait and retry."
        )

    # Split validated vs skipped pain points
    validated_trends = [t for t in report["trends"] if not t.get("skipped", False)]
    skipped_trends = [t for t in report["trends"] if t.get("skipped", False)]

    def _render_pp_card(t: dict):
        """Render a single pain point card."""
        tier = t.get("tier", 1)
        tier_label = t.get("tier_label", "OPEN")
        ad_count = t.get("best_score", 0)
        is_top = t.get("is_top", False)
        from_cache = t.get("from_cache", False)
        cache_date = t.get("cache_date", "")
        skipped = t.get("skipped", False)
        skip_reason = t.get("skip_reason", "")

        badge_class = _tier_badge_class(tier)
        border_color = {1: "#4caf50", 2: "#f9a825", 3: "#ff9800", 4: "#ef5350"}.get(tier, "#9e9e9e")

        top_badge = ' <span class="top3-badge">TOP 3</span>' if is_top else ""

        # Build ad display text
        if ad_count <= 0:
            if ad_count == -2:
                ad_display = '<span class="error-display">Could not retrieve</span> — try again later'
            else:
                ad_display = '<span class="cache-tag">N/A</span>'
        else:
            if from_cache and cache_date:
                cache_tag = f' <span class="cache-tag">(cached, checked {cache_date})</span>'
            else:
                cache_tag = ' <span class="cache-tag">(fresh)</span>'
            ad_display = f'{ad_count:,} active ads{cache_tag}'

        # Keyword display
        kw_display = ""
        if ad_count > 0 and t.get("keywords"):
            kw_list = ", ".join(
                f'{kw["keyword"]} ({kw["score"]})' for kw in t.get("keywords", [])
            )
            kw_display = f'<div class="kw-display">Keywords: {kw_list}</div>'

        # Skip info
        skip_display = ""
        if skipped and skip_reason:
            skip_display = f'<div class="skip-display">{skip_reason}</div>'

        st.markdown(
            f'<div class="pp-card" style="border-left:5px solid {border_color};">'
            f'<strong>{t["pain_point"]}</strong>{top_badge}<br>'
            f'<span class="tier-badge {badge_class}">{tier_label}</span> — '
            f'{ad_display}<br>'
            f'{kw_display}'
            f'{skip_display}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Tier warnings
        if tier == 3:
            st.markdown(
                '<div class="flag-saturated">'
                'Saturated — strong rootcause/mechanism required'
                '</div>',
                unsafe_allow_html=True,
            )
        elif tier == 4:
            st.markdown(
                '<div class="flag-super-saturated">'
                'Super saturated — extremely difficult to stand out'
                '</div>',
                unsafe_allow_html=True,
            )

    # Render validated pain points first
    for t in validated_trends:
        _render_pp_card(t)

    # Render skipped pain points in collapsed accordion at bottom
    if skipped_trends:
        st.markdown(
            f'<div class="skipped-section">'
            f'<details>'
            f'<summary>Skipped Pain Points — single ingredient support '
            f'({len(skipped_trends)} items)</summary>'
            f'</details>'
            f'</div>',
            unsafe_allow_html=True,
        )
        with st.expander(
            f"Skipped Pain Points ({len(skipped_trends)} items)",
            expanded=False,
        ):
            for t in skipped_trends:
                _render_pp_card(t)

    # Check if ALL pain points had scraper errors
    all_scraper_errors = all(
        t.get("best_score", 0) <= 0 for t in validated_trends
    )
    if all_scraper_errors and validated_trends and meta_reachable:
        st.warning(
            "Could not validate demand — Meta Ad Library unreachable for "
            "these keywords. Run again or check manually."
        )

    # If meta was unreachable, show unavailable message
    if not meta_reachable:
        st.info(
            "Tiers unavailable — Meta Ad Library unreachable. "
            "Pain points are shown but tier classification was skipped."
        )

    # Top deep dives
    st.markdown("---")
    st.markdown("## Top Pain Points — Deep Dive")

    for i, dive in enumerate(report["top_deep_dives"]):
        st.markdown(f"### #{i+1}: {dive['pain_point']}")

        col1, col2, col3, col4 = st.columns(4)
        ad_score = dive.get('trend_score', 0)
        col1.metric("Active Ads", f"{ad_score:,}" if ad_score > 0 else "N/A")
        col2.metric("Tier", dive.get("tier_label", "—"))
        if dive.get("science"):
            col3.metric("Evidence", dive["science"]["overall_evidence"].title())
        col4.metric("Ingredients", len(dive["supporting_ingredients"]))

        # Science
        if dive.get("science"):
            with st.expander("Scientific Evidence", expanded=True):
                st.info(dive["science"]["summary"])
                for ev in dive["science"]["ingredient_evidence"]:
                    st.markdown(f"**{ev['ingredient']}** — Evidence: `{ev['strength']}`")
                    st.markdown(f"_{ev['mechanism']}_")
                    if ev.get("optimal_dosage"):
                        st.markdown(f"Optimal dosage: {ev['optimal_dosage']}")
                    for s in ev.get("studies", []):
                        st.markdown(
                            f"- {s['description']} "
                            f"(Dose: {s['dosage']}, Duration: {s['duration']}, "
                            f"Effect: {s['effect_size']})"
                        )
                    if ev.get("contraindications"):
                        st.warning("Contraindications: " + ", ".join(ev["contraindications"]))

                if dive["science"].get("synergies"):
                    st.markdown("**Synergies:**")
                    for syn in dive["science"]["synergies"]:
                        st.success(
                            f"**{' + '.join(syn['ingredients'])}**: "
                            f"{syn['description']}"
                        )

        # Positioning
        if dive.get("positioning"):
            pos = dive["positioning"]
            with st.expander("Root Cause + Mechanism Positioning", expanded=True):
                st.markdown("**Root Cause Depth:**")
                col1, col2 = st.columns(2)
                col1.markdown(f"_Surface:_ {pos['root_cause']['surface']}")
                col2.markdown(f"_Cellular:_ {pos['root_cause']['cellular']}")
                st.markdown(f"_Molecular:_ {pos['root_cause']['molecular']}")

                st.markdown(f"**Mechanism:** {pos['mechanism']}")

                st.markdown("**Avatar:**")
                avatar = pos["avatar"]
                if avatar.get("narrative"):
                    st.markdown(avatar["narrative"])
                else:
                    st.markdown(
                        f"Age: {avatar.get('age', 'N/A')} | "
                        f"Gender: {avatar.get('gender', 'N/A')} | "
                        f"Lifestyle: {avatar.get('lifestyle', 'N/A')}"
                    )
                if avatar.get("habit_history"):
                    st.markdown(f"**Core Habit:** {avatar['habit_history']}")
                if avatar.get("root_cause_connection"):
                    st.markdown(f"**Why It Matters:** {avatar['root_cause_connection']}")
                if avatar.get("failed_solutions"):
                    st.markdown("**What They've Tried (And Why It Failed):**")
                    for sol in avatar["failed_solutions"]:
                        st.markdown(f"- {sol}")
                elif avatar.get("tried_before"):
                    st.markdown(
                        f"_Tried before:_ {', '.join(avatar['tried_before'])}"
                    )
                if avatar.get("urgency_trigger"):
                    st.markdown(f"**Why Now:** {avatar['urgency_trigger']}")

                if pos.get("daily_symptoms"):
                    st.markdown("**Daily Symptoms:**")
                    for s in pos["daily_symptoms"]:
                        st.markdown(f"- {s}")

                if pos.get("mass_desire"):
                    st.info(f"**Mass Desire:** {pos['mass_desire']}")

                if pos.get("hooks"):
                    st.markdown("**Hook Examples:**")
                    for h in pos["hooks"]:
                        st.markdown(f'> "{h}"')

        st.markdown("---")

    # Synergy map
    if report.get("synergy_map"):
        st.markdown("### Ingredient Synergy Map")
        for syn in report["synergy_map"]:
            st.success(
                f"**{' + '.join(syn['ingredients'])}** → {syn['pain_point']}: "
                f"{syn['description']}"
            )



# ── Reports index ─────────────────────────────────────────────────────────────
def _load_reports_index() -> list[dict]:
    """Load the reports index JSON file."""
    if REPORTS_INDEX.exists():
        try:
            return json.loads(REPORTS_INDEX.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_reports_index(index: list[dict]) -> None:
    """Save the reports index JSON file."""
    REPORTS_INDEX.write_text(
        json.dumps(index, indent=2, default=str), encoding="utf-8"
    )


def _add_to_reports_index(report: dict, pdf_path: str) -> None:
    """Add a completed report to the reports index."""
    from datetime import datetime

    index = _load_reports_index()

    # Copy PDF to reports directory
    pdf_in_reports = ""
    if pdf_path:
        src = Path(pdf_path)
        if src.exists():
            dst = REPORTS_DIR / src.name
            if src != dst:
                dst.write_bytes(src.read_bytes())
            pdf_in_reports = str(dst)
        else:
            pdf_in_reports = pdf_path

    top_pain_points = [d["pain_point"] for d in report.get("top_deep_dives", [])]

    entry = {
        "id": datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
        "product_name": report.get("product", {}).get("name", "Unknown"),
        "brand_name": report.get("product", {}).get("brand", ""),
        "date": datetime.utcnow().isoformat(),
        "pain_points_count": len(report.get("all_pain_points", [])),
        "top_pain_points": top_pain_points,
        "pdf_path": pdf_in_reports,
    }

    index.insert(0, entry)
    _save_reports_index(index)


def _generate_pdf_for_report(entry: dict) -> None:
    """Generate a PDF for a report entry that doesn't have one yet."""
    report_id = entry.get("id", "")
    json_candidates = list(OUTPUT_DIR.glob(f"*{report_id}*.json")) + list(
        REPORTS_DIR.glob(f"*{report_id}*.json")
    )
    if not json_candidates:
        slug = entry.get("product_name", "").replace(" ", "_")[:30]
        json_candidates = list(OUTPUT_DIR.glob(f"*{slug}*.json"))

    if not json_candidates:
        st.error("Could not find source report JSON to generate PDF.")
        return

    try:
        report_data = json.loads(json_candidates[0].read_text(encoding="utf-8"))
        config = _load_config()
        from analyzer.report_generator import ReportGenerator
        reporter = ReportGenerator(config)
        pdf_path = reporter.generate_pdf(report_data)
        if pdf_path:
            idx = _load_reports_index()
            for e in idx:
                if e.get("id") == entry.get("id"):
                    e["pdf_path"] = str(pdf_path)
                    break
            _save_reports_index(idx)
            st.success(f"PDF generated: {pdf_path.name}")
        else:
            st.error("PDF generation failed. Check Playwright is installed.")
    except Exception as e:
        st.error(f"PDF generation error: {e}")


def _show_reports_tab():
    """Display the Reports tab content."""
    from datetime import datetime

    st.markdown("## Reports")
    st.markdown("All generated analysis reports.")

    index = _load_reports_index()

    # Also scan for orphan PDFs not in index
    existing_pdfs = {e["pdf_path"] for e in index}
    for pdf_file in sorted(REPORTS_DIR.glob("*.pdf"), reverse=True):
        if str(pdf_file) not in existing_pdfs:
            index.append({
                "id": pdf_file.stem,
                "product_name": pdf_file.stem.replace("_", " "),
                "brand_name": "",
                "date": datetime.fromtimestamp(pdf_file.stat().st_mtime).isoformat(),
                "pain_points_count": 0,
                "top_pain_points": [],
                "pdf_path": str(pdf_file),
            })

    # Sort by date descending
    index.sort(key=lambda x: x.get("date", ""), reverse=True)

    if not index:
        st.info("No reports generated yet. Run an analysis to create your first report.")
        return

    for i, entry in enumerate(index):
        pdf_path_str = entry.get("pdf_path", "")
        pdf_path = Path(pdf_path_str) if pdf_path_str else None
        pdf_exists = pdf_path is not None and pdf_path.is_file()

        html_path = None
        if pdf_path:
            candidate = pdf_path.with_suffix(".html")
            if candidate.is_file():
                html_path = candidate

        try:
            dt = datetime.fromisoformat(entry["date"])
            date_str = dt.strftime("%B %d, %Y at %H:%M")
        except (ValueError, KeyError):
            date_str = entry.get("date", "Unknown date")

        with st.container():
            col1, col2, col3, col4 = st.columns([4, 1, 1, 1])

            with col1:
                product = entry.get("product_name", "Unknown")
                brand = entry.get("brand_name", "")
                brand_str = f" — {brand}" if brand else ""
                st.markdown(f"**{product}**{brand_str}")
                st.caption(f"{date_str} | {entry.get('pain_points_count', 0)} pain points")

                top_pps = entry.get("top_pain_points", [])
                if top_pps:
                    st.markdown(
                        "Top 3: " + ", ".join(f"**{pp}**" for pp in top_pps[:3])
                    )

            with col2:
                if pdf_exists:
                    if st.button("Preview", key=f"preview_{i}", use_container_width=True):
                        st.session_state[f"show_preview_{i}"] = not st.session_state.get(f"show_preview_{i}", False)

            with col3:
                if pdf_exists:
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            label="Download",
                            data=f.read(),
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            key=f"dl_{i}",
                            use_container_width=True,
                        )
                else:
                    if st.button("Generate PDF", key=f"gen_{i}", use_container_width=True):
                        _generate_pdf_for_report(entry)
                        st.rerun()

            with col4:
                if st.button("Delete", key=f"del_{i}", use_container_width=True):
                    if pdf_exists:
                        pdf_path.unlink(missing_ok=True)
                    if html_path and html_path.is_file():
                        html_path.unlink(missing_ok=True)
                    updated = [
                        e for e in _load_reports_index()
                        if e.get("id") != entry.get("id")
                    ]
                    _save_reports_index(updated)
                    st.rerun()

            # Inline PDF preview
            if st.session_state.get(f"show_preview_{i}", False):
                if html_path and html_path.is_file():
                    html_content = html_path.read_text(encoding="utf-8")
                    import base64
                    b64_html = base64.b64encode(html_content.encode("utf-8")).decode()
                    st.markdown(
                        f'<iframe src="data:text/html;base64,{b64_html}" '
                        f'width="100%" height="800" style="border:1px solid #ddd;'
                        f'border-radius:6px;"></iframe>',
                        unsafe_allow_html=True,
                    )
                elif pdf_exists:
                    import base64
                    pdf_bytes = pdf_path.read_bytes()
                    b64_pdf = base64.b64encode(pdf_bytes).decode()
                    st.markdown(
                        f'<iframe src="data:application/pdf;base64,{b64_pdf}" '
                        f'width="100%" height="800" style="border:1px solid #ddd;'
                        f'border-radius:6px;"></iframe>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("No preview available. Generate the PDF first.")

            st.markdown("---")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    st.set_page_config(
        page_title="Pain Point Analyzer",
        page_icon="🔬",
        layout="wide",
    )

    if not _check_auth():
        return

    st.title("Pain Point Analyzer")

    # Inject global CSS at app top — BEFORE any dynamic content renders
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY environment variable is not set. "
                 "Set it before running: `export ANTHROPIC_API_KEY=sk-ant-...`")
        return

    config = _load_config()

    # Initialize session state
    if "report" not in st.session_state:
        st.session_state["report"] = None
    if "running" not in st.session_state:
        st.session_state["running"] = False

    # ── Sidebar: Cache management ─────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Settings")

        # Cache management
        from analyzer.trends_validator import CACHE_FILE, clear_cache, _load_cache
        cache = _load_cache()
        cache_count = len(cache)
        st.markdown(f"**Keyword Cache:** {cache_count} entries")
        if cache_count > 0:
            if st.button("Clear Cache", use_container_width=True):
                clear_cache()
                st.success("Cache cleared!")
                st.rerun()

        st.markdown("---")

        # Include single-ingredient checkbox
        include_single = st.checkbox(
            "Include single-ingredient pain points (slower)",
            value=False,
            key="include_single_ingredient",
        )

        st.markdown("---")
        st.markdown(
            "**Time Estimates:**\n"
            "- Step 1 (Ingredients): ~30s\n"
            "- Step 2 (Pain Points): ~45s\n"
            "- Step 3 (Meta Ads): ~20s/each\n"
            "- Step 4 (Science): ~60s/each\n"
            "- Step 5 (Positioning): ~90s/each\n"
            "- Step 6 (Report): ~30s\n\n"
            "Estimated total: ~8 minutes"
        )

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab_analyzer, tab_reports = st.tabs(["Analyzer", "Reports"])

    with tab_reports:
        _show_reports_tab()

    with tab_analyzer:
        st.markdown(
            "Analyze any supplement product page to discover the top pain points, "
            "validate demand via Meta Ad Library, run scientific research, and build "
            "root cause + mechanism positioning."
        )

        # Time estimate display
        st.markdown(
            '<div style="background:#e3f2fd;border-radius:6px;padding:8px 16px;'
            'margin-bottom:12px;color:#1a1a1a;font-size:0.9em;">'
            'Estimated time: ~8 minutes '
            '<span style="color:#666;">(faster with cached data)</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ── Input modes ─────────────────────────────────────────────────────
        input_mode = st.radio(
            "Input method",
            ["Scrape from URL", "Paste Ingredients"],
            horizontal=True,
        )

        if input_mode == "Scrape from URL":
            with st.form("analyze_form"):
                url = st.text_input(
                    "Product Page URL",
                    placeholder="https://www.example.com/products/supplement",
                )
                submitted = st.form_submit_button("Analyze", use_container_width=True)

            # Manual ingredient input section
            if st.session_state.get("needs_manual_input"):
                extraction = st.session_state.get("extraction")
                st.warning(
                    f"Auto-extraction found only {len(extraction.ingredients)} "
                    "ingredient(s). Please provide ingredients manually."
                )

                if extraction.ingredients:
                    st.markdown("**Found so far:**")
                    for ing in extraction.ingredients:
                        st.markdown(f"- {ing.name}")

                manual_text = st.text_area(
                    "Paste ingredient list here",
                    height=150,
                    placeholder="Aged Garlic Extract 600mg\nS-allylcysteine 1.2mg\n...",
                )
                if st.button("Submit Text"):
                    from analyzer.ingredient_extractor import (
                        IngredientExtractor,
                        merge_ingredients,
                    )
                    extractor = IngredientExtractor(config)
                    manual_ings = asyncio.run(extractor.extract_from_text(manual_text))
                    extraction.ingredients = merge_ingredients(
                        extraction.ingredients, manual_ings
                    )
                    st.session_state["needs_manual_input"] = False
                    st.session_state["pipeline_paused"] = False
                    st.rerun()

            # Resume pipeline after manual input
            if (
                st.session_state.get("pipeline_paused") is False
                and st.session_state.get("extraction")
                and not st.session_state.get("report")
            ):
                extraction = st.session_state["extraction"]
                url = st.session_state.get("last_url", "")
                status = st.empty()

                def update(msg, pct=None):
                    if pct is not None:
                        status.progress(pct, text=msg)
                    else:
                        status.text(msg)

                report = asyncio.run(
                    _run_remaining_pipeline(extraction, config, url, update)
                )
                if report:
                    _add_to_reports_index(report, report.get("_pdf_path") or "")
                    st.session_state["report"] = report
                    st.rerun()

            # Run URL-based pipeline
            if submitted and url:
                st.session_state["report"] = None
                st.session_state["needs_manual_input"] = False
                st.session_state["pipeline_paused"] = None
                st.session_state["last_url"] = url

                status = st.empty()
                report = asyncio.run(_run_pipeline(url, config, status))

                if report:
                    _add_to_reports_index(report, report.get("_pdf_path") or "")
                    st.session_state["report"] = report
                    st.rerun()

        else:  # Paste Ingredients
            with st.form("text_form"):
                product_name = st.text_input(
                    "Product Name",
                    placeholder="Aged Garlic Extract 7500mg",
                )
                brand_name = st.text_input(
                    "Brand Name",
                    placeholder="Elare",
                )
                ingredient_text = st.text_area(
                    "Paste ingredient list",
                    height=200,
                    placeholder=(
                        "Aged Garlic Extract (bulb) 7500mg\n"
                        "S-allylcysteine (SAC) 3.6mg\n"
                        "Allicin 5mg\n"
                        "..."
                    ),
                )
                text_submitted = st.form_submit_button(
                    "Analyze", use_container_width=True
                )

            if text_submitted and ingredient_text.strip():
                st.session_state["report"] = None
                status = st.empty()
                report = asyncio.run(
                    _run_pipeline_from_text(
                        product_name or "Unknown Product",
                        brand_name or "",
                        ingredient_text,
                        config,
                        status,
                    )
                )
                if report:
                    _add_to_reports_index(report, report.get("_pdf_path") or "")
                    st.session_state["report"] = report
                    st.rerun()

        # Show results
        if st.session_state.get("report"):
            _show_results(st.session_state["report"])


if __name__ == "__main__":
    main()
