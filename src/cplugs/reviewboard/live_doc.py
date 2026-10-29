
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Tuple

from src.cplugs.reviewboard import live_rules, revisions
from src.cplugs.reviewboard.errors import BadRequest, NotLive
from src.cplugs.reviewboard.live_requests import LiveBody, LiveCreateBody
from src.cplugs.reviewboard.schema import BASE_SCHEMA_VERSION, MAX_REVISIONS, SCHEMA_ID, LiveDraft, Sidecar

Files = Mapping[str, bytes]
_VOLATILE = ("seq", "updated_at")


def _draft_row(body: LiveBody, viewport: int, seq: int, now: datetime) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    rows, files = revisions.page_rows(body.html, body.views, live_rules.draft_file)
    row: Dict[str, Any] = {"seq": seq, "updated_at": revisions.stamp(now), "summary": body.summary.strip(), "viewport": viewport, "views": rows,
                           "prompts": [p.model_dump(mode="json", by_alias=True) for p in body.prompts],
                           "anchors": [a.model_dump(mode="json", by_alias=True) for a in body.anchors]}
    if body.max_width is not None:
        row["max_width"] = body.max_width
    if body.inline_picks:
        row["inline_picks"] = True
    return row, files


def same_draft(old: LiveDraft, row: Mapping[str, Any]) -> bool:
    stored = old.model_dump(mode="json", by_alias=True)
    return all(stored.get(k) == row.get(k) for k in {*stored, *row} if k not in _VOLATILE)


def first_document(body: LiveCreateBody, slug: str, now: datetime, by: Mapping[str, Any], task: Mapping[str, Any]) -> Tuple[Dict[str, Any], Files]:
    row, files = _draft_row(body, body.viewport, 1, now)
    doc = {"schema": SCHEMA_ID, "schema_version": BASE_SCHEMA_VERSION,
           "board": {"slug": slug, "title": body.title, "kind": body.kind, "created_at": revisions.stamp(now), "created_by": dict(by)},
           "task": dict(task), "revisions": [], "rounds": [],
           "live": {"started_at": revisions.stamp(now), "by": dict(by), "draft": row, "sends": [], "sends_total": 0}, "ext": {}}
    return revisions.with_version(doc), files


def overwrite(current: Sidecar, body: LiveBody, now: datetime, by: Mapping[str, Any]) -> Tuple[Dict[str, Any], Files, bool, bool]:
    live = current.live
    viewport = body.viewport or (live.draft.viewport if live else None) or (current.revisions[-1].viewport if current.revisions else None)
    if viewport is None:
        raise BadRequest("viewport is required for the first draft of a board with no revision")
    seq = live.draft.seq + 1 if live else 1
    row, files = _draft_row(body, viewport, seq, now)
    if live is not None and same_draft(live.draft, row):
        return current.model_dump(mode="json", by_alias=True), {}, False, False
    doc = current.model_dump(mode="json", by_alias=True)
    doc["live"] = {"started_at": live.started_at if live else revisions.stamp(now), "by": live.by.model_dump(mode="json", by_alias=True) if live else dict(by),
                   "draft": row, "sends": doc["live"]["sends"] if live else [], "sends_total": live.sends_total if live else 0}
    return revisions.with_version(doc), files, live is None, True


def draft_matches_newest(current: Sidecar) -> bool:
    if current.live is None or not current.revisions:
        return False
    draft, last = current.live.draft, current.revisions[-1]
    return ([(v.id, v.sha256) for v in draft.views] == [(v.id, v.sha256) for v in last.views] and draft.prompts == last.prompts
            and draft.anchors == last.anchors and draft.summary == last.summary and bool(draft.inline_picks) == bool(last.inline_picks))


def milestone(current: Sidecar, pages: Mapping[str, bytes], name: Optional[str], summary: Optional[str], now: datetime,
              by: Mapping[str, Any]) -> Tuple[Dict[str, Any], Files]:
    if current.live is None:
        raise NotLive("the board is not running live, so there is no draft to bookmark")
    n = len(current.revisions) + 1
    if n > MAX_REVISIONS:
        raise BadRequest(f"a board holds at most {MAX_REVISIONS} revisions")
    draft = current.live.draft
    views, files = [], {}
    for v in draft.views:
        target = revisions.file_name(n, v.id)
        files[target] = pages[v.file]
        views.append({"id": v.id, "label": v.label, "file": target, "sha256": v.sha256, "bytes": v.bytes})
    chosen = (name or "").strip() or f"milestone {sum(1 for r in current.revisions if r.milestone) + 1}"
    row: Dict[str, Any] = {"id": f"r{n}", "n": n, "created_at": revisions.stamp(now), "by": dict(by), "summary": (summary or draft.summary).strip(),
                           "answers_round": None, "viewport": draft.viewport, "views": views, "milestone": chosen,
                           "prompts": [p.model_dump(mode="json", by_alias=True) for p in draft.prompts],
                           "anchors": [a.model_dump(mode="json", by_alias=True) for a in draft.anchors]}
    if draft.max_width is not None:
        row["max_width"] = draft.max_width
    if draft.inline_picks:
        row["inline_picks"] = True
    doc = current.model_dump(mode="json", by_alias=True)
    doc["revisions"].append(row)
    return revisions.with_version(doc), files


def ended(current: Sidecar) -> Dict[str, Any]:
    if current.live is None:
        raise NotLive("the board is not running live")
    doc = current.model_dump(mode="json", by_alias=True)
    doc.pop("live", None)
    return doc
