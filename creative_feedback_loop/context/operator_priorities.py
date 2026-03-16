"""Operator priority input for creative feedback loop.

Provides priority selection and custom context that shapes Claude's analysis.
Priority options: Spend Volume, Efficiency, New Angles, General.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

PRIORITY_OPTIONS = {
    "General": {
        "label": "General — Show me everything",
        "prompt_injection": "",
    },
    "Spend Volume": {
        "label": "Spend Volume — Patterns that drive the most total spend",
        "prompt_injection": (
            "OPERATOR PRIORITY: SPEND VOLUME\n"
            "Rank patterns by total spend generated. An ad spending $70k at 1.5x ROAS "
            "matters more than $500 at 3x ROAS. Focus on what drives scale."
        ),
    },
    "Efficiency": {
        "label": "Efficiency — Patterns that maximize ROAS at good spend levels",
        "prompt_injection": (
            "OPERATOR PRIORITY: EFFICIENCY\n"
            "Rank patterns by ROAS. Focus on what delivers the best return per dollar. "
            "Filter for ads with meaningful spend (>$500) to avoid noise from low-spend outliers."
        ),
    },
    "New Angles": {
        "label": "New Angles — Find underexplored combinations",
        "prompt_injection": (
            "OPERATOR PRIORITY: NEW ANGLES\n"
            "Highlight patterns that appear in < 20% of ads but show strong performance. "
            "Find underexplored territory. What combinations haven't been tried?"
        ),
    },
}


def render_priority_input() -> tuple[str, str]:
    """Render operator priority selector and custom context input.

    Returns:
        Tuple of (priority_key, custom_context_text).
    """
    st.markdown('<p style="color:#fafafa; font-weight:600; margin-bottom:4px;">Analysis Priority</p>', unsafe_allow_html=True)

    priority = st.selectbox(
        "Priority",
        options=list(PRIORITY_OPTIONS.keys()),
        index=0,
        format_func=lambda k: PRIORITY_OPTIONS[k]["label"],
        label_visibility="collapsed",
    )

    custom_context = st.text_area(
        "Any specific focus or context for this analysis? (optional)",
        placeholder='e.g., "We\'re trying to scale kidney ads past $20k/week. What patterns work at high spend?"',
        height=80,
        key="operator_custom_context",
    )

    return priority, custom_context


def build_priority_prompt(priority: str, custom_context: str = "") -> str:
    """Build the priority prompt injection string.

    Args:
        priority: Priority key from PRIORITY_OPTIONS.
        custom_context: Optional custom context from operator.

    Returns:
        Full prompt injection string (empty if General with no custom context).
    """
    parts = []

    injection = PRIORITY_OPTIONS.get(priority, {}).get("prompt_injection", "")
    if injection:
        parts.append(injection)

    if custom_context and custom_context.strip():
        parts.append(f"ADDITIONAL OPERATOR CONTEXT:\n{custom_context.strip()}")

    return "\n\n".join(parts)
