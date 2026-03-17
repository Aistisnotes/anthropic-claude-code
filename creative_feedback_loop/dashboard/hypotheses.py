"""Hypothesis rendering for creative feedback loop dashboard.

BUG 4 FIX: Previously displayed raw Python dicts like:
    {'Root cause': 'Cellular-level...', 'Mechanism': 'Specific vessel...'}
Now formats each hypothesis as a readable card with title, bullet points,
and dark themed card styling matching the opportunity cards.
"""

from __future__ import annotations

from typing import Any


def format_hypothesis(hypothesis: dict[str, Any] | str, index: int = 1) -> dict[str, Any]:
    """Format a single hypothesis into a readable card.

    Handles both dict and string inputs. For dicts, derives a title from
    root cause + mechanism fields and renders bullet points for each field.

    Args:
        hypothesis: Raw hypothesis dict or string.
        index: 1-based index for display.

    Returns:
        Formatted card dict with title, bullets, and display_text.
    """
    if isinstance(hypothesis, str):
        return {
            "index": index,
            "title": f"Hypothesis #{index}",
            "bullets": [{"label": "Hypothesis", "value": hypothesis}],
            "display_text": f"**Hypothesis #{index}**\n{hypothesis}",
        }

    if not isinstance(hypothesis, dict):
        return {
            "index": index,
            "title": f"Hypothesis #{index}",
            "bullets": [{"label": "Details", "value": str(hypothesis)}],
            "display_text": f"**Hypothesis #{index}**\n{hypothesis}",
        }

    # Derive title from root cause + mechanism
    root_cause = hypothesis.get("Root cause", hypothesis.get("root_cause", ""))
    mechanism = hypothesis.get("Mechanism", hypothesis.get("mechanism", ""))
    title = _derive_title(root_cause, mechanism, index)

    # Build bullet points for each field
    bullets = []
    # Define preferred field order
    field_order = [
        ("Root cause", "root_cause"),
        ("Mechanism", "mechanism"),
        ("Pain point", "pain_point"),
        ("Target", "target"),
        ("Hook", "hook"),
        ("Angle", "angle"),
        ("Evidence", "evidence"),
        ("Confidence", "confidence"),
        ("Expected ROAS", "expected_roas"),
        ("Test approach", "test_approach"),
        ("Why", "why"),
        ("Rationale", "rationale"),
    ]

    seen_keys = set()
    for display_name, alt_key in field_order:
        value = hypothesis.get(display_name, hypothesis.get(alt_key))
        if value:
            bullets.append({"label": display_name, "value": str(value)})
            seen_keys.add(display_name)
            seen_keys.add(alt_key)

    # Add any remaining fields not in the preferred order
    for key, value in hypothesis.items():
        if key not in seen_keys and value:
            label = key.replace("_", " ").title()
            bullets.append({"label": label, "value": str(value)})

    # Build display text
    display_lines = [f"**{title}**"]
    for bullet in bullets:
        display_lines.append(f"  • **{bullet['label']}**: {bullet['value']}")

    return {
        "index": index,
        "title": title,
        "bullets": bullets,
        "display_text": "\n".join(display_lines),
    }


def _derive_title(root_cause: str, mechanism: str, index: int) -> str:
    """Derive a hypothesis title from root cause and mechanism fields."""
    parts = []
    if root_cause:
        # Take first ~40 chars of root cause
        rc_short = root_cause[:40].rstrip()
        if len(root_cause) > 40:
            rc_short += "..."
        parts.append(rc_short)
    if mechanism:
        mech_short = mechanism[:40].rstrip()
        if len(mechanism) > 40:
            mech_short += "..."
        parts.append(mech_short)

    if parts:
        return f"Hypothesis #{index}: {' + '.join(parts)}"
    return f"Hypothesis #{index}"


def format_hypotheses(hypotheses: list[Any]) -> list[dict[str, Any]]:
    """Format a list of hypotheses into readable cards.

    Args:
        hypotheses: List of raw hypothesis dicts or strings.

    Returns:
        List of formatted card dicts.
    """
    return [format_hypothesis(h, i + 1) for i, h in enumerate(hypotheses)]


def render_hypotheses_text(hypotheses: list[Any]) -> str:
    """Render hypotheses as plain text for CLI output."""
    if not hypotheses:
        return "No hypotheses generated."

    cards = format_hypotheses(hypotheses)
    lines = ["HYPOTHESES", "=" * 40, ""]
    for card in cards:
        lines.append(card["display_text"])
        lines.append("")
        lines.append("-" * 40)
        lines.append("")

    return "\n".join(lines)


def render_hypothesis_html(card: dict[str, Any]) -> str:
    """Render a single hypothesis card as dark-themed HTML.

    Matches the styling of opportunity cards in the dashboard.
    """
    title = card.get("title", "Hypothesis")
    bullets = card.get("bullets", [])

    bullet_html = ""
    for b in bullets:
        bullet_html += (
            f'<div style="margin: 4px 0; padding: 2px 0;">'
            f'<span style="color: #9ca3af; font-weight: 600;">{b["label"]}:</span> '
            f'<span style="color: #e5e7eb;">{b["value"]}</span>'
            f'</div>'
        )

    return (
        f'<div style="background: #1f2937; border: 1px solid #374151; '
        f'border-radius: 8px; padding: 16px; margin: 8px 0;">'
        f'<div style="color: #60a5fa; font-size: 14px; font-weight: 700; '
        f'margin-bottom: 8px;">{title}</div>'
        f'{bullet_html}'
        f'</div>'
    )
