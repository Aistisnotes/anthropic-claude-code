"""Hypothesis Generator — generates learnings and testable hypotheses from pattern analysis.

Each learning gets a confidence level based on sample size and weight.
Each hypothesis includes a suggested script outline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .classifier import ClassificationResult
from .pattern_analyzer import PatternAnalysis


@dataclass
class Learning:
    """A specific learning from pattern analysis."""
    observation: str
    confidence: str  # HIGH / MEDIUM / LOW
    supporting_evidence: list[str] = field(default_factory=list)


@dataclass
class Hypothesis:
    """A testable hypothesis derived from a learning."""
    independent_variable: str
    expected_outcome: str
    based_on_learning: str
    suggested_hook_ideas: list[str] = field(default_factory=list)
    suggested_body_structure: str = ""
    recommended_format: str = ""
    priority: str = "MEDIUM"  # HIGH / MEDIUM / LOW


@dataclass
class HypothesisReport:
    """Complete learnings and hypotheses output."""
    learnings: list[Learning] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    raw_response: str = ""


HYPOTHESIS_PROMPT = """Based on the following pattern analysis of ad creative performance, generate specific learnings and testable hypotheses.

PATTERN ANALYSIS:
{pattern_analysis}

CLASSIFICATION SUMMARY:
- Winners: {num_winners} ({pillar_winners} pillar, {strong_winners} strong)
- Losers: {num_losers}
- Average: {num_average}
- Total account spend: ${total_spend:,.0f}

Generate your response in EXACTLY this format:

## LEARNINGS

### Learning 1
OBSERVATION: [Specific observation about what works or doesn't]
CONFIDENCE: [HIGH/MEDIUM/LOW — HIGH requires 3+ ads with pillar/strong weight, MEDIUM requires 2+ ads, LOW is based on limited data]
EVIDENCE: [List specific ad names and metrics that support this]

### Learning 2
[Same format — provide 5-7 learnings total]

## HYPOTHESES

### Hypothesis 1
BASED ON: [Which learning number this comes from]
INDEPENDENT VARIABLE: [What to change/test]
EXPECTED OUTCOME: [What you expect to happen]
PRIORITY: [HIGH = based on pillar ad patterns, MEDIUM = based on strong/normal patterns, LOW = speculative]
SUGGESTED SCRIPT:
- Hook ideas: [2-3 specific hook ideas based on winner patterns]
- Body structure: [Recommended body copy structure]
- Format: [Recommended ad format]

### Hypothesis 2
[Same format — provide 1-2 hypotheses per learning]"""


def generate_hypotheses(
    pattern_analysis: PatternAnalysis,
    classification: ClassificationResult,
) -> HypothesisReport:
    """Generate learnings and hypotheses from pattern analysis."""
    prompt = HYPOTHESIS_PROMPT.format(
        pattern_analysis=pattern_analysis.raw_analysis,
        num_winners=len(classification.winners),
        pillar_winners=classification.pillar_winners,
        strong_winners=classification.strong_winners,
        num_losers=len(classification.losers),
        num_average=len(classification.average),
        total_spend=classification.total_account_spend,
    )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    report = HypothesisReport(raw_response=raw)

    # Parse learnings
    report.learnings = _parse_learnings(raw)
    report.hypotheses = _parse_hypotheses(raw)

    return report


def _parse_learnings(text: str) -> list[Learning]:
    """Parse learnings from Claude's response."""
    learnings: list[Learning] = []
    current: dict[str, Any] = {}

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("### Learning"):
            if current.get("observation"):
                learnings.append(Learning(
                    observation=current.get("observation", ""),
                    confidence=current.get("confidence", "MEDIUM"),
                    supporting_evidence=current.get("evidence", []),
                ))
            current = {}
        elif line.startswith("OBSERVATION:"):
            current["observation"] = line[len("OBSERVATION:"):].strip()
        elif line.startswith("CONFIDENCE:"):
            current["confidence"] = line[len("CONFIDENCE:"):].strip()
        elif line.startswith("EVIDENCE:"):
            evidence_text = line[len("EVIDENCE:"):].strip()
            current["evidence"] = [e.strip() for e in evidence_text.split(",") if e.strip()]

    # Save last learning
    if current.get("observation"):
        learnings.append(Learning(
            observation=current.get("observation", ""),
            confidence=current.get("confidence", "MEDIUM"),
            supporting_evidence=current.get("evidence", []),
        ))

    return learnings


def _parse_hypotheses(text: str) -> list[Hypothesis]:
    """Parse hypotheses from Claude's response."""
    hypotheses: list[Hypothesis] = []
    current: dict[str, Any] = {}

    in_hook_ideas = False
    in_body = False

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("### Hypothesis"):
            if current.get("independent_variable"):
                hypotheses.append(Hypothesis(
                    independent_variable=current.get("independent_variable", ""),
                    expected_outcome=current.get("expected_outcome", ""),
                    based_on_learning=current.get("based_on", ""),
                    suggested_hook_ideas=current.get("hook_ideas", []),
                    suggested_body_structure=current.get("body_structure", ""),
                    recommended_format=current.get("format", ""),
                    priority=current.get("priority", "MEDIUM"),
                ))
            current = {}
            in_hook_ideas = False
            in_body = False
        elif line.startswith("BASED ON:"):
            current["based_on"] = line[len("BASED ON:"):].strip()
            in_hook_ideas = False
            in_body = False
        elif line.startswith("INDEPENDENT VARIABLE:"):
            current["independent_variable"] = line[len("INDEPENDENT VARIABLE:"):].strip()
            in_hook_ideas = False
            in_body = False
        elif line.startswith("EXPECTED OUTCOME:"):
            current["expected_outcome"] = line[len("EXPECTED OUTCOME:"):].strip()
            in_hook_ideas = False
            in_body = False
        elif line.startswith("PRIORITY:"):
            current["priority"] = line[len("PRIORITY:"):].strip()
            in_hook_ideas = False
            in_body = False
        elif "Hook ideas:" in line or "hook ideas:" in line.lower():
            hook_text = line.split(":", 1)[1].strip() if ":" in line else ""
            current.setdefault("hook_ideas", [])
            if hook_text:
                current["hook_ideas"].extend([h.strip() for h in hook_text.split(",") if h.strip()])
            in_hook_ideas = True
            in_body = False
        elif "Body structure:" in line or "body structure:" in line.lower():
            current["body_structure"] = line.split(":", 1)[1].strip() if ":" in line else ""
            in_hook_ideas = False
            in_body = True
        elif "Format:" in line and "format:" in line.lower():
            current["format"] = line.split(":", 1)[1].strip() if ":" in line else ""
            in_hook_ideas = False
            in_body = False
        elif in_hook_ideas and line.startswith("- "):
            current.setdefault("hook_ideas", []).append(line[2:].strip())
        elif in_body and line:
            current["body_structure"] = current.get("body_structure", "") + " " + line

    # Save last hypothesis
    if current.get("independent_variable"):
        hypotheses.append(Hypothesis(
            independent_variable=current.get("independent_variable", ""),
            expected_outcome=current.get("expected_outcome", ""),
            based_on_learning=current.get("based_on", ""),
            suggested_hook_ideas=current.get("hook_ideas", []),
            suggested_body_structure=current.get("body_structure", ""),
            recommended_format=current.get("format", ""),
            priority=current.get("priority", "MEDIUM"),
        ))

    return hypotheses
