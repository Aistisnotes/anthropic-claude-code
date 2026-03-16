"""PDF report generator for creative feedback loop.

Uses Jinja2 + async Playwright for HTML → PDF conversion.
Dark theme matching the UI design.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:60]


DIMENSION_LABELS = {
    "pain_point": "Pain Points",
    "symptoms": "Symptoms",
    "root_cause_depth": "Root Cause Depth",
    "root_cause_chain": "Root Cause Chain",
    "mechanism_ump": "Mechanisms — UMP",
    "mechanism_ums": "Mechanisms — UMS",
    "ad_format": "Ad Formats",
    "avatar": "Avatars",
    "awareness_level": "Awareness Levels",
    "lead_type": "Lead Types",
    "hook_type": "Hook Patterns",
    "emotional_triggers": "Emotional Triggers",
    "language_patterns": "Language Patterns",
}


def _prepare_tables(dashboard_data: dict) -> list[tuple[str, str, list]]:
    """Convert dashboard_data dict to template-friendly list of tuples."""
    result = []
    for dim_key, rows in dashboard_data.items():
        label = DIMENSION_LABELS.get(dim_key, dim_key)
        result.append((dim_key, label, rows))
    return result


def _build_comparison_data(
    current_data: dict[str, list[dict]],
    previous_data: dict[str, list[dict]],
) -> list[dict]:
    """Build comparison data for template."""
    changes = []
    for dim_key, current_rows in current_data.items():
        prev_rows = previous_data.get(dim_key, [])
        prev_by_value = {r["value"]: r for r in prev_rows}

        for row in current_rows:
            val = row["value"]
            prev = prev_by_value.get(val)
            if prev:
                pct_change = row["pct_winners"] - prev["pct_winners"]
                if abs(pct_change) >= 3:
                    changes.append({
                        "value": val,
                        "prev_pct": round(prev["pct_winners"]),
                        "curr_pct": round(row["pct_winners"]),
                        "change": round(pct_change),
                        "is_new": False,
                    })
            else:
                if row["pct_winners"] > 0:
                    changes.append({
                        "value": val,
                        "prev_pct": 0,
                        "curr_pct": round(row["pct_winners"]),
                        "change": round(row["pct_winners"]),
                        "is_new": True,
                    })

    changes.sort(key=lambda c: abs(c["change"]), reverse=True)
    return changes[:30]


async def generate_pdf(
    brand_name: str,
    csv_start: str,
    csv_end: str,
    classification_counts: dict[str, int],
    total_spend: float,
    dashboard_data: dict[str, list[dict]],
    top50_dashboard_data: dict[str, list[dict]],
    pattern_results: Optional[dict] = None,
    previous_run: Optional[dict] = None,
    priority: str = "General",
    output_dir: Optional[Path] = None,
) -> Path:
    """Generate a PDF report from analysis results.

    Returns path to the generated PDF.
    """
    from playwright.async_api import async_playwright

    if output_dir is None:
        output_dir = Path("output/reports")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    date_slug = datetime.now().strftime("%Y%m%d")
    brand_slug = _slugify(brand_name)
    pdf_path = output_dir / f"{brand_slug}_{date_slug}_creative_feedback.pdf"

    # Prepare template data
    dashboard_tables = _prepare_tables(dashboard_data)
    top50_tables = _prepare_tables(top50_dashboard_data)

    comparison_data = None
    previous_run_date = ""
    if previous_run:
        prev_dashboard = previous_run.get("dashboard_data", {})
        if prev_dashboard:
            comparison_data = _build_comparison_data(dashboard_data, prev_dashboard)
            run_ts = previous_run.get("run_timestamp", "")
            previous_run_date = run_ts[:10] if run_ts else "previous"

    insights = (pattern_results or {}).get("insights", [])
    learnings = (pattern_results or {}).get("learnings", [])
    hypotheses = (pattern_results or {}).get("hypotheses", [])
    executive_summary = (pattern_results or {}).get("executive_summary", "")

    # Render HTML
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report_template.html")
    html_content = template.render(
        brand_name=brand_name,
        csv_start=csv_start,
        csv_end=csv_end,
        run_date=datetime.now().strftime("%B %d, %Y"),
        total_ads=sum(classification_counts.values()),
        counts=classification_counts,
        total_spend=f"{total_spend:,.0f}",
        priority=priority,
        executive_summary=executive_summary,
        dashboard_tables=dashboard_tables,
        top50_tables=top50_tables,
        comparison_data=comparison_data,
        previous_run_date=previous_run_date,
        insights=insights,
        learnings=learnings,
        hypotheses=hypotheses,
    )

    # Render PDF with Playwright
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(f"file://{tmp_path}", wait_until="networkidle")
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
            )
            await browser.close()
    except Exception as e:
        raise RuntimeError(f"PDF generation failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(f"PDF saved: {pdf_path}")
    return pdf_path
