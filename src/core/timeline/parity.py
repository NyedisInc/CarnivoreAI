
from __future__ import annotations

import asyncio
import dataclasses
import time
from collections import OrderedDict, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, FrozenSet, List, NamedTuple, Optional, Tuple

import structlog

from src.core.attention.evidence import TIER_TRANSCRIPT, AttentionVerdict, Evidence
from src.core.attention.registry_index import registry_for_session
from src.core.attention.transcript_facts import TranscriptFacts
from src.core.timeline import hot
from src.core.timeline.facts_adapter import TURN_END_FIELDS
from src.core.timeline.pairs import PairBook
from src.core.timeline.parity_days import REAL, WEEK_DAYS, DayStore, DayTally, default_store_path
from src.models.activity_status import ACTIVITY_STATUSES

logger = structlog.get_logger(__name__)

CLASS_AGREE, CLASS_TURN_END, CLASS_REAL = "agree", "expected_turn_end", "real"
CF_AGREE, CF_DIFFER, CF_UNDECIDED = "agree", "differ", "undecided"
MIN_COMPARISONS: int = 5000
KEPT_DAYS_FLOOR: int = 14
MAX_DAYS: int = max(KEPT_DAYS_FLOOR, WEEK_DAYS)
MAX_SAMPLES: int = 50
CANARY_FIELD: str = "open_async_agents"
LIGHT_CANARY_TOOL: str = "AskUserQuestion"
LIGHT_CANARY_AGENTS: int = 3
MAX_LIGHT_CANARY_TRIES: int = 50
MAX_LOGGED_SESSIONS: int = 256
FACT_FIELDS: Tuple[str, ...] = tuple(f.name for f in dataclasses.fields(TranscriptFacts))


class Comparison(NamedTuple):

    fields: Tuple[str, ...]
    decided_differs: bool
    counterfactual: str
    cf_tier: str
    klass: str


def _resolve(evidence: Evidence) -> AttentionVerdict:
    from src.core.attention.resolve import resolve_attention  # noqa: PLC0415

    return resolve_attention(evidence)


def _light(verdict: AttentionVerdict) -> Tuple[str, str, str]:
    return (verdict.state, verdict.reason, verdict.tier)


def _absent_registry() -> Any:
    return registry_for_session(tmux_name=None)


def _counterfactual(evidence: Evidence, legacy: TranscriptFacts, fold: TranscriptFacts) -> Tuple[str, str]:
    bare = dataclasses.replace(evidence, registry=_absent_registry())
    was = _resolve(dataclasses.replace(bare, transcript=legacy))
    now = _resolve(dataclasses.replace(bare, transcript=fold))
    if evidence.pane is None and (was.pane_may_veto or now.pane_may_veto):
        return CF_UNDECIDED, was.tier
    return (CF_AGREE if _light(was) == _light(now) else CF_DIFFER), was.tier


def classify(fields: Tuple[str, ...], decided_differs: bool, counterfactual: str) -> str:
    if decided_differs or counterfactual == CF_DIFFER or any(name not in TURN_END_FIELDS for name in fields):
        return CLASS_REAL
    return CLASS_TURN_END if fields else CLASS_AGREE


def compare(evidence: Evidence, legacy: TranscriptFacts, fold: TranscriptFacts) -> Comparison:
    fields = tuple(name for name in FACT_FIELDS if getattr(legacy, name) != getattr(fold, name))
    decided_was = _resolve(dataclasses.replace(evidence, transcript=legacy))
    decided_now = _resolve(dataclasses.replace(evidence, transcript=fold))
    decided_differs = _light(decided_was) != _light(decided_now)
    counterfactual, cf_tier = _counterfactual(evidence, legacy, fold)
    return Comparison(fields, decided_differs, counterfactual, cf_tier, classify(fields, decided_differs, counterfactual))


def canary_copy(fold: TranscriptFacts) -> TranscriptFacts:
    return dataclasses.replace(fold, **{CANARY_FIELD: (getattr(fold, CANARY_FIELD) or 0) + 1})


def light_canary_copies(fold: TranscriptFacts) -> Tuple[TranscriptFacts, ...]:
    return (dataclasses.replace(fold, blocked_on_tool=LIGHT_CANARY_TOOL),
            dataclasses.replace(fold, blocked_on_tool=None, pending_background_agents=LIGHT_CANARY_AGENTS))


