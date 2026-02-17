"""Strategic dimension extractor - uses Claude to extract 6 DR strategy dimensions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
from jinja2 import Template

from meta_ads_analyzer.compare.strategic_dimensions import (
    MassDesirePattern,
    MechanismPattern,
    PainPointPattern,
    RootCausePattern,
    StrategicDimensions,
    SymptomPattern,
    TargetAudiencePattern,
)
from meta_ads_analyzer.models import BrandReport
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


async def extract_strategic_dimensions(
    brand_report: BrandReport, config: dict[str, Any]
) -> StrategicDimensions:
    """Extract 6 strategic dimensions from brand report using Claude analysis.

    Args:
        brand_report: BrandReport with pattern analysis
        config: Config dict with API settings

    Returns:
        StrategicDimensions with all 6 dimension types extracted
    """
    logger.info(f"Extracting strategic dimensions for {brand_report.advertiser.page_name}")

    # Build analyses JSON from pattern report
    pr = brand_report.pattern_report
    analyses = []

    # Extract available pattern data
    for i, pain_point in enumerate(pr.common_pain_points[:10], 1):
        analyses.append(
            {
                "id": f"pain_{i}",
                "pain_point": pain_point.get("pattern", ""),
                "frequency": pain_point.get("frequency", 0),
            }
        )

    for i, symptom in enumerate(pr.common_symptoms[:10], 1):
        analyses.append(
            {
                "id": f"symptom_{i}",
                "symptom": symptom.get("pattern", ""),
                "frequency": symptom.get("frequency", 0),
            }
        )

    for i, root_cause in enumerate(pr.root_cause_patterns[:10], 1):
        analyses.append(
            {
                "id": f"root_{i}",
                "root_cause": root_cause.get("pattern", ""),
                "frequency": root_cause.get("frequency", 0),
            }
        )

    for i, mechanism in enumerate(pr.mechanism_patterns[:10], 1):
        analyses.append(
            {
                "id": f"mech_{i}",
                "mechanism": mechanism.get("pattern", ""),
                "frequency": mechanism.get("frequency", 0),
            }
        )

    for i, desire in enumerate(pr.mass_desire_patterns[:10], 1):
        analyses.append(
            {
                "id": f"desire_{i}",
                "desire": desire.get("pattern", ""),
                "frequency": desire.get("frequency", 0),
            }
        )

    # Load prompt template
    prompt_path = Path("prompts/strategic_dimension_extraction.txt")
    with open(prompt_path) as f:
        template_text = f.read()

    # Render prompt using jinja2
    template = Template(template_text)
    prompt = template.render(
        brand_name=brand_report.advertiser.page_name,
        keyword=brand_report.keyword,
        total_ads=pr.total_ads_analyzed,
        analyses_json=json.dumps(analyses, indent=2),
    )

    # Call Claude
    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=config.get("analyzer", {}).get("model", "claude-sonnet-4-20250514"),
        max_tokens=4096,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse response
    text = response.content[0].text.strip()
    data = _parse_dimensions_response(text)

    # Convert to StrategicDimensions model
    return StrategicDimensions(
        root_causes=[RootCausePattern(**rc) for rc in data.get("root_causes", [])],
        mechanisms=[MechanismPattern(**m) for m in data.get("mechanisms", [])],
        target_audiences=[
            TargetAudiencePattern(**ta) for ta in data.get("target_audiences", [])
        ],
        pain_points=[PainPointPattern(**pp) for pp in data.get("pain_points", [])],
        symptoms=[SymptomPattern(**s) for s in data.get("symptoms", [])],
        mass_desires=[MassDesirePattern(**md) for md in data.get("mass_desires", [])],
    )


def _parse_dimensions_response(text: str) -> dict:
    """Parse Claude's strategic dimensions response.

    Args:
        text: Raw response text

    Returns:
        Dict with 6 dimension lists
    """
    try:
        # Look for JSON code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            json_text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            json_text = text[start:end].strip()
        else:
            # Assume entire response is JSON
            json_text = text.strip()

        data = json.loads(json_text)
        return data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse dimensions response as JSON: {e}")
        logger.debug(f"Response text: {text[:500]}...")

        # Return empty structure
        return {
            "root_causes": [],
            "mechanisms": [],
            "target_audiences": [],
            "pain_points": [],
            "symptoms": [],
            "mass_desires": [],
        }
