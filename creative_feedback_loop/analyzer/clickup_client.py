"""ClickUp API client for pulling creative tasks from brand spaces.

Flow: workspace → spaces → fuzzy match brand → find 'Creative Team' list → pull all tasks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from thefuzz import fuzz

CLICKUP_API = "https://api.clickup.com/api/v2"
TEAM_ID = "90152194635"


@dataclass
class CreativeTask:
    """A creative task pulled from ClickUp."""
    task_id: str
    name: str
    description: str
    status: str
    url: str
    date_created: Optional[datetime] = None
    date_launched: Optional[datetime] = None
    comments: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)
    gdoc_links: list[str] = field(default_factory=list)
    gdrive_folder_links: list[str] = field(default_factory=list)


def _headers() -> dict[str, str]:
    key = os.environ.get("CLICKUP_API_KEY", "")
    if not key:
        raise ValueError("CLICKUP_API_KEY environment variable is not set")
    return {"Authorization": key, "Content-Type": "application/json"}


def _get(endpoint: str, params: dict | None = None) -> Any:
    """Make a GET request to ClickUp API."""
    url = f"{CLICKUP_API}{endpoint}"
    resp = requests.get(url, headers=_headers(), params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Space discovery ───────────────────────────────────────────────────────────

def get_spaces(team_id: str = TEAM_ID) -> list[dict]:
    """Get all spaces in the workspace."""
    data = _get(f"/team/{team_id}/space", {"archived": "false"})
    return data.get("spaces", [])


def fuzzy_match_space(brand_name: str, spaces: list[dict], threshold: int = 60) -> Optional[dict]:
    """Fuzzy match a brand name to a ClickUp space."""
    best_match = None
    best_score = 0
    for space in spaces:
        space_name = space.get("name", "")
        # Try matching against space name directly
        score = fuzz.token_sort_ratio(brand_name.lower(), space_name.lower())
        if score > best_score:
            best_score = score
            best_match = space
        # Also try partial matching for cases like "Eskiin" in "Eskiin - Tasks"
        partial = fuzz.partial_ratio(brand_name.lower(), space_name.lower())
        if partial > best_score:
            best_score = partial
            best_match = space
    if best_score >= threshold:
        return best_match
    return None


# ── Folder & List discovery ───────────────────────────────────────────────────

def get_folders(space_id: str) -> list[dict]:
    """Get all folders in a space."""
    data = _get(f"/space/{space_id}/folder", {"archived": "false"})
    return data.get("folders", [])


def get_lists_in_folder(folder_id: str) -> list[dict]:
    """Get all lists in a folder."""
    data = _get(f"/folder/{folder_id}/list", {"archived": "false"})
    return data.get("lists", [])


def get_folderless_lists(space_id: str) -> list[dict]:
    """Get lists not in any folder."""
    data = _get(f"/space/{space_id}/list", {"archived": "false"})
    return data.get("lists", [])


def find_creative_lists(space_id: str) -> tuple[Optional[dict], Optional[dict]]:
    """Find both 'Creative Team' and 'Media Buying' lists inside [BRAND] - Tasks folder.

    Returns: (creative_team_list, media_buying_list) — either may be None.
    """
    folders = get_folders(space_id)

    creative_team: Optional[dict] = None
    media_buying: Optional[dict] = None

    # Search Tasks folder first, then all folders as fallback
    tasks_folders = [f for f in folders if "task" in f.get("name", "").lower()]
    search_order = tasks_folders + [f for f in folders if f not in tasks_folders]

    for folder in search_order:
        lists = get_lists_in_folder(folder["id"])
        for lst in lists:
            name_lower = lst.get("name", "").lower()
            if creative_team is None and "creative team" in name_lower:
                creative_team = lst
            if media_buying is None and "media buying" in name_lower:
                media_buying = lst
        if creative_team and media_buying:
            break

    # Fallback: folderless lists
    if not creative_team or not media_buying:
        for lst in get_folderless_lists(space_id):
            name_lower = lst.get("name", "").lower()
            if creative_team is None and "creative team" in name_lower:
                creative_team = lst
            if media_buying is None and "media buying" in name_lower:
                media_buying = lst

    return creative_team, media_buying


# ── Task pulling ──────────────────────────────────────────────────────────────

GDOC_PATTERN = re.compile(r'https://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)')
GDRIVE_FOLDER_PATTERN = re.compile(r'https://drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)')
GDRIVE_LINK_PATTERN = re.compile(r'https://(?:docs|drive)\.google\.com/[^\s\)\"\'<>]+')


def _extract_gdoc_links(text: str) -> tuple[list[str], list[str]]:
    """Extract Google Doc links and Google Drive folder links from text."""
    doc_links = []
    folder_links = []
    if not text:
        return doc_links, folder_links

    # Find all Google Drive/Docs URLs
    all_links = GDRIVE_LINK_PATTERN.findall(text)
    for link in all_links:
        if '/folders/' in link:
            folder_links.append(link)
        elif '/document/d/' in link:
            doc_links.append(link)

    return list(set(doc_links)), list(set(folder_links))


def _parse_custom_fields(raw_fields: list[dict]) -> dict[str, Any]:
    """Parse ClickUp custom fields into a clean dict."""
    result = {}
    target_fields = {
        "ad format", "ad type", "awareness level", "concept level",
        "video ad type", "date launched", "editor", "designer", "cd",
        "editor/designer",
    }
    for cf in raw_fields:
        name = cf.get("name", "").strip()
        if name.lower() in target_fields or any(t in name.lower() for t in target_fields):
            value = cf.get("value")
            # Handle dropdown/label type fields
            if cf.get("type") == "drop_down" and isinstance(value, dict):
                value = value.get("name", value)
            elif cf.get("type") == "labels" and isinstance(value, list):
                value = [v.get("label", v) if isinstance(v, dict) else v for v in value]
            # Handle date fields
            elif cf.get("type") == "date" and value:
                try:
                    value = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    pass
            # Handle type_config for drop_down options
            if cf.get("type") == "drop_down" and isinstance(value, (int, str)):
                options = cf.get("type_config", {}).get("options", [])
                for opt in options:
                    if str(opt.get("orderindex")) == str(value) or opt.get("id") == str(value):
                        value = opt.get("name", value)
                        break
            result[name] = value
    return result


def get_task_comments(task_id: str) -> list[str]:
    """Get all comments for a task."""
    try:
        data = _get(f"/task/{task_id}/comment")
        comments = []
        for c in data.get("comments", []):
            # Comments can have nested text
            text_parts = []
            for item in c.get("comment", []):
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(item["text"])
            comment_text = "".join(text_parts).strip()
            if comment_text:
                comments.append(comment_text)
        return comments
    except Exception:
        return []


def get_tasks(
    list_id: str,
    date_range_days: Optional[int] = None,
    page: int = 0,
) -> list[dict]:
    """Get tasks from a ClickUp list with pagination."""
    params: dict[str, Any] = {
        "archived": "false",
        "include_closed": "true",
        "subtasks": "true",
        "page": str(page),
    }
    data = _get(f"/list/{list_id}/task", params)
    return data.get("tasks", [])


def pull_creative_tasks(
    list_id: str,
    date_range_days: Optional[int] = None,
    fetch_comments: bool = True,
) -> list[CreativeTask]:
    """Pull all creative tasks from a list, with comments and metadata."""
    all_raw_tasks: list[dict] = []
    page = 0
    while True:
        batch = get_tasks(list_id, page=page)
        if not batch:
            break
        all_raw_tasks.extend(batch)
        page += 1
        # ClickUp returns max 100 per page
        if len(batch) < 100:
            break

    tasks: list[CreativeTask] = []
    now = datetime.now(tz=timezone.utc)

    for raw in all_raw_tasks:
        # Parse custom fields
        custom_fields = _parse_custom_fields(raw.get("custom_fields", []))

        # Check date range filter using Date Launched custom field
        date_launched = custom_fields.get("Date Launched")
        if date_range_days and date_launched:
            if isinstance(date_launched, datetime):
                age_days = (now - date_launched).days
                if age_days > date_range_days:
                    continue

        description = raw.get("description", "") or ""

        # Extract Google Doc/Drive links from description
        doc_links, folder_links = _extract_gdoc_links(description)

        # Parse creation date
        date_created = None
        if raw.get("date_created"):
            try:
                date_created = datetime.fromtimestamp(
                    int(raw["date_created"]) / 1000, tz=timezone.utc
                )
            except (ValueError, TypeError, OSError):
                pass

        task = CreativeTask(
            task_id=raw["id"],
            name=raw.get("name", ""),
            description=description,
            status=raw.get("status", {}).get("status", "unknown"),
            url=raw.get("url", ""),
            date_created=date_created,
            date_launched=date_launched if isinstance(date_launched, datetime) else None,
            custom_fields=custom_fields,
            gdoc_links=doc_links,
            gdrive_folder_links=folder_links,
        )

        # Fetch comments
        if fetch_comments:
            task.comments = get_task_comments(raw["id"])
            # Also extract doc links from comments
            for comment in task.comments:
                cdoc_links, cfolder_links = _extract_gdoc_links(comment)
                task.gdoc_links.extend(cdoc_links)
                task.gdrive_folder_links.extend(cfolder_links)
            task.gdoc_links = list(set(task.gdoc_links))
            task.gdrive_folder_links = list(set(task.gdrive_folder_links))

        tasks.append(task)

    return tasks


# ── High-level convenience ────────────────────────────────────────────────────

def find_brand_and_pull_tasks(
    brand_name: str,
    date_range_days: Optional[int] = None,
    fetch_comments: bool = True,
) -> tuple[Optional[str], Optional[str], list[CreativeTask]]:
    """Find a brand space, pull tasks from both Creative Team and Media Buying lists.

    Returns: (space_name, lists_description, tasks)
    """
    import sys

    spaces = get_spaces()
    space = fuzzy_match_space(brand_name, spaces)
    if not space:
        return None, None, []

    creative_list, media_buying_list = find_creative_lists(space["id"])
    if not creative_list and not media_buying_list:
        return space.get("name"), None, []

    all_tasks: list[CreativeTask] = []
    seen_ids: set[str] = set()
    ct_count = 0
    mb_count = 0

    if creative_list:
        ct_tasks = pull_creative_tasks(
            creative_list["id"],
            date_range_days=date_range_days,
            fetch_comments=fetch_comments,
        )
        for t in ct_tasks:
            if t.task_id not in seen_ids:
                seen_ids.add(t.task_id)
                all_tasks.append(t)
        ct_count = len(ct_tasks)

    if media_buying_list:
        mb_tasks = pull_creative_tasks(
            media_buying_list["id"],
            date_range_days=date_range_days,
            fetch_comments=fetch_comments,
        )
        for t in mb_tasks:
            if t.task_id not in seen_ids:
                seen_ids.add(t.task_id)
                all_tasks.append(t)
        mb_count = len(mb_tasks)

    total = len(all_tasks)
    print(
        f"Found {ct_count} tasks from Creative Team + {mb_count} tasks from Media Buying"
        f" = {total} total (after dedup)",
        file=sys.stderr,
    )

    lists_desc = " + ".join(filter(None, [
        creative_list.get("name") if creative_list else None,
        media_buying_list.get("name") if media_buying_list else None,
    ]))
    return space.get("name"), lists_desc, all_tasks
