"""Script Reader — extracts ad scripts/briefs from ClickUp tasks, comments, and Google Docs.

Uses Claude to parse structured creative elements from raw text.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic
import requests

from .clickup_client import CreativeTask

GDOC_ID_PATTERN = re.compile(r'/document/d/([a-zA-Z0-9_-]+)')


@dataclass
class ScriptContent:
    """Parsed script/brief content from a creative task."""
    task_id: str
    task_name: str
    raw_text: str
    source_breakdown: dict[str, str] = field(default_factory=dict)  # source → text
    hooks: list[str] = field(default_factory=list)
    body_copy: str = ""
    pain_point: str = ""
    symptoms: list[str] = field(default_factory=list)
    root_cause: str = ""
    root_cause_depth: str = ""  # surface / cellular / molecular
    mechanism_ump: str = ""  # unique mechanism of problem
    mechanism_ums: str = ""  # unique mechanism of solution
    avatar: str = ""
    ad_format: str = ""
    awareness_level: str = ""
    emotional_triggers: list[str] = field(default_factory=list)
    language_patterns: list[str] = field(default_factory=list)
    cta_type: str = ""
    lead_type: str = ""  # story, problem-solution, testimonial, etc.
    manual_review_links: list[str] = field(default_factory=list)
    folder_links: list[str] = field(default_factory=list)
    no_content_found: bool = False


def fetch_google_doc_text(doc_url: str) -> tuple[Optional[str], bool]:
    """Fetch text from a Google Doc via export URL.

    Returns: (text_content, success)
    If fails (403/private), returns (None, False).
    """
    match = GDOC_ID_PATTERN.search(doc_url)
    if not match:
        return None, False

    doc_id = match.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"

    try:
        resp = requests.get(export_url, timeout=15)
        if resp.status_code == 200:
            text = resp.text.strip()
            if text and len(text) > 20:  # Minimum viable content
                return text, True
        return None, False
    except Exception:
        return None, False


def gather_raw_content(task: CreativeTask) -> tuple[str, dict[str, str], list[str], list[str]]:
    """Gather all raw text content from a task's three sources.

    Returns: (combined_text, source_breakdown, manual_review_links, folder_links)
    """
    sources: dict[str, str] = {}
    manual_review: list[str] = []
    folder_links: list[str] = list(task.gdrive_folder_links)

    # Source 1: Task description
    if task.description and len(task.description.strip()) > 10:
        sources["description"] = task.description.strip()

    # Source 2: Task comments
    if task.comments:
        comment_text = "\n\n---\n\n".join(task.comments)
        if len(comment_text.strip()) > 10:
            sources["comments"] = comment_text.strip()

    # Source 3: Google Docs
    for doc_url in task.gdoc_links:
        text, success = fetch_google_doc_text(doc_url)
        if success and text:
            sources[f"gdoc:{doc_url}"] = text
        elif not success:
            manual_review.append(doc_url)

    combined = "\n\n=== SECTION BREAK ===\n\n".join(sources.values())
    return combined, sources, manual_review, folder_links


EXTRACTION_PROMPT = """You are analyzing an ad creative brief/script. Extract the following components from the text.
If a component is not found, write "Not found" for that field.

The text comes from a creative task named: "{task_name}"
Custom fields from the task management system: {custom_fields}

TEXT TO ANALYZE:
---
{text}
---

Extract these components and return them in EXACTLY this format (keep the labels, fill in values):

