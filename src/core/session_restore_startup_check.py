
from __future__ import annotations

import time
from typing import Callable, Dict, Iterable, Mapping, Optional

import structlog

from src.core.attention.pane_markers import RESTING_PROMPT_MARKER
from src.core.attention.pane_prompt_box import input_box_drawn
from src.core.attention.registry_record import REG_OK
from src.core.attention.registry_index import read_registry_index, registry_for_session
from src.core.session_startup_gate import detect_startup_prompt
from src.core.session_startup_gate_ledger import capture_pane_tail

logger = structlog.get_logger()

CHECK_WINDOW_SECONDS: float = 5.0
CHECK_INTERVAL_SECONDS: float = 0.75
CHECK_TAIL_LINES: int = 40

STARTUP_PROMPT_WORDS: str = (
    'reopened - waiting on the folder trust prompt: open it and choose "Yes, I trust this folder"'
)


def _past_startup(
    name: str,
    tail: str,
    *,
    fresh: bool,
    registry: Optional[Mapping[str, object]],
    since: Optional[float],
) -> bool:
    if registry is not None and since is not None:
        record = registry_for_session(
            tmux_name=name, index=registry, session_started_epoch=int(since)
        )
        if record.verdict == REG_OK:
            return True
    return fresh and input_box_drawn(tail.splitlines(), RESTING_PROMPT_MARKER)


def watch_for_startup_prompts(
    names: Iterable[str],
    *,
    socket: str,
    fresh: Iterable[str] = (),
    since: Optional[float] = None,
    window: float = CHECK_WINDOW_SECONDS,
    interval: float = CHECK_INTERVAL_SECONDS,
    capture: Optional[Callable[..., Optional[str]]] = None,
    registry_index: Callable[[], Mapping[str, object]] = read_registry_index,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Optional[bool]]:
    read = capture or capture_pane_tail
    fresh_names = set(fresh)
    pending = [n for n in dict.fromkeys(names) if n]
    verdict: Dict[str, Optional[bool]] = {n: None for n in pending}
    deadline = clock() + max(0.0, window)
    while pending:
        still = []
        registry = registry_index() if since is not None else None
        for name in pending:
            tail = read(socket=socket, name=name, lines=CHECK_TAIL_LINES)
            found = detect_startup_prompt(tail)
            if found is True:
                verdict[name] = True
                logger.info("session_restore_startup_prompt_seen", tmux_session=name)
                continue
            if found is False:
                verdict[name] = False
                if _past_startup(name, tail or "", fresh=name in fresh_names,
                                 registry=registry, since=since):
                    continue
            still.append(name)
        pending = still
        if not pending or clock() + interval > deadline:
            break
        sleep(interval)
    return verdict
