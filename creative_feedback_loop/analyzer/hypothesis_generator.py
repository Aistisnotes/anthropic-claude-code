"""Claude-powered hypothesis generator for creative testing.

Takes pattern analysis results and generates specific hypotheses
to test in the next round of creative production.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


async def generate_hypotheses(
    pattern_analysis: dict[str, Any],
    brand_name: str,
    num_hypotheses: int = 5,
    model: str = "claude-sonnet-4-20250514",
) -> list[dict[str, Any]]:
    """Generate testable creative hypotheses from pattern analysis.

    Args:
        pattern_analysis: Output from pattern_analyzer.analyze_creative_patterns.
        brand_name: Brand name.
        num_hypotheses: Number of hypotheses to generate.
        model: Claude model.

    Returns:
        List of hypothesis dicts.
    """
    client = anthropic.AsyncAnthropic()

    prompt = f"""You are a direct-response creative strategist for {brand_name}.

Based on this pattern analysis of our winning vs losing ads:

{json.dumps(pattern_analysis, indent=2)}

Generate exactly {num_hypotheses} testable creative hypotheses. Each hypothesis should:
1. Be based on a specific pattern difference between winners and losers
2. Be concrete enough to brief a creative team
3. Have a clear success metric

Return JSON array:
[
  {{
    "hypothesis_id": "H1",
    "hypothesis": "If we [do X], then [Y metric] will improve because [pattern evidence]",
    "based_on_pattern": "which pattern this comes from",
    "test_format": "what ad format to test this with (UGC/static/video/etc)",
    "script_direction": "2-3 sentence brief for the creative team",
    "success_metric": "what to measure and what threshold means success",
    "priority": "HIGH/MEDIUM/LOW",
    "confidence": "HIGH/MEDIUM/LOW based on strength of pattern evidence"
  }}
]"""

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        json_match = re.search(r"\[[\s\S]*\]", text)
        if json_match:
            hypotheses = json.loads(json_match.group())
            logger.info(f"Generated {len(hypotheses)} hypotheses")
            return hypotheses

        logger.error("No JSON array in hypothesis response")
        return []

    except Exception as e:
        logger.error(f"Hypothesis generation failed: {e}")
        return []
