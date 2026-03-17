"""Learnings rendering for creative feedback loop dashboard.

BUG 5 FIX: Previously showed one-line bullets with no supporting data:
    "Solution Aware Thyroid Scripts Consistently Fail"
Now each learning includes the observation, supporting evidence (ad count,
spend, ROAS), example ads by name, and confidence level.

Output format:
    "Solution Aware Thyroid Scripts Consistently Fail — 15 loser ads used
    solution aware targeting on thyroid, spending $31k combined at 0.68x ROAS.
    Not a single winner used this combination. Confidence: HIGH"
"""

from __future__ import annotations

from typing import Any


def format_learning(
    learning: dict[str, Any] | str,
    dashboard_data: dict[str, Any] | None = None,
    index: int = 1,
) -> dict[str, Any]:
    """Format a single learning with supporting evidence.

    Args:
        learning: Raw learning dict or string observation.
        dashboard_data: Optional dashboard data to pull evidence from.
        index: 1-based index.

    Returns:
        Formatted learning dict with observation, evidence, examples, confidence.
    """
    if isinstance(learning, str):
        # Try to enrich a bare string with dashboard data
        result = {
            "index": index,
            "observation": learning,
            "evidence": "",
            "example_ads": [],
            "confidence": "MEDIUM",
            "display_text": learning,
        }
        if dashboard_data:
            _enrich_learning(result, dashboard_data)
        result["display_text"] = _build_display_text(result)
        return result

    if not isinstance(learning, dict):
        return {
            "index": index,
            "observation": str(learning),
            "evidence": "",
            "example_ads": [],
            "confidence": "LOW",
            "display_text": str(learning),
        }

    observation = learning.get("observation", learning.get("title", learning.get("text", str(learning))))
    evidence = learning.get("evidence", "")
    example_ads = learning.get("example_ads", learning.get("examples", []))
    confidence = learning.get("confidence", "MEDIUM")
    winner_count = learning.get("winner_count", 0)
    loser_count = learning.get("loser_count", 0)
    total_spend = learning.get("total_spend", 0)
    avg_roas = learning.get("avg_roas", 0.0)

    # Build evidence string if not provided but we have structured data
    if not evidence and (winner_count or loser_count):
        evidence = _build_evidence_from_counts(
            winner_count=winner_count,
            loser_count=loser_count,
            total_spend=total_spend,
            avg_roas=avg_roas,
        )

    result = {
        "index": index,
        "observation": observation,
        "evidence": evidence,
        "example_ads": example_ads if isinstance(example_ads, list) else [example_ads],
        "confidence": confidence.upper() if isinstance(confidence, str) else "MEDIUM",
        "winner_count": winner_count,
        "loser_count": loser_count,
        "total_spend": total_spend,
        "avg_roas": avg_roas,
    }

    if dashboard_data and not evidence:
        _enrich_learning(result, dashboard_data)

    result["display_text"] = _build_display_text(result)
    return result


def _build_evidence_from_counts(
    winner_count: int,
    loser_count: int,
    total_spend: float,
    avg_roas: float,
) -> str:
    """Build an evidence string from structured counts."""
    parts = []
    if loser_count > 0:
        parts.append(f"{loser_count} loser ads")
    if winner_count > 0:
        parts.append(f"{winner_count} winner ads")
    if total_spend > 0:
        if total_spend >= 1000:
            spend_str = f"${total_spend / 1000:.0f}k"
        else:
            spend_str = f"${total_spend:.0f}"
        parts.append(f"spending {spend_str} combined")
    if avg_roas > 0:
        parts.append(f"at {avg_roas:.2f}x ROAS")

    if not parts:
        return ""

    evidence = ", ".join(parts)

    # Add winner/loser contrast
    if loser_count > 0 and winner_count == 0:
        evidence += ". Not a single winner used this combination"
    elif winner_count > 0 and loser_count == 0:
        evidence += ". No losers used this approach"

    return evidence


def _enrich_learning(
    learning: dict[str, Any],
    dashboard_data: dict[str, Any],
) -> None:
    """Try to enrich a learning with evidence from dashboard data.

    Matches the learning observation text against dimension values to find
    relevant counts and ROAS data.
    """
    observation = learning.get("observation", "").lower()
    dimensions = dashboard_data.get("dimensions", [])

    best_match = None
    best_score = 0

    for dim in dimensions:
        dim_name = dim.get("name", "").lower()
        for val in dim.get("values", []):
            val_name = val.get("value", "").lower()
            score = 0
            if val_name and val_name in observation:
                score += 3
            if dim_name and dim_name in observation:
                score += 1
            if score > best_score:
                best_score = score
                best_match = val

    if best_match and best_score >= 2:
        winner_count = best_match.get("winner_count", 0)
        loser_count = best_match.get("loser_count", 0)
        total_spend = best_match.get("total_spend", 0)
        avg_roas = best_match.get("avg_roas", 0.0)
        example_ads = best_match.get("example_ads", [])

        learning["winner_count"] = winner_count
        learning["loser_count"] = loser_count
        learning["total_spend"] = total_spend
        learning["avg_roas"] = avg_roas

        if example_ads:
            learning["example_ads"] = example_ads[:3]

        if not learning.get("evidence"):
            learning["evidence"] = _build_evidence_from_counts(
                winner_count, loser_count, total_spend, avg_roas
            )

        # Set confidence based on data strength
        total_ads = winner_count + loser_count
        if total_ads >= 10:
            learning["confidence"] = "HIGH"
        elif total_ads >= 5:
            learning["confidence"] = "MEDIUM"
        else:
            learning["confidence"] = "LOW"


def _build_display_text(learning: dict[str, Any]) -> str:
    """Build the full display text for a learning.

    Format:
        "Solution Aware Thyroid Scripts Consistently Fail — 15 loser ads used
        solution aware targeting on thyroid, spending $31k combined at 0.68x ROAS.
        Not a single winner used this combination. Confidence: HIGH"
    """
    observation = learning.get("observation", "Unknown")
    evidence = learning.get("evidence", "")
    example_ads = learning.get("example_ads", [])
    confidence = learning.get("confidence", "MEDIUM")

    parts = [observation]

    if evidence:
        parts[0] += f" — {evidence}"

    if example_ads:
        ad_names = [str(a) for a in example_ads[:3]]
        parts.append(f"Examples: {', '.join(ad_names)}")

    parts.append(f"Confidence: {confidence}")

    return ". ".join(parts)


def format_learnings(
    learnings: list[Any],
    dashboard_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Format a list of learnings with evidence.

    Args:
        learnings: List of raw learning dicts or strings.
        dashboard_data: Optional dashboard data for enrichment.

    Returns:
        List of formatted learning dicts.
    """
    return [
        format_learning(l, dashboard_data, i + 1)
        for i, l in enumerate(learnings)
    ]


def render_learnings_text(
    learnings: list[Any],
    dashboard_data: dict[str, Any] | None = None,
) -> str:
    """Render learnings as plain text for CLI output."""
    if not learnings:
        return "No learnings recorded."

    formatted = format_learnings(learnings, dashboard_data)
    lines = ["LEARNINGS", "=" * 40, ""]
    for l in formatted:
        lines.append(f"  {l['index']}. {l['display_text']}")
        lines.append("")

    return "\n".join(lines)
