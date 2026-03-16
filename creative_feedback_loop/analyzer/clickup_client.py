"""ClickUp API client for pulling creative tasks."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests

from creative_feedback_loop.clickup_matcher import ClickUpTask

logger = logging.getLogger(__name__)


def fetch_clickup_tasks(
    list_id: str,
    api_key: str | None = None,
) -> list[ClickUpTask]:
    """Fetch tasks from a ClickUp list.

    Args:
        list_id: ClickUp list ID.
        api_key: ClickUp API key. Falls back to CLICKUP_API_KEY env var.

    Returns:
        List of ClickUpTask.
    """
    api_key = api_key or os.environ.get("CLICKUP_API_KEY", "")
    if not api_key:
        logger.warning("No ClickUp API key — returning empty task list")
        return []

    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": api_key}
    params: dict[str, Any] = {
        "page": 0,
        "include_closed": "true",
        "subtasks": "true",
    }

    all_tasks: list[ClickUpTask] = []

    while True:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"ClickUp API error: {e}")
            break

        tasks_data = data.get("tasks", [])
        if not tasks_data:
            break

        for t in tasks_data:
            status = t.get("status", {})
            custom_fields = {}
            for cf in t.get("custom_fields", []):
                cf_name = cf.get("name", "")
                cf_val = cf.get("value")
                if cf_name and cf_val is not None:
                    custom_fields[cf_name] = cf_val

            all_tasks.append(ClickUpTask(
                task_id=t.get("id", ""),
                name=t.get("name", ""),
                status=status.get("status", "") if isinstance(status, dict) else str(status),
                script=t.get("description", ""),
                custom_fields=custom_fields,
                url=t.get("url", ""),
            ))

        if data.get("last_page", True):
            break
        params["page"] += 1

    logger.info(f"Fetched {len(all_tasks)} tasks from ClickUp list {list_id}")
    return all_tasks