class Parity:

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 min_comparisons: int = MIN_COMPARISONS, required_states: FrozenSet[str] = ACTIVITY_STATUSES,
                 enabled: Callable[[], bool] = hot.shadow_enabled, pairs: Optional[PairBook] = None,
                 store_path: Callable[[], Optional[Path]] = default_store_path,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._clock, self._enabled, self._monotonic = clock, enabled, monotonic
        self._pairs = pairs if pairs is not None else hot.PAIRS
        self.min_comparisons, self.required_states = min_comparisons, frozenset(required_states)
        self._store = DayStore(store_path)
        self._days: "OrderedDict[str, DayTally]" = OrderedDict()
        self._loaded = False
        self._samples: Deque[Dict[str, Any]] = deque(maxlen=MAX_SAMPLES)
        self._last_real: "OrderedDict[str, Tuple[Tuple[str, ...], bool, str]]" = OrderedDict()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for tally in self._store.load():
            self._days.setdefault(tally.day, tally)
        self._trim_days()

    def _trim_days(self) -> None:
        for day in sorted(self._days)[:-MAX_DAYS]:
            del self._days[day]

    def _week_states(self, day: str) -> FrozenSet[str]:
        end = date.fromisoformat(day)
        window = {(end - timedelta(days=back)).isoformat() for back in range(WEEK_DAYS)}
        return frozenset(state for name in window if name in self._days for state in self._days[name].by_state)

    def _body(self, day: str) -> Dict[str, Any]:
        return self._days[day].body(self.min_comparisons, self.required_states, self._week_states(day))

    def _today(self) -> DayTally:
        self._ensure_loaded()
        day = self._clock().date().isoformat()
        tally = self._days.get(day)
        if tally is None:
            if self._days:
                logger.info("timeline_parity_day", **self._body(max(self._days)))
            tally = self._days[day] = DayTally(day)
            self._trim_days()
        return tally

    def on_observation(self, session_id: str, evidence: Evidence, display: str) -> None:
        try:
            if self._enabled():
                self._observe(session_id, evidence, display)
        except (TypeError, AttributeError, KeyError, ValueError, IndexError) as exc:
            logger.error("timeline_parity_bug", session_id=session_id, error=type(exc).__name__, exc_info=True)

    def _observe(self, session_id: str, evidence: Evidence, display: str) -> None:
        tally = self._today()
        pair = self._pairs.find(evidence.transcript)
        if pair is None or pair.raced:
            if pair is None:
                tally.unpaired += 1
            else:
                tally.raced += 1
            return
        fold = pair.fold
        if not tally.canary["injected"]:
            tally.canary["injected"] += 1
            tally.canary[compare(evidence, evidence.transcript, canary_copy(fold)).klass] += 1
        self._light_canary(tally, evidence, fold)
        result = compare(evidence, evidence.transcript, fold)
        floor = pair.floor_day != tally.day and result.counterfactual != CF_UNDECIDED
        if floor:
            pair.floor_day = tally.day
        self._count(tally, session_id, result, display, pair.size, floor)
        self._persist()

    def _light_canary(self, tally: DayTally, evidence: Evidence, fold: TranscriptFacts) -> None:
        if tally.canary_light[REAL] or tally.canary_light["injected"] >= MAX_LIGHT_CANARY_TRIES:
            return
        tally.canary_light["injected"] += 1
        moved = any(compare(evidence, evidence.transcript, copy).counterfactual == CF_DIFFER
                    for copy in light_canary_copies(fold))
        tally.canary_light[REAL if moved else "unmoved"] += 1

    def _count(self, tally: DayTally, session_id: str, result: Comparison, display: str, size: int, floor: bool) -> None:
        tally.comparisons += 1
        tally.classes[result.klass] += 1
        tally.by_state[display] += 1
        if result.counterfactual == CF_UNDECIDED:
            tally.undecided += 1
        else:
            tally.by_tier[result.cf_tier] += 1
            if floor and result.cf_tier == TIER_TRANSCRIPT:
                tally.transcript_decided += 1
        if result.klass == CLASS_REAL:
            tally.real_fields.update(name for name in result.fields if name not in TURN_END_FIELDS)
        if result.klass == CLASS_AGREE:
            self._last_real.pop(session_id, None)
            return
        self._samples.append({
            "at": self._clock().isoformat(), "session_id": session_id, "class": result.klass, "fields": list(result.fields),
            "decided_differs": result.decided_differs, "counterfactual": result.counterfactual, "cf_tier": result.cf_tier,
            "size": size,
        })
        if result.klass == CLASS_REAL:
            self._log_real(session_id, result, size)

    def _log_real(self, session_id: str, result: Comparison, size: int) -> None:
        signature = (result.fields, result.decided_differs, result.counterfactual)
        if self._last_real.get(session_id) == signature:
            self._last_real.move_to_end(session_id)
            return
        self._last_real[session_id] = signature
        self._last_real.move_to_end(session_id)
        while len(self._last_real) > MAX_LOGGED_SESSIONS:
            self._last_real.popitem(last=False)
        logger.info("timeline_parity_real", session_id=session_id, fields=list(result.fields),
                    decided_differs=result.decided_differs, counterfactual=result.counterfactual, size=size)

    def _persist(self) -> None:
        now = self._monotonic()
        if not self._store.due(now):
            return
        text = self._store.body(list(self._days.values()))
        if text is None:
            return
        self._store.written_at = now
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._store.write(text)
            return
        loop.run_in_executor(None, self._store.write, text)

    def snapshot(self) -> Dict[str, Any]:
        self._ensure_loaded()
        days: List[Dict[str, Any]] = [self._body(day) for day in sorted(self._days, reverse=True)]
        return {
            "enabled": self._enabled(), "status_source": hot.status_source(),
            "floors": {"min_comparisons": self.min_comparisons, "required_states": sorted(self.required_states)},
            "window_days": WEEK_DAYS,
            "week_states_missing": days[0]["week_states_missing"] if days else sorted(self.required_states),
            "counted_days": sum(1 for day in days if day["counted"]),
            "days": days, "samples": list(self._samples), "hot_files": len(hot.DRIVER),
        }


PARITY = Parity()
