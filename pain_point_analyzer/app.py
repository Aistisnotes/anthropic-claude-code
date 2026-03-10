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


def _tier_badge_inline(tier: int) -> tuple[str, str]:
    """Return (tier_label, inline_style) for a tier badge."""
    _base = "padding: 4px 12px; border-radius: 4px; font-weight: bold; display: inline-block;"
    styles = {
        0: ("UNKNOWN", f"background-color: #6b7280; color: #ffffff; {_base}"),
        1: ("OPEN", f"background-color: #22c55e; color: #ffffff; {_base}"),
        2: ("SOLID", f"background-color: #eab308; color: #000000; {_base}"),
        3: ("SATURATED", f"background-color: #f97316; color: #ffffff; {_base}"),
        4: ("SUPER SATURATED", f"background-color: #ef4444; color: #ffffff; {_base}"),
    }
    return styles.get(tier, styles[0])


# ── Results display ────────────────────────────────────────────────────────────
def _show_results(report: dict):
    """Display the analysis results inline."""
    # Completion banner
    elapsed = report.get("_elapsed")
    if elapsed:
        st.success(f"Analysis complete in {_format_elapsed(elapsed)}")

    # Pipeline log (collapsed)
    log_entries = report.get("_pipeline_log", [])
    if log_entries:
        with st.expander("Pipeline Log (click to expand)", expanded=False):
            log_html = (
                '<div style="font-family: monospace; font-size: 0.85em; '
                'background: #262730; border: 1px solid #3d3d4d; border-radius: 6px; '
                'padding: 12px; max-height: 400px; overflow-y: auto;">'
            )
            for entry in log_entries:
                level = entry.get("level", "info")
                if "error" in entry.get("msg", "").lower() or level == "error":
                    color = "#ff6b6b"
                    weight = "bold"
                elif "cached" in entry.get("msg", "").lower():
                    color = "#888888"
                    weight = "normal"
                else:
                    color = "#fafafa"
                    weight = "normal"
                log_html += (
                    f'<div style="color: {color}; font-weight: {weight};">'
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
        """Render a single pain point card with inline styles (dark mode)."""
        tier = t.get("tier", 1)
        tier_label = t.get("tier_label", "OPEN")
        ad_count = t.get("best_score", 0)
        is_top = t.get("is_top", False)
        from_cache = t.get("from_cache", False)
        cache_date = t.get("cache_date", "")
        skipped = t.get("skipped", False)
        skip_reason = t.get("skip_reason", "")

        _, badge_style = _tier_badge_inline(tier)
        border_color = {
            1: "#22c55e", 2: "#eab308", 3: "#f97316", 4: "#ef4444"
        }.get(tier, "#6b7280")

        top_badge = (
            ' <span style="background-color: #1a73e8; color: #ffffff; '
            'font-size: 0.75em; padding: 2px 8px; border-radius: 10px; '
            'font-weight: bold;">TOP 3</span>'
            if is_top else ""
        )

        # Build ad display text
        if ad_count <= 0:
            if ad_count == -2:
                ad_display = (
                    '<span style="color: #ff6b6b; font-weight: bold;">'
                    'Could not retrieve</span> '
                    '<span style="color: #fafafa;">— try again later</span>'
                )
            else:
                ad_display = '<span style="color: #888888;">N/A</span>'
        else:
            if from_cache and cache_date:
                cache_tag = (
                    f' <span style="color: #888888; font-size: 0.85em;">'
                    f'(cached, checked {cache_date})</span>'
                )
            else:
                cache_tag = (
                    ' <span style="color: #888888; font-size: 0.85em;">'
                    '(fresh)</span>'
                )
            ad_display = (
                f'<span style="color: #fafafa;">{ad_count:,} active ads</span>'
                f'{cache_tag}'
            )

        # Keyword display
        kw_display = ""
        if ad_count > 0 and t.get("keywords"):
            kw_list = ", ".join(
                f'{kw["keyword"]} ({kw["score"]})' for kw in t.get("keywords", [])
            )
            kw_display = (
                f'<div style="font-size: 0.85em; color: #aaaaaa; margin-top: 2px;">'
                f'Keywords: {kw_list}</div>'
            )

        # Skip info
        skip_display = ""
        if skipped and skip_reason:
            skip_display = (
                f'<div style="font-size: 0.85em; color: #888888; margin-top: 2px;">'
                f'{skip_reason}</div>'
            )

        card_bg = "#1e1e2a" if skipped else "#262730"

        st.markdown(
            f'<div style="background: {card_bg}; padding: 12px 16px; '
            f'margin-bottom: 8px; border-radius: 0 6px 6px 0; '
            f'border-left: 5px solid {border_color};">'
            f'<strong style="color: #fafafa;">{t["pain_point"]}</strong>'
            f'{top_badge}<br>'
            f'<span style="{badge_style}">{tier_label}</span> '
            f'<span style="color: #fafafa;">— </span>'
            f'{ad_display}<br>'
            f'{kw_display}'
            f'{skip_display}'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Render validated pain points first
    for t in validated_trends:
        _render_pp_card(t)

    # Render skipped/unvalidated pain points at bottom in collapsed accordion
    if skipped_trends:
        with st.expander(
            f"Skipped Pain Points — single ingredient support ({len(skipped_trends)} items)",
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

        tier = dive.get("tier", 0)
        tier_label = dive.get("tier_label", "—")

        col1, col2, col3, col4 = st.columns(4)
        ad_score = dive.get('trend_score', 0)
        col1.metric("Active Ads", f"{ad_score:,}" if ad_score > 0 else "N/A")
        col2.metric("Tier", tier_label)
        if dive.get("science"):
            col3.metric("Evidence", dive["science"]["overall_evidence"].title())
        col4.metric("Ingredients", len(dive["supporting_ingredients"]))

        # Saturation note only in the deep dive (not in the list)
        if tier >= 3:
            note_color = "#ef4444" if tier == 4 else "#f97316"
            note_text = (
                "Super saturated — see Edge Angle below for differentiation strategy"
                if tier == 4
                else "Saturated — strong rootcause/mechanism required to stand out"
            )
            st.markdown(
                f'<p style="color: {note_color}; font-weight: bold; '
                f'font-size: 0.9em; margin-bottom: 4px;">{note_text}</p>',
                unsafe_allow_html=True,
            )

        # ── Science ───────────────────────────────────────────────────────
        if dive.get("science"):
            sci = dive["science"]
            with st.expander("Scientific Evidence", expanded=True):
                # 1. THE PATHWAY
                pathway_steps = sci.get("pathway_steps", [])
                if pathway_steps:
                    st.markdown("**The Pathway**")
                    pathway_html = '<div style="background: #262730; border: 1px solid #3d3d4d; border-radius: 6px; padding: 12px; margin-bottom: 12px;">'
                    for ps in pathway_steps:
                        step_num = ps.get("step_number", "")
                        desc = ps.get("description", "")
                        pathway_html += (
                            f'<div style="color: #fafafa; margin-bottom: 6px;">'
                            f'<span style="color: #1a73e8; font-weight: bold;">Step {step_num}:</span> '
                            f'{desc}</div>'
                        )
                    pathway_html += '</div>'
                    st.markdown(pathway_html, unsafe_allow_html=True)

                # 2. KEY STUDIES
                st.markdown("**Key Studies**")
                for ev in sci["ingredient_evidence"]:
                    st.markdown(
                        f"**{ev['ingredient']}** — "
                        f"Evidence: `{ev['strength']}`"
                    )
                    for s in ev.get("studies", []):
                        st.markdown(
                            f"- **Study:** {s['description']} | "
                            f"**Dose:** {s['dosage']} | "
                            f"**Duration:** {s['duration']} | "
                            f"**Result:** {s['effect_size']}"
                        )
                    if ev.get("optimal_dosage"):
                        st.markdown(f"  Optimal dosage: {ev['optimal_dosage']}")
                    if ev.get("contraindications"):
                        st.warning(
                            "Contraindications: "
                            + ", ".join(ev["contraindications"])
                        )

                # 3. ELI10
                eli10 = sci.get("eli10", "")
                if eli10:
                    st.markdown(
                        f'<div style="background: #1a2332; border-left: 4px solid #1a73e8; '
                        f'padding: 12px 16px; border-radius: 0 6px 6px 0; margin-top: 12px;">'
                        f'<strong style="color: #1a73e8;">Explain Like I\'m 10:</strong><br>'
                        f'<span style="color: #fafafa; font-style: italic;">{eli10}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                if sci.get("synergies"):
                    st.markdown("**Synergies:**")
                    for syn in sci["synergies"]:
                        st.success(
                            f"**{' + '.join(syn['ingredients'])}**: "
                            f"{syn['description']}"
                        )

        # ── Positioning ───────────────────────────────────────────────────
        if dive.get("positioning"):
            pos = dive["positioning"]
            with st.expander("Positioning & Avatars", expanded=True):
                # Mass Desire first
                if pos.get("mass_desire"):
                    st.markdown(
                        f'<div style="background: #1a2332; border: 1px solid #1a73e8; '
                        f'border-radius: 6px; padding: 16px; margin-bottom: 16px;">'
                        f'<strong style="color: #1a73e8; font-size: 0.85em;">MASS DESIRE</strong><br>'
                        f'<span style="color: #fafafa; font-size: 1.1em; font-weight: bold;">'
                        f'{pos["mass_desire"]}</span></div>',
                        unsafe_allow_html=True,
                    )

                # Avatar Profiles (CHANGE 3)
                avatar_profiles = pos.get("avatar_profiles", [])
                if avatar_profiles:
                    st.markdown("**Target Avatars**")
                    for idx, profile in enumerate(avatar_profiles, 1):
                        desc = profile.get("description", "") if isinstance(profile, dict) else str(profile)
                        st.markdown(
                            f'<div style="background: #262730; border-left: 3px solid #1a73e8; '
                            f'padding: 10px 14px; margin-bottom: 6px; border-radius: 0 4px 4px 0;">'
                            f'<span style="color: #1a73e8; font-weight: bold;">{idx}.</span> '
                            f'<span style="color: #fafafa;">{desc}</span></div>',
                            unsafe_allow_html=True,
                        )
                else:
                    # Fallback to legacy avatar
                    avatar = pos.get("avatar", {})
                    if avatar.get("narrative"):
                        st.markdown(f"**Avatar:** {avatar['narrative']}")

                # Daily Symptoms (CHANGE 7)
                if pos.get("daily_symptoms"):
                    st.markdown("**What They Experience Daily**")
                    symptoms_html = '<div style="background: #262730; border-radius: 6px; padding: 12px; margin-bottom: 12px;">'
                    for s in pos["daily_symptoms"]:
                        symptoms_html += (
                            f'<div style="color: #fafafa; margin-bottom: 4px; padding-left: 12px; '
                            f'border-left: 2px solid #f97316;">{s}</div>'
                        )
                    symptoms_html += '</div>'
                    st.markdown(symptoms_html, unsafe_allow_html=True)

                # Root Cause Chain
                st.markdown("**Root Cause Depth**")
                rc = pos["root_cause"]
                rc_html = (
                    f'<div style="background: #262730; border-radius: 6px; padding: 12px; margin-bottom: 12px;">'
                    f'<div style="color: #fafafa; margin-bottom: 8px;">'
                    f'<span style="color: #22c55e; font-weight: bold;">Surface:</span> {rc["surface"]}</div>'
                    f'<div style="color: #fafafa; margin-bottom: 8px;">'
                    f'<span style="color: #eab308; font-weight: bold;">Cellular:</span> {rc["cellular"]}</div>'
                    f'<div style="color: #fafafa;">'
                    f'<span style="color: #ef4444; font-weight: bold;">Molecular:</span> {rc["molecular"]}</div>'
                    f'</div>'
                )
                st.markdown(rc_html, unsafe_allow_html=True)

                st.markdown(f"**Mechanism:** {pos['mechanism']}")

                # Ingredient Pathways (CHANGE 6)
                pathways = pos.get("ingredient_pathways", [])
                if pathways:
                    st.markdown("**Ingredient Pathways**")
                    for pw in pathways:
                        chain = pw.get("chain", "")
                        if not chain:
                            chain = (
                                f"{pw.get('ingredient', '')} → "
                                f"{pw.get('root_cause', '')} → "
                                f"{pw.get('resolution', '')} → "
                                f"{pw.get('mass_desire', '')}"
                            )
                        st.markdown(
                            f'<div style="background: #1a2332; border-left: 4px solid #22c55e; '
                            f'padding: 10px 14px; margin-bottom: 6px; border-radius: 0 4px 4px 0; '
                            f'font-size: 0.95em;">'
                            f'<span style="color: #fafafa;">{chain}</span></div>',
                            unsafe_allow_html=True,
                        )

                # Multi-Layer Connection (CHANGE 8) — only for saturated
                multi_layer = pos.get("multi_layer")
                if multi_layer:
                    st.markdown(
                        '<div style="background: #2a1a1a; border: 1px solid #ef4444; '
                        'border-radius: 6px; padding: 16px; margin: 12px 0;">',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        '<span style="color: #ef4444; font-weight: bold; font-size: 1.05em;">'
                        'Edge Angle — Multi-Layer Connection</span>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="color: #fafafa; margin: 8px 0; font-weight: bold; '
                        f'font-size: 1em;">{multi_layer["full_chain"]}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="color: #cccccc; margin-bottom: 8px;">'
                        f'<strong style="color: #f97316;">Why this is new:</strong> '
                        f'{multi_layer["why_new_angle"]}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="color: #fafafa; background: #1a2332; '
                        f'padding: 10px; border-radius: 4px; margin-bottom: 8px; '
                        f'font-style: italic;">'
                        f'{multi_layer["new_hope_hook"]}</div>',
                        unsafe_allow_html=True,
                    )
                    ml_hooks = multi_layer.get("hooks", [])
                    if ml_hooks:
                        hooks_html = '<div style="margin-top: 8px;">'
                        for mh in ml_hooks:
                            hooks_html += (
                                f'<div style="color: #fafafa; margin-bottom: 4px; '
                                f'padding-left: 12px; border-left: 2px solid #ef4444;">'
                                f'"{mh}"</div>'
                            )
                        hooks_html += '</div>'
                        st.markdown(hooks_html, unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)

                # Hooks
                if pos.get("hooks"):
                    st.markdown("**Hook Examples**")
                    for h in pos["hooks"]:
                        st.markdown(f'> "{h}"')

        st.markdown("---")



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
                        f'width="100%" height="800" style="border:1px solid #3d3d4d;'
                        f'border-radius:6px;"></iframe>',
                        unsafe_allow_html=True,
                    )
                elif pdf_exists:
                    import base64
                    pdf_bytes = pdf_path.read_bytes()
                    b64_pdf = base64.b64encode(pdf_bytes).decode()
                    st.markdown(
                        f'<iframe src="data:application/pdf;base64,{b64_pdf}" '
                        f'width="100%" height="800" style="border:1px solid #3d3d4d;'
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
            '<div style="background:#1a2332;border-radius:6px;padding:8px 16px;'
            'margin-bottom:12px;color:#fafafa;font-size:0.9em;border:1px solid #3d3d4d;">'
            'Estimated time: ~8 minutes '
            '<span style="color:#888;">(faster with cached data)</span>'
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
