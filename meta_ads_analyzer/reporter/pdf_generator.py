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

from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)

# Directory containing Jinja2 templates
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Default output directory
_DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "reports"


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
