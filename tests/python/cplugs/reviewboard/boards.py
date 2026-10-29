
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from src.cplugs.reviewboard import document
from src.cplugs.reviewboard.scan import MARKER

PAGE = b"<!doctype html><title>bar</title><div data-rb-anchor='send'>send</div>\n"

SIDECAR: Dict[str, Any] = {
    "schema": "carnivore.reviewboard.sidecar", "schema_version": 1,
    "board": {"slug": "20261013-bottom-bar", "title": "bottom bar", "kind": "mockup", "created_at": "2026-10-13T14:02:11Z",
              "created_by": {"actor": "claude", "session": "ses_6b001a1c", "label": "Carnivore - Reorg"}},
    "task": {"item_id": 526, "list": "project:18", "computer": "mac-mini-m4", "github_issue": "Harbor666/CarnivoreAIDev#1700",
             "title_at_link": "Task Manager rebuild, Part 3: bottom bar", "linked_at": "2026-10-13T14:02:11Z", "history": []},
    "revisions": [{
        "id": "r1", "n": 1, "created_at": "2026-10-13T14:02:11Z", "by": {"actor": "claude", "session": "ses_6b001a1c"},
        "summary": "first pass", "answers_round": None, "source_commit": "e9f097608", "viewport": 320,
        "views": [{"id": "main", "label": "bar", "file": "r001.html", "sha256": hashlib.sha256(PAGE).hexdigest(), "bytes": len(PAGE)}],
        "prompts": [
            {"id": "layout", "kind": "choice", "label": "which button row",
             "options": [{"id": "a", "label": "one row"}, {"id": "b", "label": "two rows"}], "anchor": "buttons"},
            {"id": "padding", "kind": "check", "label": "padding under the input looks right"},
            {"id": "extra", "kind": "question", "label": "anything missing?"}],
        "anchors": [{"id": "send", "label": "send button"}, {"id": "buttons", "label": "button row"}]}],
    "rounds": [{
        "id": "n1", "n": 1, "revision": "r1", "client_round_id": "6f1d2c1e-8b3e-4d55-9a2b-1c3d4e5f6a7b",
        "sent_at": "2026-10-13T14:20:40Z", "by": "joe", "context": {"theme": "dracula", "width": 412, "fit": "actual", "view": "main"},
        "answers": [{"prompt": "layout", "options": ["b"], "note": ""}, {"prompt": "padding", "checked": True, "note": ""},
                    {"prompt": "extra", "text": "the count icon needs the warning color", "note": ""}],
        "anchor_notes": [{"anchor": "send", "text": "too close to the edge"}], "note": "closer, keep going", "unanswered": [],
        "delivery": {"state": "posted", "item_id": 526, "message_id": 2481, "at": "2026-10-13T14:20:41Z"}}],
    "ext": {},
}


def sidecar(**changes: Any) -> Dict[str, Any]:
    raw = copy.deepcopy(SIDECAR)
    raw.update(changes)
    return raw


def make_root(tmp: Path) -> Path:
    root = tmp / "boards"
    root.mkdir()
    (root / MARKER).write_text("marker\n")
    return root


def make_board(root: Path, raw: Dict[str, Any] = SIDECAR, canonical: bool = True) -> Path:
    folder = root / raw["board"]["slug"]
    folder.mkdir()
    (folder / "r001.html").write_bytes(PAGE)
    text = document.canonical_text(document.parse_sidecar(raw)) if canonical else json.dumps(raw)
    (folder / document.SIDECAR_FILE).write_text(text, encoding="utf-8")
    return folder