HOOKS: [List each hook on a new line, typically 3 per script. If multiple versions, list all.]
BODY_COPY: [The main body/script text after the hook]
PAIN_POINT: [The primary pain point targeted]
SYMPTOMS: [Comma-separated list of physical symptoms/experiences mentioned]
ROOT_CAUSE: [The root cause presented]
ROOT_CAUSE_DEPTH: [One of: surface, cellular, molecular — based on how deep the science goes]
MECHANISM_UMP: [Unique Mechanism of Problem — why the problem exists]
MECHANISM_UMS: [Unique Mechanism of Solution — why this solution works]
AVATAR: [Description of the target avatar — specific habits, life patterns, why previous solutions failed]
AD_FORMAT: [One of: UGC, AI, VSL, Long Form Static, Short Form Static, Carousel, other — check task name and content]
AWARENESS_LEVEL: [One of: Unaware, Problem Aware, Solution Aware, Product Aware, Most Aware]
EMOTIONAL_TRIGGERS: [Comma-separated list of emotional triggers used]
LANGUAGE_PATTERNS: [Comma-separated list of notable phrases, power words, or recurring language patterns]
CTA_TYPE: [The type of call-to-action used]
LEAD_TYPE: [One of: Story, Problem-Solution, Testimonial, Listicle, News/Discovery, Challenge, Question, other]"""


def extract_script_components(
    task: CreativeTask,
    raw_text: str,
    custom_fields: dict[str, Any],
) -> dict[str, Any]:
    """Use Claude to extract structured script components from raw text."""
    client = anthropic.Anthropic()

    cf_str = ", ".join(f"{k}: {v}" for k, v in custom_fields.items() if v)

    prompt = EXTRACTION_PROMPT.format(
        task_name=task.name,
        custom_fields=cf_str or "None available",
        text=raw_text[:12000],  # Limit to avoid token overflow
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text
    return _parse_extraction_response(response_text)


def _parse_extraction_response(text: str) -> dict[str, Any]:
    """Parse Claude's structured extraction response."""
    result: dict[str, Any] = {}
    field_map = {
        "HOOKS": "hooks",
        "BODY_COPY": "body_copy",
        "PAIN_POINT": "pain_point",
        "SYMPTOMS": "symptoms",
        "ROOT_CAUSE": "root_cause",
        "ROOT_CAUSE_DEPTH": "root_cause_depth",
        "MECHANISM_UMP": "mechanism_ump",
        "MECHANISM_UMS": "mechanism_ums",
        "AVATAR": "avatar",
        "AD_FORMAT": "ad_format",
        "AWARENESS_LEVEL": "awareness_level",
        "EMOTIONAL_TRIGGERS": "emotional_triggers",
        "LANGUAGE_PATTERNS": "language_patterns",
        "CTA_TYPE": "cta_type",
        "LEAD_TYPE": "lead_type",
    }

    lines = text.split("\n")
    current_key = None
    current_value: list[str] = []

    for line in lines:
        matched = False
        for label, key in field_map.items():
            if line.strip().startswith(f"{label}:"):
                # Save previous
                if current_key:
                    result[current_key] = "\n".join(current_value).strip()
                current_key = key
                current_value = [line.strip()[len(label) + 1:].strip()]
                matched = True
                break
        if not matched and current_key:
            current_value.append(line)

    # Save last field
    if current_key:
        result[current_key] = "\n".join(current_value).strip()

    # Post-process list fields
    for list_field in ["hooks", "symptoms", "emotional_triggers", "language_patterns"]:
        raw = result.get(list_field, "")
        if isinstance(raw, str):
            # Split by newlines or commas
            items = []
            for item in re.split(r'[\n,]', raw):
                item = item.strip().lstrip("- •·123456789.)")
                if item and item.lower() != "not found":
                    items.append(item.strip())
            result[list_field] = items

    # Clean "Not found" values
    for k, v in result.items():
        if isinstance(v, str) and v.lower().strip() == "not found":
            result[k] = ""

    return result


def read_script(task: CreativeTask, use_claude: bool = True) -> ScriptContent:
    """Read and parse a script/brief from a creative task.

    Checks all three sources: description, comments, Google Docs.
    Optionally uses Claude to extract structured components.
    """
    raw_text, sources, manual_review, folder_links = gather_raw_content(task)

    content = ScriptContent(
        task_id=task.task_id,
        task_name=task.name,
        raw_text=raw_text,
        source_breakdown=sources,
        manual_review_links=manual_review,
        folder_links=folder_links,
    )

    if not raw_text or len(raw_text.strip()) < 20:
        content.no_content_found = True
        return content

    if use_claude and raw_text.strip():
        try:
            extracted = extract_script_components(task, raw_text, task.custom_fields)
            content.hooks = extracted.get("hooks", [])
            content.body_copy = extracted.get("body_copy", "")
            content.pain_point = extracted.get("pain_point", "")
            content.symptoms = extracted.get("symptoms", [])
            content.root_cause = extracted.get("root_cause", "")
            content.root_cause_depth = extracted.get("root_cause_depth", "")
            content.mechanism_ump = extracted.get("mechanism_ump", "")
            content.mechanism_ums = extracted.get("mechanism_ums", "")
            content.avatar = extracted.get("avatar", "")
            content.ad_format = extracted.get("ad_format", "") or task.custom_fields.get("Ad Format", "")
            content.awareness_level = (
                extracted.get("awareness_level", "")
                or task.custom_fields.get("Awareness Level", "")
            )
            content.emotional_triggers = extracted.get("emotional_triggers", [])
            content.language_patterns = extracted.get("language_patterns", [])
            content.cta_type = extracted.get("cta_type", "")
            content.lead_type = extracted.get("lead_type", "")
        except Exception as e:
            # If Claude extraction fails, we still have raw text
            content.no_content_found = False

    return content


def read_all_scripts(
    tasks: list[CreativeTask],
    use_claude: bool = True,
    progress_callback: Any = None,
) -> list[ScriptContent]:
    """Read scripts from all tasks. Returns list of ScriptContent."""
    results: list[ScriptContent] = []
    for i, task in enumerate(tasks):
        if progress_callback:
            progress_callback(i, len(tasks), task.name)
        content = read_script(task, use_claude=use_claude)
        results.append(content)
    return results
