"""Script reader — reads ad scripts from ClickUp task descriptions or Google Docs."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


def read_scripts_from_tasks(tasks_with_ads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read scripts from matched ClickUp tasks.

    For each matched ad that has a ClickUp task, extract the script from:
    1. Task description (primary)
    2. Google Docs link in custom fields (if description is empty)

    Args:
        tasks_with_ads: List of dicts with 'ad', 'clickup_task', 'classification' keys.

    Returns:
        Same list enriched with 'script' key.
    """
    enriched = []
    scripts_found = 0

    for item in tasks_with_ads:
        task = item.get("clickup_task")
        script = ""

        if task:
            # Try task description first
            desc = getattr(task, "script", "") or getattr(task, "description", "") or ""
            if desc and len(desc.strip()) > 20:
                script = desc.strip()
            else:
                # Check custom fields for Google Docs link
                custom = getattr(task, "custom_fields", {}) or {}
                for field_name, field_val in custom.items():
                    if isinstance(field_val, str) and "docs.google.com" in field_val:
                        script = _fetch_google_doc(field_val)
                        break

        if script:
            scripts_found += 1

        item["script"] = script
        enriched.append(item)

    logger.info(f"Scripts read: {scripts_found}/{len(tasks_with_ads)} tasks have scripts")
    return enriched


def _fetch_google_doc(url: str) -> str:
    """Fetch plain text from a Google Docs URL.

    Uses the /export?format=txt endpoint which works for publicly shared docs.
    """
    try:
        import requests

        # Convert sharing URL to export URL
        match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
        if not match:
            logger.warning(f"Cannot parse Google Docs ID from: {url}")
            return ""

        doc_id = match.group(1)
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"

        resp = requests.get(export_url, timeout=15)
        if resp.status_code == 200:
            text = resp.text.strip()
            logger.info(f"Fetched Google Doc ({len(text)} chars)")
            return text
        else:
            logger.warning(f"Google Doc fetch failed: HTTP {resp.status_code}")
            return ""
    except Exception as e:
        logger.warning(f"Google Doc fetch error: {e}")
        return ""
