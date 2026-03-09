"""PDF report generator for strategic compare outputs.

Converts strategic_market_map.json + strategic_loophole_doc.json into a
polished PDF using Jinja2 HTML templates rendered by Playwright.

Usage:
    from meta_ads_analyzer.reporter.pdf_generator import generate_pdf

    pdf_path = await generate_pdf(
        loophole_doc_path=Path("output/reports/compare_.../strategic_loophole_doc.json"),
        market_map_path=Path("output/reports/compare_.../strategic_market_map.json"),
        output_dir=Path("~/Desktop/reports"),
    )
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

import os

from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

# Directory containing Jinja2 templates
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Default output directory — overridable via PDF_OUTPUT_DIR env var
_DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("PDF_OUTPUT_DIR", str(Path.home() / "Desktop" / "reports"))
)


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:60]


def _load_json(path: Path) -> dict:
    """Load and parse a JSON file."""
    with open(path) as f:
        return json.load(f)


def _render_html(loophole_data: dict, market_map_data: Optional[dict]) -> str:
    """Render the HTML report using Jinja2 template."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("strategic_report.html")

    # Format the generated date
    generated_at = loophole_data.get("meta", {}).get("generated_at", "")
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            generated_date = dt.strftime("%B %d, %Y")
        except (ValueError, AttributeError):
            generated_date = generated_at[:10]
    else:
        generated_date = datetime.now().strftime("%B %d, %Y")

    return template.render(
        loophole=loophole_data,
        market_map=market_map_data,
        generated_date=generated_date,
    )


