
from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Callable, Dict, Iterator, Optional

import structlog

logger = structlog.get_logger()

STATE = "state"
KIND_ROUTE = "route"
KIND_SETTING = "setting"
ROUTE = "route"
PANE, EXTERNAL, PEER = "pane", "external", "peer"

Sink = Callable[[str, str, str, str], None]
_sink: Optional[Sink] = None
_context: ContextVar[tuple] = ContextVar("old_names_context", default=(ROUTE, ""))
_declared: Dict[str, set] = {}


def install_sink(sink: Optional[Sink]) -> None:
    global _sink
    _sink = sink


def declare(kind: str, names: "list[str] | tuple[str, ...] | set[str]") -> None:
    _declared.setdefault(kind, set()).update(names)


def declared() -> Dict[str, list]:
    return {kind: sorted(names) for kind, names in _declared.items()}


@contextlib.contextmanager
def using(via: str, caller: str = "") -> Iterator[None]:
    """Mark everything read inside the block as coming ``via`` a pane, an external token, a peer or an import.

    Inputs: via (one of the module's vias); caller (the calling session's tmux name, for the log line only, never counted). Output: a context manager.
    """
    token = _context.set((via, caller))
    try:
        yield
    finally:
        _context.reset(token)


def note(kind: str, name: str) -> None:
    sink = _sink
    if sink is None:
        return
    via, caller = _context.get()
    try:
        sink(kind, name, via, caller)
    except Exception as exc:  # noqa: BLE001
        logger.warning("old_name_count_failed", kind=kind, error_type=type(exc).__name__)
