"""Pattern analyzer for creative feedback loop.

Wraps Claude API pattern analysis and enriches opportunity dicts with actual
structured fields (winner_count, loser_count, avg_roas) parsed from the
response text and/or dashboard data.

BUG 2 FIX: Previously returned winner_count=0, loser_count=0, avg_roas=0 on
every opportunity card because the structured fields were never populated.
Now parses these numbers from Claude's response text (e.g. "8 winner ads")
and falls back to dashboard data counts.
"""

from __future__ import annotations

import re
from typing import Any


def analyze_patterns(
    response_text: str,
    dashboard_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse opportunity cards from Claude pattern analysis response.

    Extracts structured fields (winner_count, loser_count, avg_roas, score)
    from the response text. Falls back to dashboard_data counts if text
    parsing fails.

    Args:
        response_text: Raw text from Claude pattern analysis.
        dashboard_data: Optional dashboard data dict with dimension-level
            winner/loser counts and ROAS values.

    Returns:
        List of opportunity dicts with populated structured fields.
    """
    opportunities = _parse_opportunities_from_text(response_text)

    # Enrich with dashboard data if available
    if dashboard_data:
        _enrich_from_dashboard(opportunities, dashboard_data)

    return opportunities


def _parse_opportunities_from_text(text: str) -> list[dict[str, Any]]:
    """Parse opportunity sections from Claude response text.

    Looks for structured opportunity blocks and extracts both the narrative
    text and embedded numeric fields. Handles both "Opportunity #N" and
    numbered-list "1. Title" formats.
    """
    opportunities = []

    # Split on either "Opportunity #N" OR numbered items "1. Title" (capital after number)
    # Use (?:^|\n) so the first item at position 0 is also captured as a split point.
    sections = re.split(
        r'(?:^|\n)(?:#{1,3}\s*)?(?:Opportunity\s*#?\d+\s*[:–—]?\s*|\d+[\.\)]\s+(?=[A-Z\w]))',
        text, flags=re.IGNORECASE | re.MULTILINE
    )

    # If no structured sections found, treat entire text as one opportunity
    if len(sections) <= 1:
        opp = _extract_fields_from_section(text)
        if opp.get("text"):
            opportunities.append(opp)
        return opportunities

    for section in sections[1:]:  # Skip preamble before first opportunity
        section = section.strip()
        if not section:
            continue
        opp = _extract_fields_from_section(section)
        if opp.get("text"):
            opportunities.append(opp)

    return opportunities


def _extract_fields_from_section(section: str) -> dict[str, Any]:
    """Extract structured fields from an opportunity section.

    NOTE: We do NOT parse winner_count, loser_count, or avg_roas from Claude's
    text because Claude often generates approximate or inflated numbers.
    These stats are populated later from ACTUAL dashboard data in
    _enrich_from_dashboard(). If no dashboard match is found, we show
    "Based on Claude analysis" instead of fake numbers.
    """
    opp: dict[str, Any] = {"text": section.strip()}

    # Parse score: "Score: 85/100", "85/100"
    score_match = re.search(r'[Ss]core[:\s]+(\d+)\s*/\s*100', section)
    if not score_match:
        score_match = re.search(r'(\d+)\s*/\s*100', section)
    if score_match:
        opp["score"] = int(score_match.group(1))

    # Parse title: first line or bold text; strip any leftover leading "1." numbering
    title_match = re.search(r'^[#*]*\s*(.+?)(?:\n|$)', section.strip())
    if title_match:
        raw_title = re.sub(r'[#*]', '', title_match.group(1)).strip()
        raw_title = re.sub(r'^\d+[\.\)]\s*', '', raw_title)
        opp["title"] = raw_title

    # Stats default to None (unverified) — will be filled from dashboard data
    opp.setdefault("winner_count", None)
    opp.setdefault("loser_count", None)
    opp.setdefault("avg_roas", None)
    opp.setdefault("score", 0)
    opp.setdefault("title", "Untitled Opportunity")
    opp["stats_verified"] = False

    return opp


def _enrich_from_dashboard(
    opportunities: list[dict[str, Any]],
    dashboard_data: dict[str, Any],
) -> None:
    """Enrich opportunity dicts with data from the dashboard.

    If an opportunity still has 0 for winner_count/loser_count/avg_roas,
    try to pull actual values from the dashboard dimension data.
    """
    dimensions = dashboard_data.get("dimensions", [])
    if not dimensions:
        return

    # Compute aggregate winner/loser counts across all dimensions
    total_winners = 0
    total_losers = 0
    roas_values = []

    for dim in dimensions:
        for val in dim.get("values", []):
            w = val.get("winner_count", 0)
            l = val.get("loser_count", 0)
            total_winners += w
            total_losers += l
            if val.get("avg_roas", 0) > 0:
                roas_values.append(val["avg_roas"])

    avg_roas = sum(roas_values) / len(roas_values) if roas_values else 0.0

    # Match opportunities to specific dimensions by keyword — use REAL data only
    for opp in opportunities:
        if opp.get("winner_count") is None:
            matched = _match_opportunity_to_dimension(opp, dimensions)
            if matched:
                opp["winner_count"] = matched.get("winner_count", 0)
                opp["loser_count"] = matched.get("loser_count", 0)
                opp["avg_roas"] = matched.get("avg_roas", 0.0)
                opp["total_spend"] = matched.get("total_spend", 0)
                opp["stats_verified"] = True
            else:
                # No match — leave as unverified, don't fill with aggregates
                opp["winner_count"] = None
                opp["loser_count"] = None
                opp["avg_roas"] = None
                opp["stats_verified"] = False


def build_spend_context(
    ads: list[dict[str, Any]],
    parsed_names: list[dict[str, Any]] | None = None,
) -> str:
    """Build spend aggregation context for the Claude pattern analysis prompt.

    Groups ads by pain point, mechanism, format, and awareness level, then
    calculates total spend + avg ROAS per group. Includes top 3 ads by spend.

    Args:
        ads: List of ad dicts with at least 'name', 'spend', 'roas' fields.
        parsed_names: Optional pre-parsed naming results (from naming_parser).

    Returns:
        Formatted text block to include in the Claude prompt.
    """
    if not ads:
        return ""

    # If no pre-parsed names, try to parse them
    if parsed_names is None:
        try:
            from creative_feedback_loop.naming_parser import parse_ad_name
            parsed_names = [parse_ad_name(ad.get("name", "")) for ad in ads]
        except ImportError:
            parsed_names = [{}] * len(ads)

    # Group ads by key dimensions
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "Pain Point": {},
        "Mechanism (Problem)": {},
        "Ad Format": {},
        "Awareness Level": {},
    }

    for ad, parsed in zip(ads, parsed_names):
        spend = ad.get("spend", 0) or 0
        roas = ad.get("roas", 0) or 0
        name = ad.get("name", "")
        entry = {"name": name, "spend": spend, "roas": roas}

        pp = parsed.get("pain_point", "")
        if pp:
            groups["Pain Point"].setdefault(pp, []).append(entry)

        mech = parsed.get("mechanism_ump", "")
        if mech:
            groups["Mechanism (Problem)"].setdefault(mech, []).append(entry)

        fmt = parsed.get("ad_format", "")
        if fmt:
            groups["Ad Format"].setdefault(fmt, []).append(entry)

        aw = parsed.get("awareness_level", "")
        if aw:
            groups["Awareness Level"].setdefault(aw, []).append(entry)

    # Build text
    lines = ["SPEND DATA BY DIMENSION (use these EXACT dollar amounts in your analysis):", ""]

    for dim_name, values in groups.items():
        if not values:
            continue
        lines.append(f"  {dim_name}:")
        for val_name, val_ads in sorted(values.items(), key=lambda x: -sum(a["spend"] for a in x[1])):
            total_spend = sum(a["spend"] for a in val_ads)
            roas_vals = [a["roas"] for a in val_ads if a["roas"] > 0]
            avg_roas = sum(roas_vals) / len(roas_vals) if roas_vals else 0
            count = len(val_ads)

            if total_spend >= 1000:
                spend_str = f"${total_spend / 1000:.0f}k"
            else:
                spend_str = f"${total_spend:.0f}"

            lines.append(f"    {val_name}: {count} ads, {spend_str} total spend, {avg_roas:.2f}x avg ROAS")

            # Top 3 ads by spend
            top_ads = sorted(val_ads, key=lambda a: a["spend"], reverse=True)[:3]
            for ta in top_ads:
                ta_spend = f"${ta['spend'] / 1000:.0f}k" if ta["spend"] >= 1000 else f"${ta['spend']:.0f}"
                lines.append(f"      - {ta['name']} ({ta_spend}, {ta['roas']:.2f}x)")

        lines.append("")

    lines.append("IMPORTANT: Every opportunity MUST include dollar amounts. Reference specific ad names with their spend and ROAS.")
    return "\n".join(lines)


def _match_opportunity_to_dimension(
    opp: dict[str, Any],
    dimensions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Try to match an opportunity to a specific dimension value by keyword overlap."""
    opp_text = (opp.get("text", "") + " " + opp.get("title", "")).lower()

    best_match = None
    best_score = 0

    for dim in dimensions:
        dim_name = dim.get("name", "").lower()
        for val in dim.get("values", []):
            val_name = val.get("value", "").lower()
            # Simple keyword matching
            score = 0
            if val_name and val_name in opp_text:
                score += 3
            if dim_name and dim_name in opp_text:
                score += 1
            if score > best_score:
                best_score = score
                best_match = val

    return best_match


def format_opportunity_card(opp: dict[str, Any]) -> str:
    """Format a single opportunity as a display string.

    If stats are verified (matched to real dashboard data) AND counts are non-zero,
    shows actual numbers. If both winner_count and loser_count are 0, suppresses
    the stats line entirely (BUG 5 — don't show "Winners: 0 | Losers: 0").
    If unverified, shows score only or nothing.
    """
    title = opp.get("title", "Untitled Opportunity")
    score = opp.get("score", 0)
    stats_verified = opp.get("stats_verified", False)
    winner_count = opp.get("winner_count") or 0
    loser_count = opp.get("loser_count") or 0

    if stats_verified and (winner_count > 0 or loser_count > 0):
        avg_roas = opp.get("avg_roas", 0.0) or 0.0
        total_spend = opp.get("total_spend", 0) or 0
        stats_line = f"Winners: {winner_count} | Losers: {loser_count} | Avg ROAS: {avg_roas:.2f}x"
        if total_spend:
            if total_spend >= 1000:
                stats_line += f" | Spend: ${total_spend / 1000:.0f}k"
            else:
                stats_line += f" | Spend: ${total_spend:.0f}"
        if score:
            stats_line += f" | Score: {score}/100"
    elif score:
        stats_line = f"Score: {score}/100"
    else:
        stats_line = ""

    if stats_line:
        return f"{title}\n{stats_line}"
    return title


# ── Backward-compatible async wrapper for app.py ──────────────────────────────

async def analyze_patterns(  # noqa: RUF029
    ads_data: list,
    dashboard_data: dict,
    priority_prompt: str = "",
    previous_notes: str = "",
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Async wrapper called by app.py. Returns {executive_summary, insights, learnings, hypotheses}."""
    import anthropic
    import re

    if not ads_data:
        return {"executive_summary": "", "insights": [], "learnings": [], "hypotheses": []}

    winners = [a for a in ads_data if a.get("status") == "winner"]
    losers = [a for a in ads_data if a.get("status") == "loser"]
    untested = [a for a in ads_data if a.get("status") == "untested"]

    def _ad_line(ad: dict) -> str:
        ext = ad.get("extraction") or ad.get("naming_extraction") or {}
        mech = ext.get("mechanism", {})
        if isinstance(mech, dict):
            mech = mech.get("ump", "") or ""
        rc = ext.get("root_cause", {})
        if isinstance(rc, dict):
            rc = rc.get("depth", "") or ""
        avatar = ext.get("avatar", {})
        if isinstance(avatar, dict):
            avatar = avatar.get("behavior", "") or ""
        return (
            f"- {ad.get('ad_name', '')} | spend=&#36;{ad.get('spend', 0):.0f} "
            f"roas={ad.get('roas', 0):.2f} | "
            f"pain={ext.get('pain_point','?')} mech={mech or '?'} "
            f"format={ext.get('ad_format','?')} awareness={ext.get('awareness_level','?')} "
            f"root_cause={rc or '?'} avatar={avatar or '?'}"
        )

    spend_ctx = build_spend_context(ads_data)
    winner_spend = sum(float(a.get("spend", 0)) for a in winners)
    loser_spend = sum(float(a.get("spend", 0)) for a in losers)

    prompt = f"""You are a creative strategist analyzing Meta ad performance data for a direct response brand.

YOUR TASK: Find 5-7 multi-dimensional patterns that connect 2-3+ dimensions from the data. Single-dimension insights are BANNED.

DATA:
WINNERS ({len(winners)} ads, ${winner_spend:,.0f} total spend):
{chr(10).join(_ad_line(a) for a in winners[:25]) or 'none'}

LOSERS ({len(losers)} ads, ${loser_spend:,.0f} total spend):
{chr(10).join(_ad_line(a) for a in losers[:25]) or 'none'}

UNTESTED: {len(untested)} ads

SPEND CONTEXT:
{spend_ctx}

{f'OPERATOR PRIORITIES: {priority_prompt}' if priority_prompt else ''}
{f'PREVIOUS NOTES: {previous_notes}' if previous_notes else ''}

RULES FOR INSIGHTS:
1. EVERY insight MUST connect 2-3+ dimensions (pain point + awareness, mechanism + format, avatar + pain point, etc.)
2. EVERY insight MUST include spend and ROAS data for BOTH winning and losing sides
3. EVERY insight MUST name specific ads with their batch numbers, spend, and ROAS
4. Show CONTRAST: "Pattern A wins in context B but loses in context C"
5. Prioritize volume-efficiency ratio: high spend + good ROAS = strongest signal. Low spend = weak signal regardless of ROAS.
6. If a pattern has high spend tolerance AND efficiency, suggest expanding it to other dimensions.
7. "Scale this" is NOT an insight. Show WHY it works by connecting dimensions.

BANNED INSIGHTS (too shallow):
- "Scale kidney campaigns" (single dimension)
- "Problem Aware outperforms Solution Aware" (single dimension)
- "Long Form Static works well" (single dimension, no contrast)
- Any insight without specific ad names and spend data

GOOD INSIGHT EXAMPLE:
"All 6 kidney winners use Problem Aware + RenalLymphaticClogged mechanism + Long Form Static (combined $183k, 1.32x ROAS). All 4 thyroid losers use the SAME lymphatic mechanism but with Solution Aware positioning ($15k, 0.91x). The mechanism works — the awareness level kills it. Test Problem Aware on thyroid scripts."

For each insight provide:
- A clear title (max 15 words)
- The multi-dimensional pattern with specific data
- Confidence: HIGH ($50k+ spend proof) / MEDIUM ($10-50k) / LOW (<$10k)

For your top 3 insights, also suggest 2 expansion opportunities each — how could this winning pattern be applied to OTHER dimension values not yet tested?

Respond with:

EXECUTIVE SUMMARY:
[2-3 sentences connecting the biggest patterns]

OPPORTUNITIES:
1. [Title]
[Pattern detail with spend, ROAS, specific ads, contrast between winners and losers]
Confidence: [HIGH/MEDIUM/LOW] — [reason]
Expansion: [2 expansion ideas]

2. [Title]
...

LEARNINGS:
1. [Learning with specific data: X ads, $Y spend, Z ROAS, hit rate A/B]
2. ...

HYPOTHESES:
1. [What to test] — Expected: [outcome with numbers] — Based on: [specific winning ads] — Risk: [HIGH/MEDIUM/LOW]
2. ...
"""

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    response_text = message.content[0].text

    _SECTION_HEADERS = r"(?:EXECUTIVE SUMMARY|OPPORTUNITIES|LEARNINGS|HYPOTHESES|INSIGHTS)"

    def _extract_section(text: str, header: str) -> str:
        pattern = rf"{header}:?\s*\n(.*?)(?=\n{_SECTION_HEADERS}:|\Z)"
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _parse_bullets(text: str) -> list:
        lines = [ln.lstrip("-•*0123456789. ").strip() for ln in text.splitlines() if ln.strip()]
        return [ln for ln in lines if len(ln) > 5]

    _HYPOTHESIS_PREFIXES = ("test:", "if we", "given ", "expected:", "hypothesis:")

    def _is_hypothesis(item: str) -> bool:
        low = item.lower()
        return any(low.startswith(p) for p in _HYPOTHESIS_PREFIXES) or "expected:" in low

    executive_summary = _extract_section(response_text, "EXECUTIVE SUMMARY")
    # Truncate exec summary before any leaked numbered items (opportunities spill-over)
    _exec_parts = re.split(r'\n\s*\d+[\.\)]\s', executive_summary)
    executive_summary = _exec_parts[0].strip()

    opps_text = _extract_section(response_text, "OPPORTUNITIES")

    if not opps_text:
        # Fall back to everything before LEARNINGS/HYPOTHESES headers, not the full response
        opps_text = re.split(r'\n(?:LEARNINGS|HYPOTHESES|INSIGHTS):', response_text, maxsplit=1, flags=re.IGNORECASE)[0]
    raw_opps = _parse_opportunities_from_text(opps_text)
    if dashboard_data:
        _enrich_from_dashboard(raw_opps, dashboard_data)

    raw_learnings = _parse_bullets(_extract_section(response_text, "LEARNINGS"))
    raw_hypotheses = _parse_bullets(_extract_section(response_text, "HYPOTHESES"))

    # Dedup keys: first 50 chars lowercase of learnings + hypotheses
    learn_keys = {item.lower()[:50] for item in raw_learnings}
    hyp_keys = {item.lower()[:50] for item in raw_hypotheses}

    insights = []
    seen_insight_keys: set = set()
    for opp in raw_opps:
        # Skip if this insight overlaps with a learning or hypothesis (BUG 2)
        opp_key = (opp.get("title", "") or opp.get("text", "")).lower()[:50]
        if opp_key in learn_keys or opp_key in hyp_keys:
            continue
        if opp_key in seen_insight_keys:
            continue
        seen_insight_keys.add(opp_key)

        verified = opp.get("stats_verified", False)
        w = opp.get("winner_count")
        l = opp.get("loser_count")
        r = opp.get("avg_roas")
        if verified and (w or l):
            confidence = "Verified"
        else:
            w = l = r = None
            confidence = "Based on Claude analysis"
        insights.append({
            "title": opp.get("title", ""),
            "detail": opp.get("text", ""),
            "winner_count": w,
            "loser_count": l,
            "avg_roas": r,
            "confidence": confidence,
            "is_baseline": False,
        })

    # Move hypothesis-like items out of learnings; deduplicate hypotheses
    clean_learnings = [item for item in raw_learnings if not _is_hypothesis(item) and item.lower()[:50] not in hyp_keys]
    spilled = [item for item in raw_learnings if _is_hypothesis(item)]
    extra_hyps = [h for h in spilled if h.lower()[:60] not in {h2.lower()[:60] for h2 in raw_hypotheses}]

    return {
        "executive_summary": executive_summary,
        "insights": insights,
        "learnings": clean_learnings,
        "hypotheses": raw_hypotheses + extra_hyps,
    }