async def generate_pdf(
    loophole_doc_path: Path,
    market_map_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    output_filename: Optional[str] = None,
) -> Path:
    """Generate a PDF report from compare output JSON files.

    Args:
        loophole_doc_path: Path to strategic_loophole_doc.json
        market_map_path: Path to strategic_market_map.json (optional, enriches report)
        output_dir: Directory to save the PDF (defaults to ~/Desktop/reports/)
        output_filename: Override the output filename (without extension)

    Returns:
        Path to the generated PDF file

    Raises:
        FileNotFoundError: If loophole_doc_path doesn't exist
        RuntimeError: If PDF generation fails
    """
    from playwright.async_api import async_playwright

    if not loophole_doc_path.exists():
        raise FileNotFoundError(f"Loophole doc not found: {loophole_doc_path}")

    # Load data
    loophole_data = _load_json(loophole_doc_path)

    market_map_data = None
    if market_map_path and market_map_path.exists():
        market_map_data = _load_json(market_map_path)
        logger.info(f"Loaded market map: {market_map_path.name}")
    else:
        # Try to find market map in same directory
        sibling = loophole_doc_path.parent / "strategic_market_map.json"
        if sibling.exists():
            market_map_data = _load_json(sibling)
            logger.info(f"Auto-loaded market map from same directory")

    # Build output path
    if output_dir is None:
        output_dir = _DEFAULT_OUTPUT_DIR
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        keyword = loophole_data.get("meta", {}).get("keyword", "report")
        date_str = datetime.now().strftime("%Y%m%d")
        output_filename = f"{_slugify(keyword)}_{date_str}_strategic_analysis"

    pdf_path = output_dir / f"{output_filename}.pdf"

    # Render HTML
    logger.info("Rendering HTML template...")
    html_content = _render_html(loophole_data, market_map_data)

    # Write HTML to temp file for Playwright
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    logger.info("Generating PDF with Playwright...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # Load the HTML file
            await page.goto(f"file://{tmp_path}", wait_until="networkidle")

            # Generate PDF
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={
                    "top": "18mm",
                    "bottom": "18mm",
                    "left": "16mm",
                    "right": "16mm",
                },
            )

            await browser.close()

    except Exception as e:
        raise RuntimeError(f"PDF generation failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(f"PDF saved: {pdf_path}")
    return pdf_path


def generate_pdf_sync(
    loophole_doc_path: Path,
    market_map_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    output_filename: Optional[str] = None,
) -> Path:
    """Synchronous wrapper around generate_pdf for use in sync contexts."""
    import asyncio

    return asyncio.run(
        generate_pdf(
            loophole_doc_path=loophole_doc_path,
            market_map_path=market_map_path,
            output_dir=output_dir,
            output_filename=output_filename,
        )
    )



def _aggregate_market_patterns(brands: list[dict]) -> dict:
    """Aggregate patterns across all brand reports for the market-level section.

    Returns a dict with:
      - top_root_causes: list of {root_cause, frequency, scientific_explanation, brands}
      - top_mechanisms: list of {mechanism, frequency, scientific_explanation, brands}
      - top_pain_points: list of {pain_point, frequency, brands}
      - what_nobody_does_well: deduplicated list across all brands
      - top_avatars: aggregated cross-brand avatar profiles
    """
    from collections import defaultdict

    rc_map: dict[str, dict] = defaultdict(lambda: {"frequency": 0, "brands": [], "scientific_explanation": "", "upstream_gap": ""})
    mech_map: dict[str, dict] = defaultdict(lambda: {"frequency": 0, "brands": [], "scientific_explanation": "", "ingredients_involved": []})
    pain_map: dict[str, dict] = defaultdict(lambda: {"frequency": 0, "brands": [], "symptoms": []})
    nobody_does_well: list[str] = []

    for brand in brands:
        bname = brand.get("brand_name", "Unknown")

        for rc in brand.get("root_causes", []):
            key = (rc.get("root_cause") or "")[:80]
            if not key or key.lower() in ("none stated", "none stated in ad"):
                continue
            rc_map[key]["frequency"] += rc.get("frequency", 1)
            if bname not in rc_map[key]["brands"]:
                rc_map[key]["brands"].append(bname)
            if not rc_map[key]["scientific_explanation"] and rc.get("scientific_explanation"):
                rc_map[key]["scientific_explanation"] = rc["scientific_explanation"]
            if not rc_map[key]["upstream_gap"] and rc.get("upstream_gap"):
                rc_map[key]["upstream_gap"] = rc["upstream_gap"]

        for mech in brand.get("mechanisms", []):
            key = (mech.get("mechanism") or "")[:80]
            if not key or key.lower() in ("none stated", "none stated in ad"):
                continue
            mech_map[key]["frequency"] += mech.get("frequency", 1)
            if bname not in mech_map[key]["brands"]:
                mech_map[key]["brands"].append(bname)
            if not mech_map[key]["scientific_explanation"] and mech.get("scientific_explanation"):
                mech_map[key]["scientific_explanation"] = mech["scientific_explanation"]
            for ing in mech.get("ingredients_involved", []):
                if ing and ing not in mech_map[key]["ingredients_involved"]:
                    mech_map[key]["ingredients_involved"].append(ing)

        for pp in brand.get("pain_points", []):
            key = (pp.get("pain_point") or "")[:80]
            if not key:
                continue
            pain_map[key]["frequency"] += pp.get("frequency", 1)
            if bname not in pain_map[key]["brands"]:
                pain_map[key]["brands"].append(bname)
            for sym in pp.get("symptoms", []):
                if sym and sym not in pain_map[key]["symptoms"]:
                    pain_map[key]["symptoms"].append(sym)

        for item in brand.get("what_nobody_does_well", []):
            if item and item not in nobody_does_well:
                nobody_does_well.append(item)

    top_root_causes = sorted(
        [{"root_cause": k, **v} for k, v in rc_map.items()],
        key=lambda x: (len(x["brands"]), x["frequency"]),
        reverse=True,
    )[:6]

    top_mechanisms = sorted(
        [{"mechanism": k, **v} for k, v in mech_map.items()],
        key=lambda x: (len(x["brands"]), x["frequency"]),
        reverse=True,
    )[:6]

    top_pain_points = sorted(
        [{"pain_point": k, **v} for k, v in pain_map.items()],
        key=lambda x: (len(x["brands"]), x["frequency"]),
        reverse=True,
    )[:8]

    return {
        "top_root_causes": top_root_causes,
        "top_mechanisms": top_mechanisms,
        "top_pain_points": top_pain_points,
        "what_nobody_does_well": nobody_does_well,
    }


def _build_cross_category_gap(brands: list[dict]) -> list[str]:
    """Aggregate 'what_nobody_does_well' items across all cross-category brands."""
    seen: set[str] = set()
    items: list[str] = []
    for b in brands:
        for item in b.get("what_nobody_does_well", []):
            if item and item not in seen:
                seen.add(item)
                items.append(item)
    return items[:8]


async def generate_market_pdf(
    market_dir: Path,
    keyword: str,
    output_dir: Optional[Path] = None,
    blue_ocean_framing: bool = False,
) -> Path:
    """Generate a standalone PDF from a market run's brand reports.

    Reads all brand_report_*.json files in market_dir and renders them
    into a single multi-brand analysis PDF using the market_report.html template.

    Args:
        market_dir: Directory containing brand_report_*.json files
        keyword: The market research keyword
        output_dir: Directory to save the PDF (defaults to ~/Desktop/reports/)

    Returns:
        Path to the generated PDF file
    """
    from playwright.async_api import async_playwright

    market_dir = Path(market_dir)
    if not market_dir.exists():
        raise FileNotFoundError(f"Market directory not found: {market_dir}")

    # Glob brand report files, sorted by mtime
    report_files = sorted(
        market_dir.glob("brand_report_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not report_files:
        raise FileNotFoundError(f"No brand_report_*.json files found in {market_dir}")

    # Extract brand data from each report
    brands = []
    for report_file in report_files:
        data = _load_json(report_file)
        pr = data.get("pattern_report", {})

        what_not_to_do_raw = pr.get("what_not_to_do", [])
        # Handle both list and string formats
        if isinstance(what_not_to_do_raw, list):
            what_not_to_do_list = what_not_to_do_raw
            what_not_to_do_str = []
        else:
            what_not_to_do_list = []
            what_not_to_do_str = what_not_to_do_raw

        brands.append({
            "brand_name": data.get("advertiser", {}).get("page_name", "Unknown"),
            "ad_count": data.get("advertiser", {}).get("ad_count", 0),
            "all_page_names": data.get("advertiser", {}).get("all_page_names", []),
            "ads_analyzed": pr.get("total_ads_analyzed", 0),
            "competitive_verdict": pr.get("competitive_verdict", ""),
            "root_causes": pr.get("root_cause_patterns", [])[:4],
            "mechanisms": pr.get("mechanism_patterns", [])[:4],
            "pain_points": pr.get("common_pain_points", [])[:5],
            "hook_types": pr.get("hook_patterns", [])[:5],
            "loopholes": pr.get("loopholes", [])[:5],
            "key_insights": pr.get("key_insights", []),
            "recommendations": pr.get("recommendations", []),
            "what_not_to_do": what_not_to_do_str,
            "what_not_to_do_list": what_not_to_do_list,
            # New deep analysis fields
            "avatars": pr.get("avatars", [])[:4],
            "concepts": pr.get("concepts", [])[:4],
            "what_nobody_does_well": pr.get("what_nobody_does_well", []),
            "creative_format_distribution": pr.get("creative_format_distribution", {}),
            "executive_summary": pr.get("executive_summary", ""),
            # Cross-category fields
            "cross_category": data.get("cross_category", False),
            "cross_category_product_type": data.get("cross_category_product_type", ""),
        })

    # Build output path
    if output_dir is None:
        output_dir = _DEFAULT_OUTPUT_DIR
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%B %d, %Y")
    date_slug = datetime.now().strftime("%Y%m%d")
    keyword_slug = _slugify(keyword)
    slug = "blue_ocean_cross_category" if blue_ocean_framing else "market_analysis"
    pdf_path = output_dir / f"{keyword_slug}_{date_slug}_{slug}.pdf"

    # Aggregate market-level patterns across all brands
    market_patterns = _aggregate_market_patterns(brands)

    # Flatten loopholes from all brands into a single ranked list for Section C
    all_loopholes = []
    for brand in brands:
        for lh in brand.get("loopholes", []):
            entry = dict(lh) if isinstance(lh, dict) else {}
            entry["brand"] = brand.get("brand_name", "Unknown")
            all_loopholes.append(entry)
    # Sort by score descending, fallback to 0
    all_loopholes.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)

    # Build cross-category gap list for blue ocean framing
    cross_category_market_gap = _build_cross_category_gap(brands) if blue_ocean_framing else []

    # Render HTML template
    logger.info(f"Rendering market report HTML for {len(brands)} brands...")
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("market_report.html")
    html_content = template.render(
        keyword=keyword,
        date_str=date_str,
        brands=brands,
        market_patterns=market_patterns,
        all_loopholes=all_loopholes,
        market_dir_name=market_dir.name,
        blue_ocean_framing=blue_ocean_framing,
        cross_category_market_gap=cross_category_market_gap,
    )

    # Write to temp file and render with Playwright
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    logger.info("Generating market PDF with Playwright...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(f"file://{tmp_path}", wait_until="networkidle")
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={
                    "top": "18mm",
                    "bottom": "18mm",
                    "left": "16mm",
                    "right": "16mm",
                },
            )
            await browser.close()
    except Exception as e:
        raise RuntimeError(f"Market PDF generation failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(f"Market PDF saved: {pdf_path}")
    return pdf_path


def generate_market_pdf_sync(
    market_dir: Path,
    keyword: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """Synchronous wrapper around generate_market_pdf for use in sync contexts."""
    import asyncio

    return asyncio.run(
        generate_market_pdf(
            market_dir=market_dir,
            keyword=keyword,
            output_dir=output_dir,
        )
    )


async def generate_blue_ocean_pdf(
    blue_ocean_doc,  # BlueOceanResult
    output_dir: Optional[Path] = None,
    output_filename: Optional[str] = None,
) -> Path:
    """Generate a PDF report from a BlueOceanResult.

    Args:
        blue_ocean_doc: BlueOceanResult instance
        output_dir: Directory to save the PDF (defaults to ~/Desktop/reports/)
        output_filename: Override the output filename (without extension)

    Returns:
        Path to the generated PDF file
    """
    from playwright.async_api import async_playwright

    if output_dir is None:
        output_dir = _DEFAULT_OUTPUT_DIR
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        keyword = blue_ocean_doc.keyword
        date_str = datetime.now().strftime("%Y%m%d")
        output_filename = f"{_slugify(keyword)}_{date_str}_blue_ocean"

    pdf_path = output_dir / f"{output_filename}.pdf"

    # Render HTML
    logger.info("Rendering blue ocean HTML template...")
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("blue_ocean_report.html")
    html_content = template.render(
        report=blue_ocean_doc,
        generated_date=datetime.now().strftime("%B %d, %Y"),
    )

    # Write to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    logger.info("Generating blue ocean PDF with Playwright...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(f"file://{tmp_path}", wait_until="networkidle")
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "14mm", "bottom": "14mm", "left": "15mm", "right": "15mm"},
            )
            await browser.close()
    except Exception as e:
        raise RuntimeError(f"Blue ocean PDF generation failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(f"Blue ocean PDF saved: {pdf_path}")
    return pdf_path


def generate_blue_ocean_pdf_sync(
    blue_ocean_doc,
    output_dir: Optional[Path] = None,
    output_filename: Optional[str] = None,
) -> Path:
    """Synchronous wrapper around generate_blue_ocean_pdf."""
    import asyncio

    return asyncio.run(
        generate_blue_ocean_pdf(
            blue_ocean_doc=blue_ocean_doc,
            output_dir=output_dir,
            output_filename=output_filename,
        )
    )


async def generate_brand_pdf(
    brand_report,  # BrandReport
    output_dir: Optional[Path] = None,
    output_filename: Optional[str] = None,
) -> Path:
    """Generate a PDF report from a BrandReport.

    Args:
        brand_report: BrandReport instance
        output_dir: Directory to save the PDF (defaults to ~/Desktop/reports/)
        output_filename: Override the output filename (without extension)

    Returns:
        Path to the generated PDF file
    """
    from playwright.async_api import async_playwright

    if output_dir is None:
        output_dir = _DEFAULT_OUTPUT_DIR
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    pr = brand_report.pattern_report

    if output_filename is None:
        keyword_slug = _slugify(brand_report.keyword or "brand")
        brand_slug = _slugify(brand_report.advertiser.page_name)
        date_str = datetime.now().strftime("%Y%m%d")
        output_filename = f"{brand_slug}_{keyword_slug}_{date_str}_brand_analysis"

    pdf_path = output_dir / f"{output_filename}.pdf"

    # Build what_not_to_do in both formats
    what_not_to_do_raw = pr.what_not_to_do or []
    if isinstance(what_not_to_do_raw, list):
        what_not_to_do_list = what_not_to_do_raw
        what_not_to_do_str = []
    else:
        what_not_to_do_list = []
        what_not_to_do_str = what_not_to_do_raw

    brand = {
        "brand_name": brand_report.advertiser.page_name,
        "ad_count": brand_report.advertiser.ad_count,
        "all_page_names": brand_report.advertiser.all_page_names or [],
        "ads_analyzed": pr.total_ads_analyzed or 0,
        "competitive_verdict": pr.competitive_verdict or "",
        "executive_summary": pr.executive_summary or "",
        "key_insights": pr.key_insights or [],
        "root_causes": (pr.root_cause_patterns or [])[:4],
        "mechanisms": (pr.mechanism_patterns or [])[:4],
        "pain_points": (pr.common_pain_points or [])[:5],
        "hook_types": (pr.hook_patterns or [])[:5],
        "loopholes": (pr.loopholes or [])[:6],
        "avatars": (pr.avatars or [])[:4],
        "concepts": (pr.concepts or [])[:4],
        "what_nobody_does_well": pr.what_nobody_does_well or [],
        "recommendations": pr.recommendations or [],
        "what_not_to_do": what_not_to_do_str,
        "what_not_to_do_list": what_not_to_do_list,
    }

    # Render HTML template
    logger.info(f"Rendering brand report HTML for {brand['brand_name']}...")
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("brand_report.html")
    html_content = template.render(
        brand=brand,
        keyword=brand_report.keyword or "",
        generated_date=datetime.now().strftime("%B %d, %Y"),
    )

    # Write to temp file and render with Playwright
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    logger.info("Generating brand PDF with Playwright...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(f"file://{tmp_path}", wait_until="networkidle")
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={
                    "top": "18mm",
                    "bottom": "18mm",
                    "left": "16mm",
                    "right": "16mm",
                },
            )
            await browser.close()
    except Exception as e:
        raise RuntimeError(f"Brand PDF generation failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(f"Brand PDF saved: {pdf_path}")
    return pdf_path


def auto_generate_pdf_for_compare(
    compare_output_dir: Path,
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Find and convert compare outputs in a directory to PDF.

    Looks for strategic_loophole_doc.json and strategic_market_map.json
    in the given directory and generates a PDF report.

    Args:
        compare_output_dir: Directory containing compare output JSONs
        output_dir: Where to save the PDF (defaults to ~/Desktop/reports/)

    Returns:
        Path to generated PDF, or None if generation failed
    """
    loophole_path = compare_output_dir / "strategic_loophole_doc.json"
    market_map_path = compare_output_dir / "strategic_market_map.json"

    if not loophole_path.exists():
        logger.warning(f"No loophole doc found in {compare_output_dir}")
        return None

    try:
        pdf_path = generate_pdf_sync(
            loophole_doc_path=loophole_path,
            market_map_path=market_map_path if market_map_path.exists() else None,
            output_dir=output_dir,
        )
        return pdf_path
    except Exception as e:
        logger.error(f"PDF generation failed for {compare_output_dir}: {e}")
        return None
