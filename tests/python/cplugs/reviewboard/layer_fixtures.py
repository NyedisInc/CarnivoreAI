
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict

from tests.python.cplugs.reviewboard.boards import PAGE, SIDECAR

OPTIONS = [{"id": "a", "label": "alpha"}, {"id": "b", "label": "bravo"}, {"id": "c", "label": "charlie"}]

QUESTIONS: Dict[str, Any] = {
    "kind": "questions", "v": 1, "title": "layout questions", "intro": "answer what you can", "placement": "inline",
    "items": [
        {"id": "keep-rail", "label": "keep the rail?", "kind": "yesno", "anchor": "send", "required": True},
        {"id": "dense", "label": "dense rows", "kind": "toggle", "default": False},
        {"id": "density", "label": "density", "kind": "choice", "group": "look", "options": OPTIONS, "default": "b"},
        {"id": "panels", "label": "panels", "kind": "multi", "help": "pick two at most", "options": OPTIONS, "min": 1, "max": 2, "default": ["a"]},
        {"id": "order", "label": "order them", "kind": "rank", "options": OPTIONS, "default": ["c", "b", "a"]},
        {"id": "name", "label": "name", "kind": "text", "placeholder": "a name", "default": "x"},
        {"id": "why", "label": "why", "kind": "longtext"},
        {"id": "size", "label": "size", "kind": "number", "min": 1, "max": 10, "step": 0.5, "unit": "px", "slider": True, "default": 2.5},
        {"id": "due", "label": "due", "kind": "date", "min": "2026-10-01", "max": "2026-12-31", "default": "2026-10-20"},
    ],
}

ROWS: Dict[str, Any] = {
    "kind": "rows", "v": 1, "title": "alex watch", "placement": "float", "pick": "one",
    "choices": [{"id": "ok", "label": "ok", "tone": "ok"}, {"id": "later", "label": "later", "tone": "later"}],
    "rows": [
        {"id": "aw-001", "title": "first row", "tag": "NEW", "lines": [{"label": "now", "text": "it works"}], "meta": "e9f0976", "group": "NEW (2)",
         "anchor": "send", "suggest": "ok"},
        {"id": "aw-002", "title": "second row", "choices": [{"id": "keep", "label": "keep"}, {"id": "drop", "label": "drop", "tone": "push"}], "default": "keep"},
    ],
}


def layer_sidecar(layer: Dict[str, Any], **revision: Any) -> Dict[str, Any]:
    raw = copy.deepcopy(SIDECAR)
    row = raw["revisions"][0]
    row.update(payload_mode=True, prompts=[], layer=copy.deepcopy(layer))
    row.update(revision)
    row["views"][0].update(sha256=hashlib.sha256(PAGE).hexdigest(), bytes=len(PAGE))
    raw["rounds"] = []
    return raw
