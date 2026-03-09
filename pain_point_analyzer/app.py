"""Pain Point Analyzer — Streamlit Web UI.

Takes a product page URL, extracts ingredients, discovers pain points,
validates with Google Trends, runs scientific research, and builds
root cause + mechanism positioning for the top 3 pain points.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from datetime import datetime
from pathlib import Path

import streamlit as st

# ── Project paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH = PROJECT_ROOT / "config" / "default.toml"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Add project root to path
sys.path.insert(0, str(PROJECT_ROOT.parent))


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


# ── Pipeline runner ────────────────────────────────────────────────────────────
async def _run_pipeline(url: str, config: dict, status_placeholder):
    """Run the full 6-step pipeline."""
    from pain_point_analyzer.analyzer.ingredient_extractor import IngredientExtractor

    progress_bar = status_placeholder.progress(0, text="Starting analysis...")

    def update(msg: str, pct: float | None = None):
        if pct is not None:
            progress_bar.progress(pct, text=msg)
        else:
            status_placeholder.text(msg)

    # Step 1: Extract ingredients
    update("Step 1/6: Extracting ingredients...", 0.05)
    extractor = IngredientExtractor(config)
    extraction = await extractor.extract(
        url, progress_cb=lambda m: update(f"Step 1/6: {m}", 0.10)
    )

    st.session_state["extraction"] = extraction

    if len(extraction.ingredients) < 3:
        st.session_state["needs_manual_input"] = True
        st.session_state["pipeline_paused"] = True
        update("Ingredient extraction needs review.", 0.15)
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
    from pain_point_analyzer.analyzer.ingredient_extractor import (
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
    from pain_point_analyzer.analyzer.pain_point_discovery import PainPointDiscovery
    from pain_point_analyzer.analyzer.trends_validator import TrendsValidator
    from pain_point_analyzer.analyzer.scientific_researcher import ScientificResearcher
    from pain_point_analyzer.analyzer.positioning_engine import PositioningEngine
    from pain_point_analyzer.analyzer.report_generator import ReportGenerator

    # Step 2: Discover pain points
    update("Step 2/6: Discovering pain points...", 0.20)
    discovery_engine = PainPointDiscovery(config)
    discovery = await discovery_engine.discover(
        extraction.ingredients,
        progress_cb=lambda m: update(f"Step 2/6: {m}", 0.30),
    )

    # Step 3: Google Trends validation
    update("Step 3/6: Validating with Google Trends...", 0.40)
    trends_engine = TrendsValidator(config)
    trends = await trends_engine.validate(
        discovery.pain_points,
        progress_cb=lambda m: update(f"Step 3/6: {m}", 0.50),
    )

    # Step 4: Scientific research
    update("Step 4/6: Running scientific research...", 0.55)
    researcher = ScientificResearcher(config)
    research = await researcher.research(
        trends.top_results,
        extraction.ingredients,
        progress_cb=lambda m: update(f"Step 4/6: {m}", 0.65),
    )

    # Step 5: Positioning
    update("Step 5/6: Building positioning...", 0.75)
    positioning_engine = PositioningEngine(config)
    positioning = await positioning_engine.build_positioning(
        trends.top_results,
        research.reports,
        extraction.ingredients,
        progress_cb=lambda m: update(f"Step 5/6: {m}", 0.85),
    )

    # Step 6: Generate report
    update("Step 6/6: Generating report...", 0.90)
    reporter = ReportGenerator(config)
    report = reporter.generate(
        extraction, discovery, trends, research, positioning, url
    )

    # Try PDF
    pdf_path = reporter.generate_pdf(report)
    report["_pdf_path"] = str(pdf_path) if pdf_path else None

    update("Analysis complete!", 1.0)
    return report


# ── Results display ────────────────────────────────────────────────────────────
def _show_results(report: dict):
    """Display the analysis results inline."""
    product = report["product"]

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

    # Trends
    st.markdown("### Google Trends Rankings")
    trends_data = []
    for t in report["trends"]:
        trends_data.append({
            "Pain Point": t["pain_point"],
            "Best Keyword": t["best_keyword"],
            "Score": t["best_score"],
            "Top 3": "Yes" if t["is_top"] else "",
        })
    st.dataframe(trends_data, use_container_width=True)

    # Top deep dives
    st.markdown("---")
    st.markdown("## Top Pain Points — Deep Dive")

    for i, dive in enumerate(report["top_deep_dives"]):
        st.markdown(f"### #{i+1}: {dive['pain_point']}")

        col1, col2, col3 = st.columns(3)
        col1.metric("Trend Score", dive["trend_score"])
        if dive.get("science"):
            col2.metric("Evidence", dive["science"]["overall_evidence"].title())
        col3.metric("Ingredients", len(dive["supporting_ingredients"]))

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
                st.markdown(
                    f"Age: {pos['avatar']['age']} | "
                    f"Gender: {pos['avatar']['gender']} | "
                    f"Lifestyle: {pos['avatar']['lifestyle']}"
                )
                if pos["avatar"].get("tried_before"):
                    st.markdown(
                        f"_Tried before:_ {', '.join(pos['avatar']['tried_before'])}"
                    )

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

    # Downloads
    st.markdown("### Downloads")
    col1, col2 = st.columns(2)

    # JSON download
    json_str = json.dumps(report, indent=2, default=str)
    col1.download_button(
        label="Download JSON Report",
        data=json_str,
        file_name=f"pain_point_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        use_container_width=True,
    )

    # PDF download
    pdf_path = report.get("_pdf_path")
    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            col2.download_button(
                label="Download PDF Report",
                data=f.read(),
                file_name=Path(pdf_path).name,
                mime="application/pdf",
                use_container_width=True,
            )


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Pain Point Analyzer",
        page_icon="🔬",
        layout="wide",
    )

    if not _check_auth():
        return

    st.title("Pain Point Analyzer")
    st.markdown(
        "Analyze any supplement product page to discover the top pain points "
        "by search volume, validate with scientific research, and build "
        "root cause + mechanism positioning."
    )

    config = _load_config()

    # Initialize session state
    if "report" not in st.session_state:
        st.session_state["report"] = None
    if "running" not in st.session_state:
        st.session_state["running"] = False

    # ── Input modes ─────────────────────────────────────────────────────────
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

        # Manual ingredient input section (shown when auto-extraction finds too few)
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
                from pain_point_analyzer.analyzer.ingredient_extractor import (
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
                st.session_state["report"] = report
                st.rerun()

    # Show results
    if st.session_state.get("report"):
        _show_results(st.session_state["report"])


if __name__ == "__main__":
    main()
