
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
    "task": {"item_id": 41, "list": "project:3", "computer": "hostb", "github_issue": "NyedisInc/CarnivoreAI#1700",
             "title_at_link": "Board panel refactor, step 3: bottom bar", "linked_at": "2026-10-13T14:02:11Z", "history": []},
    "revisions": [{
        "id": "r1", "n": 1, "created_at": "2026-10-13T14:02:11Z", "by": {"actor": "claude", "session": "ses_6b001a1c"},
        "summary": "first pass", "answers_round": None, "source_commit": "8ff51de7a", "viewport": 320,
        "views": [{"id": "main", "label": "bar", "file": "r001.html", "sha256": hashlib.sha256(PAGE).hexdigest(), "bytes": len(PAGE)}],
        "prompts": [
            {"id": "layout", "kind": "choice", "label": "which button row",
             "options": [{"id": "a", "label": "one row"}, {"id": "b", "label": "two rows"}], "anchor": "buttons"},
            {"id": "padding", "kind": "check", "label": "padding under the input looks right"},
            {"id": "extra", "kind": "question", "label": "anything missing?"}],
        "anchors": [{"id": "send", "label": "send button"}, {"id": "buttons", "label": "button row"}]}],
    "rounds": [{
        "id": "n1", "n": 1, "revision": "r1", "client_round_id": "8da2d99b-6bec-416f-850a-e4d075a649e6",
        "sent_at": "2026-10-13T14:20:40Z", "by": "joe", "context": {"theme": "dracula", "width": 412, "fit": "actual", "view": "main"},
        "answers": [{"prompt": "layout", "options": ["b"], "note": ""}, {"prompt": "padding", "checked": True, "note": ""},
                    {"prompt": "extra", "text": "the count icon needs the warning color", "note": ""}],
        "anchor_notes": [{"anchor": "send", "text": "too close to the edge"}], "note": "closer, keep going", "unanswered": [],
        "delivery": {"state": "posted", "item_id": 41, "message_id": 2481, "at": "2026-10-13T14:20:41Z"}}],
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
