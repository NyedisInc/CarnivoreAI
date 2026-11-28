
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from src.core.agent_manifests import engine
from src.core.attention.evidence import (
    ACTIVITY_HINT_BACKGROUND, REASON_NO_EVIDENCE, REASON_PERMISSION, REASON_QUESTION,
    REASON_STREAMING, REASON_SUBAGENTS, REASON_TURN_ENDED,
    STATE_BUSY, STATE_DONE_IDLE, STATE_NEEDS_USER, STATE_UNKNOWN, TIER_NONE, TIER_PANE,
)
from src.core.attention.resolve_verdicts import _verdict
from src.core.background_work.measured import STATE_RUNNING


@dataclass(frozen=True)
class ManifestReading:

    cli: str
    version: str
    state: Optional[str] = None
    rule: Optional[str] = None
    code: Optional[str] = None


def read_manifest(pane_pid: Optional[int], snapshot: Any, screen: Callable[[], Optional[str]],
                  status_code: Optional[str] = None) -> Optional[ManifestReading]:
    parents = getattr(snapshot, "parents", None) or {}
    commands = getattr(snapshot, "commands", None) or {}
    manifest = engine.identify(pane_pid, parents, commands)
    if manifest is not None and manifest.id == "agy":
        code = _agy_code(pane_pid, parents, commands)
        if code is not None:
            return ManifestReading(manifest.id, "statusline", code=code)
    if status_code is not None:
        if manifest is None:
            return ManifestReading("program", "osc 3008", code=status_code)
        return ManifestReading(manifest.id, manifest.version, code=status_code)
    if manifest is None:
        return None
    text = screen()
    match = engine.evaluate(manifest, text) if text is not None else None
    if match is None:
        return ManifestReading(manifest.id, manifest.version)
    return ManifestReading(manifest.id, manifest.version, match.state, match.rule)


def _agy_code(pane_pid: Optional[int], parents: Any, commands: Any) -> Optional[str]:
    from src.config import settings
    from src.core.agy.state import read_state, status_code
    from src.core.attention.agy_conversation import agy_pid_under

    pid = agy_pid_under(pane_pid, parents, commands)
    return status_code(read_state(settings.get_state_dir(), pid)) if pid is not None else None


_STATES = {"working": (STATE_BUSY, REASON_STREAMING), "idle": (STATE_DONE_IDLE, REASON_TURN_ENDED)}
_CODES = {"busy": (STATE_BUSY, REASON_STREAMING), "idle": (STATE_DONE_IDLE, REASON_TURN_ENDED),
          "done": (STATE_DONE_IDLE, REASON_TURN_ENDED), "waiting": (STATE_NEEDS_USER, REASON_QUESTION)}


def _live_non_server_shells(evidence: Any) -> int:
    measure = getattr(evidence, "background_process", None)
    if measure is None or getattr(measure, "state", None) != STATE_RUNNING:
        return 0
    return max(0, int(getattr(measure, "count", 0) or 0) - int(getattr(measure, "servers", 0) or 0))


def _bg_shell_verdict(cli: str, live_shells: int, evidence: Any) -> Any:
    return replace(
        _verdict(
            STATE_BUSY, REASON_SUBAGENTS, TIER_PANE,
            "%s: %d background tool shell(s) running" % (cli, live_shells),
            evidence=evidence,
        ),
        activity_hint=ACTIVITY_HINT_BACKGROUND,
    )


def manifest_verdict(evidence: Any) -> Optional[Any]:
    reading = getattr(evidence, "manifest", None)
    if reading is None:
        return None
    if reading.code is not None:
        state, reason = _CODES[reading.code]
        if state == STATE_DONE_IDLE:
            live_shells = _live_non_server_shells(evidence)
            if live_shells > 0:
                return _bg_shell_verdict(reading.cli, live_shells, evidence)
        return _verdict(state, reason, TIER_PANE, "%s: status code %s" % (reading.cli, reading.code),
                        evidence=evidence, settle=state == STATE_NEEDS_USER)
    where = "%s screen rules %s" % (reading.cli, reading.version)
    if reading.state is None:
        live_shells = _live_non_server_shells(evidence)
        if live_shells > 0:
            return _bg_shell_verdict(reading.cli, live_shells, evidence)
        return _verdict(STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE,
                        "%s: no rule matched the screen" % where, evidence=evidence)
    if reading.state == "blocked":
        reason = REASON_PERMISSION if "permission" in (reading.rule or "") else REASON_QUESTION
        return _verdict(STATE_NEEDS_USER, reason, TIER_PANE, "%s: rule %s" % (where, reading.rule),
                        evidence=evidence, settle=True)
    state, reason = _STATES[reading.state]
    if state == STATE_DONE_IDLE:
        live_shells = _live_non_server_shells(evidence)
        if live_shells > 0:
            return _bg_shell_verdict(reading.cli, live_shells, evidence)
    return _verdict(state, reason, TIER_PANE, "%s: rule %s" % (where, reading.rule), evidence=evidence)
