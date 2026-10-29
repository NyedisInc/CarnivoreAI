
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.core.json_artifact import atomic_write_json, read_json_object

FILENAME = "limit_rotation.json"

MAX_ATTEMPTS = 2

COOLDOWN_SECONDS = 30 * 60

RETENTION_SECONDS = 9 * 24 * 3600

CAPS_KEY = "_caps"
BASELINE_KEY = "_baseline"


def default_path() -> Path:
    from src.config import settings

    return Path(settings.get_state_dir()) / FILENAME


class RotationState:

    def __init__(self, path: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._entries: Optional[Dict[str, Dict[str, Any]]] = None

    def _all(self) -> Dict[str, Dict[str, Any]]:
        if self._entries is None:
            raw = read_json_object(self._path or default_path(), log_event="limit_rotation_state_unreadable")
            self._entries = {k: v for k, v in (raw or {}).items() if isinstance(v, dict)}
        return self._entries

    def _save(self) -> None:
        entries = self._all()
        horizon = self._clock() - RETENTION_SECONDS
        for key in [k for k, v in entries.items() if not k.startswith("_") and float(v.get("at", 0)) < horizon]:
            del entries[key]
        caps = entries.get(CAPS_KEY)
        if caps is not None:
            for account in [a for a, until in caps.items() if float(until) <= self._clock()]:
                del caps[account]
        atomic_write_json(self._path or default_path(), entries, log_event="limit_rotation_state_write_failed")

    def _entry(self, record_id: str) -> Dict[str, Any]:
        return self._all().setdefault(record_id, {"at": self._clock()})

    def may_restart(self, record_id: str) -> tuple[bool, Optional[str]]:
        entry = self._all().get(record_id, {})
        if int(entry.get("attempts", 0)) >= MAX_ATTEMPTS:
            return False, "attempts_exhausted"
        if self._clock() - float(entry.get("last_attempt", 0)) < COOLDOWN_SECONDS:
            return False, "cooldown"
        return True, None

    def record_attempt(self, record_id: str) -> None:
        entry = self._entry(record_id)
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_attempt"] = self._clock()
        self._save()

    def continue_sent(self, record_id: str) -> bool:
        return bool(self._all().get(record_id, {}).get("continue_sent"))

    def mark_continue_sent(self, record_id: str) -> None:
        self._entry(record_id)["continue_sent"] = True
        self._save()

    def claim_notice(self, record_id: str, outcome: str) -> bool:
        entry = self._entry(record_id)
        told = entry.setdefault("notified", [])
        if outcome in told:
            return False
        told.append(outcome)
        self._save()
        return True

    def note_cap(self, account_id: str, resets_at_epoch: float) -> None:
        if resets_at_epoch <= self._clock():
            return
        caps = self._all().setdefault(CAPS_KEY, {})
        if float(caps.get(account_id, 0)) >= resets_at_epoch:
            return
        caps[account_id] = resets_at_epoch
        self._save()

    def capped_accounts(self) -> set[str]:
        now = self._clock()
        return {a for a, until in self._all().get(CAPS_KEY, {}).items() if float(until) > now}

    def baselined(self) -> bool:
        return bool(self._all().get(BASELINE_KEY, {}).get("done"))

    def take_baseline(self, records: Dict[str, Optional[float]]) -> None:
        now = self._clock()
        self._all()[BASELINE_KEY] = {
            "at": now, "done": True, "records": sorted(r for r, until in records.items() if until is not None and until <= now),
        }
        self._save()

    def pre_existing(self, record_id: str) -> bool:
        return record_id in self._all().get(BASELINE_KEY, {}).get("records", [])
