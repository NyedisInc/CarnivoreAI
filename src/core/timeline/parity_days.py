
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

import structlog

logger = structlog.get_logger(__name__)

STORE_NAME: str = "timeline-parity.json"
STORE_VERSION: int = 1
WRITE_EVERY_SECONDS: float = 60.0
WEEK_DAYS: int = 7
REAL: str = "real"
_COUNTERS = ("classes", "by_tier", "by_state", "real_fields", "canary", "canary_light")


@dataclass
class DayTally:

    day: str
    comparisons: int = 0
    unpaired: int = 0
    raced: int = 0
    undecided: int = 0
    transcript_decided: int = 0
    classes: Counter = field(default_factory=Counter)
    by_tier: Counter = field(default_factory=Counter)
    by_state: Counter = field(default_factory=Counter)
    real_fields: Counter = field(default_factory=Counter)
    canary: Counter = field(default_factory=Counter)
    canary_light: Counter = field(default_factory=Counter)

    def floors_met(self, min_comparisons: int) -> bool:
        return (self.transcript_decided >= min_comparisons and self.canary[REAL] == 1 and self.canary_light[REAL] == 1)

    def counted(self, min_comparisons: int, required_states: FrozenSet[str], week_states: FrozenSet[str]) -> bool:
        return self.floors_met(min_comparisons) and required_states <= week_states

    def stored(self) -> Dict[str, Any]:
        return {f.name: dict(getattr(self, f.name)) if f.name in _COUNTERS else getattr(self, f.name) for f in fields(self)}

    def body(self, min_comparisons: int, required_states: FrozenSet[str], week_states: FrozenSet[str]) -> Dict[str, Any]:
        return {**self.stored(), "states_missing": sorted(required_states - set(self.by_state)),
                "week_states_missing": sorted(required_states - week_states),
                "counted": self.counted(min_comparisons, required_states, week_states)}

    @classmethod
    def from_stored(cls, data: Dict[str, Any]) -> "DayTally":
        tally = cls(str(data["day"]))
        for f in fields(cls):
            if f.name == "day" or f.name not in data:
                continue
            value = data[f.name]
            setattr(tally, f.name, Counter({str(k): int(v) for k, v in value.items()}) if f.name in _COUNTERS else int(value))
        return tally


class DayStore:

    def __init__(self, path_of: Any) -> None:
        self._path_of = path_of
        self.written_at: Optional[float] = None

    def load(self) -> List[DayTally]:
        path = self._path_of()
        if path is None or not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != STORE_VERSION:
                logger.warning("timeline_parity_store_version", version=data.get("version"))
                return []
            return [DayTally.from_stored(day) for day in data["days"]]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("timeline_parity_store_unreadable", error=type(exc).__name__, detail=str(exc)[:200])
            return []

    def due(self, now: float) -> bool:
        return self.written_at is None or now - self.written_at >= WRITE_EVERY_SECONDS

    def body(self, days: List[DayTally]) -> Optional[str]:
        return None if self._path_of() is None else json.dumps(
            {"version": STORE_VERSION, "days": [day.stored() for day in days]}, sort_keys=True)

    def write(self, text: str) -> None:
        path = self._path_of()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp = tempfile.mkstemp(prefix=".timeline-parity.", dir=str(path.parent))
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, path)
        except OSError as exc:
            logger.warning("timeline_parity_store_write_failed", error=type(exc).__name__, detail=str(exc)[:200])


def default_store_path() -> Path:
    from src.config import settings  # noqa: PLC0415

    from src.core.pipeline.contract import PLUGIN_DIR  # noqa: PLC0415

    return Path(settings.get_state_dir()) / PLUGIN_DIR / STORE_NAME
