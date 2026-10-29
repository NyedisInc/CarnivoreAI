
from __future__ import annotations

import json
from contextlib import closing
from typing import Any, Dict, Optional, Tuple

from src.cplugs.huddle import files
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.sdk.sandboxed_html import view_headers

MAX_BYTES = 2 * 1024 * 1024
MAX_TITLE = 120
MAX_DESCRIPTION = 300
FILE_NAME = "artifact.html"
KEY = "artifact"

VIEW_HEADERS = view_headers(FILE_NAME)


def clean(title: Any, description: Any, html: Any) -> Tuple[str, str, bytes]:
    if not isinstance(title, str) or not title.strip():
        raise TaskManagerInvalid("an artifact needs a title")
    if len(title.strip()) > MAX_TITLE:
        raise TaskManagerInvalid(f"the title is at most {MAX_TITLE} characters")
    if description is None:
        description = ""
    if not isinstance(description, str) or len(description.strip()) > MAX_DESCRIPTION or "\n" in description.strip():
        raise TaskManagerInvalid(f"the description is one line of at most {MAX_DESCRIPTION} characters")
    if not isinstance(html, str) or not html.strip():
        raise TaskManagerInvalid("an artifact needs its html page")
    try:
        data = html.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TaskManagerInvalid("the page is not valid text") from exc
    if len(data) > MAX_BYTES:
        raise TaskManagerInvalid(f"the page is {len(data)} bytes; the limit is {MAX_BYTES} (2 MB)")
    return title.strip(), description.strip(), data


def parts_of(entry: Dict[str, Any], title: str, description: str) -> str:
    meta = {"id": entry["id"], "title": title, "description": description, "size": entry["size"]}
    return json.dumps({"files": [entry], KEY: meta}, ensure_ascii=False)


def meta_of(raw: str) -> Optional[Dict[str, Any]]:
    if not raw or not raw.startswith(files.PARTS_PREFIX) or f'"{KEY}"' not in raw:
        return None
    try:
        meta = json.loads(raw)[KEY]
        return {k: meta[k] for k in ("id", "title", "description", "size")} if isinstance(meta, dict) else None
    except (ValueError, KeyError, TypeError):
        return None


def wire(raw: str) -> Optional[Dict[str, Any]]:
    return meta_of(raw)


def find(storage: Any, item_id: int, file_id: str) -> Optional[Dict[str, Any]]:
    with closing(storage.connect(False)) as conn:
        rows = conn.execute(f"SELECT parts FROM work_messages WHERE item_id = ? AND {files.PARTS_SQL}", (int(item_id),)).fetchall()
    for row in rows:
        meta = meta_of(row["parts"])
        if meta and meta["id"] == file_id:
            return meta
    return None
