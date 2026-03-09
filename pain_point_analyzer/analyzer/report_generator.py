"""Step 6: Report Generation.

Compile all analysis into JSON + PDF report.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .ingredient_extractor import ExtractionResult
from .pain_point_discovery import DiscoveryResult
from .positioning_engine import PositioningResult
from .scientific_researcher import ResearchResult
from .trends_validator import ValidationResult

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class ReportGenerator:
    """Generate JSON + PDF reports from analysis results."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.output_dir = Path(
            config.get("reporting", {}).get("output_dir", "output")
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        extraction: ExtractionResult,
        discovery: DiscoveryResult,
        trends: ValidationResult,
        research: ResearchResult,
        positioning: PositioningResult,
        url: str,
    ) -> dict[str, Any]:
        """Compile all results into a structured report dict and save files."""
        report = self._build_report_dict(
            extraction, discovery, trends, research, positioning, url
        )

        # Save JSON
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        product_slug = (
            extraction.product.product_name[:40]
            .replace(" ", "_")
            .replace("/", "_")
        )
        safe_slug = "".join(
            c for c in product_slug if c.isalnum() or c in "-_"
        ) or "product"

        json_path = self.output_dir / f"{timestamp}_{safe_slug}.json"
        json_path.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        logger.info(f"JSON report saved: {json_path}")

        report["_json_path"] = str(json_path)
        return report

    def generate_pdf(self, report: dict[str, Any]) -> Path | None:
        """Generate PDF from report data using Jinja2 + Playwright."""
        try:
            env = Environment(
                loader=FileSystemLoader(str(TEMPLATE_DIR)),
                autoescape=True,
            )
            template = env.get_template("report_template.html")

            html = template.render(
                report=report,
                generated_date=datetime.utcnow().strftime("%B %d, %Y"),
            )

            # Save HTML
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            html_path = self.output_dir / f"{timestamp}_report.html"
            html_path.write_text(html, encoding="utf-8")

            # Convert to PDF with Playwright
            pdf_path = html_path.with_suffix(".pdf")
            self._html_to_pdf(html_path, pdf_path)

            logger.info(f"PDF report saved: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"PDF generation failed: {e}")
            return None

    def _html_to_pdf(self, html_path: Path, pdf_path: Path) -> None:
        """Convert HTML file to PDF using Playwright."""
        import asyncio

        from playwright.async_api import async_playwright

        async def _convert():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(
                    f"file://{html_path.resolve()}",
                    wait_until="networkidle",
                )
                await page.pdf(
                    path=str(pdf_path),
                    format="A4",
                    margin={"top": "14mm", "bottom": "14mm",
                            "left": "15mm", "right": "15mm"},
                    print_background=True,
                )
                await browser.close()

        asyncio.get_event_loop().run_until_complete(_convert())

    def _build_report_dict(
        self,
        extraction: ExtractionResult,
        discovery: DiscoveryResult,
        trends: ValidationResult,
        research: ResearchResult,
        positioning: PositioningResult,
        url: str,
    ) -> dict[str, Any]:
        """Build the complete report dictionary."""
        # Product summary
        product = {
            "name": extraction.product.product_name,
            "brand": extraction.product.brand_name,
            "url": url,
            "description": extraction.product.description,
            "claims": extraction.product.claims,
            "ingredients": [
                {
                    "name": ing.name,
                    "amount": ing.amount,
                    "unit": ing.unit,
                    "sources": ing.sources,
                }
                for ing in extraction.ingredients
            ],
        }

        # All pain points
        all_pain_points = [
            {
                "name": pp.name,
                "description": pp.description,
                "category": pp.category,
                "supporting_ingredients": pp.supporting_ingredients,
                "ingredient_count": pp.ingredient_count,
            }
            for pp in discovery.pain_points
        ]

        # Demand validation data (Meta Ad Library)
        trends_data = []
        for r in trends.all_results:
            trends_data.append({
                "pain_point": r.pain_point.name,
                "best_keyword": r.best_keyword,
                "best_score": r.best_score,
                "tier": r.tier,
                "tier_label": r.tier_label,
                "tier_color": r.tier_color,
                "keywords": [
                    {
                        "keyword": ks.keyword,
                        "score": ks.score,
                        "variant_type": ks.variant_type,
                    }
                    for ks in r.keywords
                ],
                "is_top": r in trends.top_results,
            })

        # Top 3 deep dives
        top_deep_dives = []
        for tr in trends.top_results:
            # Find matching science and positioning
            science = None
            for sr in research.reports:
                if sr.pain_point_name == tr.pain_point.name:
                    science = sr
                    break

            pos = None
            for pd in positioning.docs:
                if pd.pain_point_name == tr.pain_point.name:
                    pos = pd
                    break

            dive = {
                "pain_point": tr.pain_point.name,
                "supporting_ingredients": tr.pain_point.supporting_ingredients,
                "best_keyword": tr.best_keyword,
                "trend_score": tr.best_score,
                "tier": tr.tier,
                "tier_label": tr.tier_label,
                "tier_color": tr.tier_color,
            }

            if science:
                dive["science"] = {
                    "summary": science.summary,
                    "overall_evidence": science.overall_evidence_strength,
                    "ingredient_evidence": [
                        {
                            "ingredient": ev.ingredient_name,
                            "strength": ev.evidence_strength,
                            "mechanism": ev.mechanism,
                            "studies": [
                                {
                                    "description": s.description,
                                    "dosage": s.dosage,
                                    "duration": s.duration,
                                    "effect_size": s.effect_size,
                                }
                                for s in ev.key_studies
                            ],
                            "contraindications": ev.contraindications,
                            "optimal_dosage": ev.optimal_dosage,
                        }
                        for ev in science.ingredient_evidence
                    ],
                    "synergies": [
                        {
                            "ingredients": syn.ingredients,
                            "description": syn.synergy_description,
                            "mechanism": syn.mechanism,
                        }
                        for syn in science.synergies
                    ],
                }

            if pos:
                dive["positioning"] = {
                    "root_cause": {
                        "surface": pos.root_cause_surface,
                        "cellular": pos.root_cause_cellular,
                        "molecular": pos.root_cause_molecular,
                    },
                    "mechanism": pos.mechanism,
                    "avatar": {
                        "age": pos.avatar_age,
                        "gender": pos.avatar_gender,
                        "lifestyle": pos.avatar_lifestyle,
                        "tried_before": pos.avatar_tried_before,
                    },
                    "daily_symptoms": pos.daily_symptoms,
                    "mass_desire": pos.mass_desire,
                    "hooks": pos.hooks,
                }

            top_deep_dives.append(dive)

        # Synergy map
        synergy_map = []
        for sr in research.reports:
            for syn in sr.synergies:
                synergy_map.append({
                    "pain_point": syn.pain_point,
                    "ingredients": syn.ingredients,
                    "description": syn.synergy_description,
                    "mechanism": syn.mechanism,
                })

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "product": product,
            "all_pain_points": all_pain_points,
            "trends": trends_data,
            "top_deep_dives": top_deep_dives,
            "synergy_map": synergy_map,
        }
