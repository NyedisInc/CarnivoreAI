
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from src.core.plugin_health import model
from src.core.plugin_health.model import Verdict
from src.core.plugin_health.presence import GONE, UNREADABLE

_ADMIT_HELD = {"revoked": model.REASON_REVOKED, "index_expired": model.REASON_INDEX_EXPIRED, "trust_refused": model.REASON_TRUST_REFUSED,
               "unbuildable": model.REASON_MANIFEST_INVALID}
_CRASHED_STATES = frozenset({"crash_loop", "backing_off", "killed"})


@dataclass(frozen=True)
class SidecarFacts:

    folder: str
    in_registry: bool
    record_ok: bool = True
    manifest_ok: bool = True
    local: bool = False
    sideload_on: bool = True
    enabled: bool = False
    consented: bool = False
    owed: bool = False
    grants_missing: bool = False
    admit: Optional[str] = None
    runtime_up: bool = True
    safe_env_or_owner: bool = False
    process: str = "unknown"
    blocked_by: Tuple[str, ...] = ()


def _verdict(word: str, reason: Optional[str] = None) -> Verdict:
    if word == model.WORD_ON:
        return Verdict(word, None, model.BUTTON_TURN_OFF)
    if word == model.WORD_OFF:
        return Verdict(word, None, model.BUTTON_TURN_ON)
    if word == model.WORD_NEEDS_APPROVAL:
        return Verdict(word, reason, model.BUTTON_REVIEW)
    return Verdict(word, reason, model.HELD_BUTTONS.get(reason or ""))


def _folder_verdict(presence: str) -> Optional[Verdict]:
    if presence == GONE:
        return _verdict(model.WORD_HELD, model.REASON_FOLDER_MISSING)
    if presence == UNREADABLE:
        return _verdict(model.WORD_HELD, model.REASON_FOLDER_UNREADABLE)
    return None


def _unloaded_verdict(f: SidecarFacts) -> Optional[Verdict]:
    if f.in_registry:
        return None
    if f.local and not f.sideload_on:
        return _verdict(model.WORD_HELD, model.REASON_SIDELOAD_OFF)
    if not f.record_ok:
        return _verdict(model.WORD_HELD, model.REASON_INSTALL_RECORD_MISSING)
    return _verdict(model.WORD_HELD, model.REASON_MANIFEST_INVALID)


def _enabled_verdict(f: SidecarFacts) -> Verdict:
    if f.admit == "safe_mode":
        return _verdict(model.WORD_HELD, model.REASON_SAFE_MODE if f.safe_env_or_owner else model.REASON_THIRD_PARTY_OFF)
    if f.admit in _ADMIT_HELD:
        return _verdict(model.WORD_HELD, _ADMIT_HELD[f.admit])
    if f.admit == "needs_approval" or f.owed or f.process == "integrity":
        return _verdict(model.WORD_NEEDS_APPROVAL, model.REASON_CODE_CHANGED)
    if f.grants_missing:
        return _verdict(model.WORD_NEEDS_APPROVAL, model.REASON_GRANT_WAITING)
    if not f.runtime_up:
        return _verdict(model.WORD_HELD, model.REASON_RUNTIME_DOWN)
    if f.process in _CRASHED_STATES:
        return _verdict(model.WORD_HELD, model.REASON_CRASHED)
    if f.blocked_by:
        return _verdict(model.WORD_HELD, model.REASON_NEEDS_PLUGIN)
    return _verdict(model.WORD_ON)


def classify_sidecar(f: SidecarFacts) -> Verdict:
    found = _folder_verdict(f.folder) or _unloaded_verdict(f)
    if found is not None:
        return found
    if not f.enabled:
        if not f.consented:
            return _verdict(model.WORD_NEEDS_APPROVAL, model.REASON_NEW_INSTALL)
        if f.owed:
            return _verdict(model.WORD_NEEDS_APPROVAL, model.REASON_CODE_CHANGED)
        return _verdict(model.WORD_OFF)
    return _enabled_verdict(f)


def classify_listing_state(state: str, detail: Optional[str]) -> Verdict:
    if state == "active":
        return _verdict(model.WORD_ON)
    if state == "needs_approval":
        return _verdict(model.WORD_NEEDS_APPROVAL, model.REASON_GRANT_WAITING)
    if state == "inert":
        return _verdict(model.WORD_HELD, model.REASON_NEEDS_PLUGIN)
    if state == "unavailable":
        return _verdict(model.WORD_HELD, model.REASON_UNAVAILABLE)
    return _verdict(model.WORD_OFF)


def classify_claude_plugin(presence: str, recorded_digest: str, measured_digest: Optional[str]) -> Verdict:
    found = _folder_verdict(presence)
    if found is not None:
        return found
    if measured_digest is None:
        return _verdict(model.WORD_HELD, model.REASON_FOLDER_UNREADABLE)
    if recorded_digest and measured_digest != recorded_digest:
        return _verdict(model.WORD_NEEDS_APPROVAL, model.REASON_CHANGED_ON_DISK)
    return _verdict(model.WORD_ON)
