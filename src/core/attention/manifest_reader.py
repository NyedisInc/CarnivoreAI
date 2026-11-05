
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from src.core.agent_manifests import engine
from src.core.attention.evidence import (
    REASON_NO_EVIDENCE, REASON_PERMISSION, REASON_QUESTION, REASON_STREAMING, REASON_TURN_ENDED,
    STATE_BUSY, STATE_DONE_IDLE, STATE_NEEDS_USER, STATE_UNKNOWN, TIER_NONE, TIER_PANE,
)
from src.core.attention.resolve_verdicts import _verdict


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


_STATES = {"working": (STATE_BUSY, REASON_STREAMING), "idle": (STATE_DONE_IDLE, REASON_TURN_ENDED)}
_CODES = {"busy": (STATE_BUSY, REASON_STREAMING), "idle": (STATE_DONE_IDLE, REASON_TURN_ENDED),
          "done": (STATE_DONE_IDLE, REASON_TURN_ENDED), "waiting": (STATE_NEEDS_USER, REASON_QUESTION)}


def manifest_verdict(evidence: Any) -> Optional[Any]:
    reading = getattr(evidence, "manifest", None)
    if reading is None:
        return None
    if reading.code is not None:
        state, reason = _CODES[reading.code]
        return _verdict(state, reason, TIER_PANE, "%s: status code %s" % (reading.cli, reading.code),
                        evidence=evidence, settle=state == STATE_NEEDS_USER)
    where = "%s screen rules %s" % (reading.cli, reading.version)
    if reading.state is None:
        return _verdict(STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE,
                        "%s: no rule matched the screen" % where, evidence=evidence)
    if reading.state == "blocked":
        reason = REASON_PERMISSION if "permission" in (reading.rule or "") else REASON_QUESTION
        return _verdict(STATE_NEEDS_USER, reason, TIER_PANE, "%s: rule %s" % (where, reading.rule),
                        evidence=evidence, settle=True)
    state, reason = _STATES[reading.state]
    return _verdict(state, reason, TIER_PANE, "%s: rule %s" % (where, reading.rule), evidence=evidence)
