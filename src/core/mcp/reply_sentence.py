
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any, Dict, Optional

from src.core.stream_redactor import redact_whole

META_KEY = "carnivore_sentence"
NAME_ARGS = ("name", "label", "title", "target")
VERBS: Dict[str, str] = {
    "list": "listed", "get": "read", "read": "read", "create": "created", "add": "added", "remove": "removed",
    "delete": "deleted", "set": "set", "update": "updated", "send": "sent", "say": "said", "reply": "replied to",
    "start": "started", "stop": "stopped", "restart": "restarted", "spawn": "started", "wake": "woke", "wait": "waited on",
    "answer": "answered", "open": "opened", "show": "showed", "search": "searched", "adopt": "adopted", "move": "moved",
    "archive": "archived", "rename": "renamed", "join": "joined", "leave": "left", "put": "saved", "deal": "dealt",
    "close": "closed", "finish": "finished", "pass": "passed", "report": "reported", "promote": "promoted",
    "off": "turned off", "on": "turned on", "use": "switched", "check": "checked", "install": "installed",
    "request": "requested", "retag": "retagged", "declare": "declared", "export": "exported", "import": "imported",
    "grant": "granted", "release": "released", "withdraw": "withdrew", "forget": "forgot", "remember": "saved",
    "ask": "asked", "run": "ran", "sync": "synced", "cancel": "canceled", "reconnect": "reconnected", "recreate": "recreated",
    "resume": "resumed", "status": "checked the status of", "lookup": "looked up", "explain": "explained", "profile": "profiled",
}
CREATE_LIKE = frozenset({"created", "added", "started"})
_SPACE = re.compile(r"\s+")
_NAMES: ContextVar[Optional[Dict[str, str]]] = ContextVar("carnivore_sentence_names", default=None)


def begin_call() -> None:
    _NAMES.set({})


def note_name(target: Any, name: Any) -> None:
    names = _NAMES.get()
    if names is not None and isinstance(target, str) and isinstance(name, str) and name.strip():
        names[target.strip()] = name


def _clean(text: Any, limit: int) -> str:
    line = _SPACE.sub(" ", redact_whole(str(text))).strip()
    return line if len(line) <= limit else line[:limit - 3].rstrip() + "..."


def _name_arg(args: Dict[str, Any]) -> Optional[str]:
    for key in NAME_ARGS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            if key == "target" and (shown := (_NAMES.get() or {}).get(value.strip())):
                return _clean(shown, 60)
            return _clean(value, 60)
    return None


def _phrase(tool: str) -> tuple:
    words = tool.split("_")
    index = next((i for i, w in enumerate(words) if w in VERBS), None)
    if index is None:
        return "ran", " ".join(words)
    noun = " ".join(w for i, w in enumerate(words) if i != index)
    if noun and not noun.endswith("s") and VERBS[words[index]] != "checked the status of":
        noun = f"a {noun}"
    return VERBS[words[index]], noun


def sentence_for(tool: str, args: Any, result: Dict[str, Any]) -> str:
    args = args if isinstance(args, dict) else {}
    blocks = result.get("content") if isinstance(result, dict) else None
    first = blocks[0].get("text", "") if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict) else ""
    if result.get("isError"):
        return "failed: " + (_clean(first, 140) or f"{tool.replace('_', ' ')} did not complete")
    if '"status": "pending"' in first[:200]:
        return "asked the owner to approve " + tool.replace("_", " ")
    verb, noun = _phrase(tool)
    text = f"{verb} {noun}".strip().lower()
    name = _name_arg(args)
    if name:
        text += f" called {name}" if verb in CREATE_LIKE else f" ({name})"
    return text


def attach(tool: str, args: Any, result: Any) -> Any:
    try:
        blocks = result.get("content") if isinstance(result, dict) else None
        if not isinstance(blocks, list) or (blocks and isinstance(blocks[-1], dict) and (blocks[-1].get("_meta") or {}).get(META_KEY)):
            return result
        blocks.append({"type": "text", "text": sentence_for(tool, args, result), "_meta": {META_KEY: True}})
    except (AttributeError, TypeError, ValueError, IndexError):
        return result
    return result
