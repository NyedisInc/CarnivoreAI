
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from src.cplugs.reviewboard.errors import BadRequest
from src.cplugs.reviewboard.layers.models import CanvasLayer
from src.cplugs.reviewboard.layers.shell import shell_page
from src.cplugs.reviewboard.requests import CreateBody, RevisionBody
from src.cplugs.reviewboard.schema import BASE_SCHEMA_VERSION, MAX_REVISIONS, MAX_VIEW_BYTES, SCHEMA_ID, SCHEMA_VERSION, Sidecar

MAIN_VIEW = "main"
MAIN_LABEL = "main"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
Files = Mapping[str, bytes]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stamp(now: datetime) -> str:
    return now.strftime(TIME_FORMAT)


def file_name(n: int, view_id: str) -> str:
    return f"r{n:03d}.html" if view_id == MAIN_VIEW else f"r{n:03d}--{view_id}.html"


def page_rows(main: str, views: List[Any], namer: Callable[[str], str]) -> Tuple[List[Dict[str, Any]], Dict[str, bytes]]:
    pages = [(MAIN_VIEW, MAIN_LABEL, main)] + [(v.id, v.label, v.html) for v in views]
    ids = [p[0] for p in pages]
    if len(set(ids)) != len(ids) or (views and MAIN_VIEW in [v.id for v in views]):
        raise BadRequest("every view needs its own id, and main is the first page (html), not a views entry")
    rows: List[Dict[str, Any]] = []
    files: Dict[str, bytes] = {}
    for view_id, label, html in pages:
        data = html.encode("utf-8")
        if len(data) > MAX_VIEW_BYTES:
            raise BadRequest(f"the {view_id} page is {len(data)} bytes; a page is at most {MAX_VIEW_BYTES}")
        name = namer(view_id)
        files[name] = data
        rows.append({"id": view_id, "label": label, "file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return rows, files


def _pages(body: RevisionBody, n: int) -> Tuple[List[Dict[str, Any]], Dict[str, bytes]]:
    main = body.html if body.html is not None else shell_page(body.layer.title)
    return page_rows(main, body.views, lambda view_id: file_name(n, view_id))


def _revision(body: RevisionBody, n: int, viewport: int, now: datetime, by: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    views, files = _pages(body, n)
    row = {"id": f"r{n}", "n": n, "created_at": stamp(now), "by": dict(by), "summary": body.summary.strip(),
           "answers_round": body.answers_round, "viewport": viewport, "views": views,
           "prompts": [p.model_dump(mode="json", by_alias=True) for p in body.prompts],
           "anchors": [a.model_dump(mode="json", by_alias=True) for a in body.anchors]}
    if body.source_commit:
        row["source_commit"] = body.source_commit
    if body.max_width is not None and body.layer is None:
        row["max_width"] = body.max_width
    if body.inline_picks:
        row["inline_picks"] = True
    if body.payload_mode or body.layer is not None:
        row["payload_mode"] = True
    if body.layer is not None and not isinstance(body.layer, CanvasLayer):
        row["layer"] = body.layer.model_dump(mode="json", by_alias=True)
    return row, files


def with_version(doc: Dict[str, Any]) -> Dict[str, Any]:
    if doc.get("live") is not None or any(r.get("milestone") is not None or r.get("inline_picks") is not None for r in doc.get("revisions", [])):
        doc["schema_version"] = SCHEMA_VERSION
    return doc


def first_document(body: CreateBody, slug: str, now: datetime, by: Mapping[str, Any], task: Mapping[str, Any]) -> Tuple[Dict[str, Any], Files]:
    row, files = _revision(body, 1, body.viewport, now, by)
    doc = {"schema": SCHEMA_ID, "schema_version": BASE_SCHEMA_VERSION,
           "board": {"slug": slug, "title": body.title, "kind": body.kind, "created_at": stamp(now), "created_by": dict(by)},
           "task": dict(task), "revisions": [row], "rounds": [], "ext": {}}
    return with_version(doc), files


def next_document(current: Sidecar, body: RevisionBody, now: datetime, by: Mapping[str, Any]) -> Tuple[Dict[str, Any], Files]:
    n = len(current.revisions) + 1
    if n > MAX_REVISIONS:
        raise BadRequest(f"a board holds at most {MAX_REVISIONS} revisions")
    viewport: Optional[int] = body.viewport or (current.revisions[-1].viewport if current.revisions else None)
    if viewport is None:
        raise BadRequest("viewport is required for the first revision")
    row, files = _revision(body, n, viewport, now, by)
    doc = current.model_dump(mode="json", by_alias=True)
    doc["revisions"].append(row)
    return with_version(doc), files
