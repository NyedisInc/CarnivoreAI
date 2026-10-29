
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import structlog

from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

TOPIC = "command"
KEEP = 20
FRESH_SECONDS = 15.0
SCROLL_TOP, FOLD = "scroll_top", "fold"
FOLD_ACTIONS = ("fold", "unfold", "close")

_lock = threading.Lock()
_log: Dict[str, List[Dict[str, Any]]] = {}
_seq: Dict[str, int] = {}


def _key(ctx: CplugContext) -> str:
    return str(ctx.storage.path)


def send(ctx: CplugContext, kind: str, **args: Any) -> Dict[str, Any]:
    key = _key(ctx)
    with _lock:
        seq = _seq.get(key, 0) + 1
        _seq[key] = seq
        command = {"seq": seq, "kind": kind, "at": time.monotonic(), **args}
        _log[key] = (_log.get(key, []) + [command])[-KEEP:]
    try:
        ctx.notify(TOPIC)
    except (RuntimeError, ValueError) as exc:
        ctx.log.warning("tmdevtools_notify_failed", error=str(exc))
    return dict(command)


def since(ctx: CplugContext, after: Optional[int]) -> List[Dict[str, Any]]:
    now = time.monotonic()
    with _lock:
        found = list(_log.get(_key(ctx), []))
    out = []
    for command in found:
        age = now - command["at"]
        if (after is not None and command["seq"] > after) or (after is None and age <= FRESH_SECONDS):
            out.append({**{k: v for k, v in command.items() if k != "at"}, "age": round(age, 1)})
    return out


def latest(ctx: CplugContext) -> int:
    with _lock:
        return _seq.get(_key(ctx), 0)


def reset() -> None:
    with _lock:
        _log.clear()
        _seq.clear()
