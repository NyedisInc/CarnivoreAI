
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from src.cplugs.reviewboard import document, rules
from src.cplugs.reviewboard.schema import BASE_SCHEMA_VERSION, SCHEMA_ID, Sidecar

MAPPED_KEYS = frozenset({"mockup", "task", "huddle_item_id", "revision", "created", "kind", "revisions", "notes", "views", "choices"})
CONVERTER = "convert-legacy"
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ROUND_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "carnivore.reviewboard.legacy")


class LegacyError(ValueError):
    pass


@dataclass(frozen=True)
class Converted:

    sidecar: Sidecar
    files: Dict[str, bytes]


def _time(value: Any, where: str) -> str:
    if isinstance(value, str) and _DATE.match(value):
        return f"{value}T00:00:00Z"
    if isinstance(value, str) and re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", value):
        return value
    raise LegacyError(f"{where} is not a date")


def _kind(old: Any) -> str:
    text = old if isinstance(old, str) else ""
    for kind in ("mockup", "flowchart", "copy"):
        if text.startswith(kind):
            return kind
    return "other"


def _views(old: Mapping[str, Any]) -> List[Dict[str, str]]:
    mockup = old.get("mockup")
    if not isinstance(mockup, str) or not mockup.endswith(".html"):
        raise LegacyError("the old sidecar names no mockup page")
    pages = old.get("views") or [{"page": mockup, "what": old.get("task") or mockup}]
    stem = mockup[: -len(".html")]
    out: List[Dict[str, str]] = []
    for page in pages:
        name = page.get("page") if isinstance(page, dict) else None
        if not isinstance(name, str) or not name.endswith(".html") or "/" in name:
            raise LegacyError(f"view {page!r} names no page in the sidecar's folder")
        own = name[: -len(".html")]
        view_id = "main" if name == mockup else re.sub(r"[^a-z0-9-]+", "-", own[len(stem) + 1:] if own.startswith(f"{stem}-") else own).strip("-")
        out.append({"id": view_id, "page": name, "label": str(page.get("what") or view_id)[:120]})
    out.sort(key=lambda v: v["id"] != "main")
    if not out or out[0]["id"] != "main":
        raise LegacyError(f"the mockup page {mockup} is not among the views")
    return out


def _revisions(old: Mapping[str, Any], views: List[Dict[str, Any]], viewport: int) -> List[Dict[str, Any]]:
    olds = old.get("revisions")
    if not isinstance(olds, list) or not olds:
        raise LegacyError("the old sidecar lists no revisions")
    if old.get("revision") not in (None, len(olds)) or [r.get("revision") for r in olds] != list(range(1, len(olds) + 1)):
        raise LegacyError("the old revisions do not run 1, 2, ... to the current revision")
    if old.get("choices"):
        raise LegacyError("the old sidecar has choices; converting them is not built (none existed when this was written)")
    rows = []
    for rev in olds:
        n = rev["revision"]
        newest = n == len(olds)
        commit = old.get("source_commit") if newest and isinstance(old.get("source_commit"), str) else None
        rows.append({"id": f"r{n}", "n": n, "created_at": _time(rev.get("date") or old.get("created"), f"revision {n} date"),
                     "by": {"actor": rev.get("by") or "claude"}, "summary": rev.get("summary"), "answers_round": None,
                     "source_commit": commit, "viewport": viewport,
                     "views": [{k: v[k] for k in ("id", "label", "file", "sha256", "bytes")} for v in views],
                     "prompts": [], "anchors": [], "ext": {} if newest else {rules.LEGACY_EXT: {"v": 1, "reconstructed": True}}})
    return rows


def _rounds(old: Mapping[str, Any], slug: str, revision: str, item_id: int) -> List[Dict[str, Any]]:
    rows = []
    for i, note in enumerate(old.get("notes") or [], start=1):
        if not isinstance(note, dict) or not isinstance(note.get("verbatim"), str) or not note["verbatim"].strip():
            raise LegacyError(f"note {i} has no verbatim text")
        sent = _time(note.get("date") or old.get("created"), f"note {i} date")
        rows.append({"id": f"n{i}", "n": i, "revision": revision,
                     "client_round_id": str(uuid.uuid5(_ROUND_NAMESPACE, f"{slug}:{i}")), "sent_at": sent,
                     "by": note.get("by") or "joe", "context": {}, "answers": [], "anchor_notes": [], "note": note["verbatim"],
                     "unanswered": [], "delivery": {"state": "posted", "item_id": item_id, "at": sent},
                     "ext": {"legacy": {"v": 1, **{k: v for k, v in note.items() if k not in ("verbatim", "by")}}}})
    return rows


def convert(old: Mapping[str, Any], *, slug: str, item_id: int, computer: str, viewport: int, now: str,
            read_page: Callable[[str], bytes], github_issue: Optional[str] = None, task_list: Optional[str] = None) -> Converted:
    views = _views(old)
    newest = len(old.get("revisions") or [])
    files: Dict[str, bytes] = {}
    for view in views:
        data = read_page(view["page"])
        view["file"] = rules.view_file(max(newest, 1), view["id"])
        view["sha256"], view["bytes"] = hashlib.sha256(data).hexdigest(), len(data)
        files[view["file"]] = data
    revisions = _revisions(old, views, viewport)
    created = _time(old.get("created"), "created")
    previous = old.get("huddle_item_id")
    history = []
    if isinstance(previous, int) and previous != item_id:
        history.append({"item_id": item_id, "computer": computer, "from": previous, "at": now, "by": CONVERTER,
                        "note": f"the old sidecar named item {previous}; the task is {item_id}"})
    title = old.get("task") if isinstance(old.get("task"), str) else slug
    raw = {
        "schema": SCHEMA_ID, "schema_version": BASE_SCHEMA_VERSION,
        "board": {"slug": slug, "title": title[:120], "kind": _kind(old.get("kind")), "created_at": created,
                  "created_by": {"actor": "claude"}},
        "task": {"item_id": item_id, "list": task_list, "computer": computer, "github_issue": github_issue,
                 "title_at_link": title[:200], "linked_at": created, "history": history},
        "revisions": revisions,
        "rounds": _rounds(old, slug, revisions[-1]["id"], item_id),
        "ext": {"legacy": {"v": 1, "kind": old.get("kind"), "huddle_item_id": previous,
                           **{k: v for k, v in old.items() if k not in MAPPED_KEYS}}},
    }
    return Converted(sidecar=document.parse_sidecar(raw), files=files)
