
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from src.core.attention.registry_read import REG_ABSENT, REG_STALE
from src.core.session_startup_gate import (
    GATE_AWAITING,
    SCREEN_UNRECOGNIZED,
    STARTUP_HOOK_GRACE_SECONDS,
    startup_screen_kind,
)
from src.core.stream_redactor import StreamRedactor

FALLBACK_HOLD_SECONDS: int = STARTUP_HOOK_GRACE_SECONDS

SCREEN_TEXT_MAX_CHARS: int = 3500

AGENT_EXECUTABLES: Tuple[str, ...] = ("claude", "codex")


@dataclass(frozen=True)
class StartupScreen:

    kind: str
    text: str
    since: datetime
    matched: bool

    def shown(self, now: datetime) -> bool:
        if self.matched:
            return True
        return (now - self.since).total_seconds() >= FALLBACK_HOLD_SECONDS


def screen_text_for_alert(text: str) -> str:
    redactor = StreamRedactor()
    clean = redactor.feed(text) + redactor.flush(end=True)
    lines = [line.rstrip() for line in clean.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    out = "\n".join(lines)
    return out[-SCREEN_TEXT_MAX_CHARS:]


def agent_alive_under(
    pane_pid: Optional[int], parents: Mapping[int, int], commands: Mapping[int, str], ok: bool,
) -> Optional[bool]:
    """Is an agent executable running in this pane's process tree?

    Description: walks one ``ps`` snapshot for a descendant of (or the pane
      process itself) whose argv[0] basename is in
      :data:`AGENT_EXECUTABLES`. A snapshot that could not be read, or no
      pane pid, answers None: not having looked is never "gone".
    Inputs: pane_pid (int | None); parents ({pid: ppid}); commands
      ({pid: command line}); ok (bool) - False when the table was unreadable.
    Output: bool | None.
    Example: agent_alive_under(10, {11: 10}, {11: "/x/claude --resume"}, True) -> True
    """
    if pane_pid is None or not ok:
        return None
    for pid, command in commands.items():
        argv0 = (command or "").split(" ", 1)[0]
        if argv0.rsplit("/", 1)[-1] not in AGENT_EXECUTABLES:
            continue
        cursor, hops = pid, 0
        while cursor is not None and hops < 64:
            if cursor == pane_pid:
                return True
            cursor, hops = parents.get(cursor), hops + 1
    return False


def classify_startup_screen(
    text: Optional[str], *, registry_present: bool, record_absent: bool,
    agent_alive: Optional[bool], resting: Optional[bool],
) -> Optional[Tuple[str, bool]]:
    if registry_present or agent_alive is False or not text or not text.strip():
        return None
    kind = startup_screen_kind(text)
    if kind is not None:
        return kind, True
    if record_absent and agent_alive is True and resting is False:
        return SCREEN_UNRECOGNIZED, False
    return None


def read_startup_screen(
    memory: "StartupScreenMemory", session_id: str, *, text: Optional[str], registry: Any,
    pane: Any, pane_pid: Optional[int], snapshot: Callable[[], Any], instance: tuple, now: datetime,
) -> Optional[StartupScreen]:
    present = bool(getattr(registry, "instance_present", False))
    alive: Optional[bool] = None
    if text and not present:
        table = snapshot()
        alive = agent_alive_under(pane_pid, table.parents, table.commands, table.ok)
    found = classify_startup_screen(
        text, registry_present=present,
        record_absent=getattr(registry, "verdict", None) in (REG_ABSENT, REG_STALE),
        agent_alive=alive, resting=getattr(pane, "resting_prompt", None),
    )
    return memory.observe(session_id, instance, found, text, now)


class StartupScreenMemory:

    def __init__(self) -> None:
        self._seen: Dict[str, Tuple[tuple, str, datetime]] = {}

    def observe(
        self, session_id: str, instance: tuple, found: Optional[Tuple[str, bool]],
        text: Optional[str], now: datetime,
    ) -> Optional[StartupScreen]:
        if found is None or text is None:
            self._seen.pop(session_id, None)
            return None
        kind, matched = found
        prior = self._seen.get(session_id)
        since = prior[2] if prior is not None and prior[0] == instance and prior[1] == kind else now
        self._seen[session_id] = (instance, kind, since)
        return StartupScreen(kind, screen_text_for_alert(text), since, matched)


def shown_screen(observation: object) -> Optional[StartupScreen]:
    """The startup screen an observation surfaces, or None.

    Description: None for a missing or stale observation (a stale reading
      is not a screen; ``unknown`` is not a prompt), for a remote row, and
      for a fallback screen still inside its hold.
    Inputs: observation - an ``attention.watcher.Observation`` or None.
    Output: StartupScreen | None.
    """
    if observation is None or getattr(observation, "stale", True):
        return None
    evidence = getattr(observation, "evidence", None)
    screen = getattr(evidence, "startup_screen", None)
    if screen is None or not screen.shown(evidence.now):
        return None
    return screen


def gate_with_screen(gate: str, observation: object) -> str:
    return GATE_AWAITING if shown_screen(observation) is not None else gate
