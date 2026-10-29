"""The one task that raises toasts, and the only thing that ever does.

ONE SERVER-OWNED ASYNCIO TASK. It lists the sessions worth watching,
reads their evidence off the loop, resolves each one through the pure
resolver, hands the answer to the ledger, and acts on whatever comes back
as an edge. The listing pass consumes the immutable observation stored here and
raises nothing, so display and notifications share the same evidence. A phone with no browser open still gets its
push, because the watcher raises, not a poll.

TESTABLE WITHOUT A SERVER, AND THAT IS A CONSTRAINT, NOT A CONVENIENCE.
Everything this class touches arrives through the constructor: the
target list, the evidence reader, the three actions, the ledger and the
clock. Nothing in ``src/core/attention/`` may import ``session_manager``,
so the watcher cannot reach for a session, a policy or a toast inbox
directly, and the replay suite drives years of recorded history through
it in milliseconds with no files and no sleeping.

THE LOOP MAY NOT DIE. A watcher that raises out of its own tick takes
every notification on the machine with it, silently, until the next
restart. So a failure reading ONE session is caught around that session
and the rest of the tick continues, and a failure anywhere else in the
tick is caught around the tick and the loop continues. Both are logged
with the event name first. ``asyncio.CancelledError`` is re-raised
before either, because shutdown is not a failure.

THE CADENCE IS A TICK WITH AN EARLY WAKE, NOT A POLL. The backstop tick
is :data:`DEFAULT_TICK_SECONDS`, and on top of it the EXISTING
``PipeWaiter`` (``src/core/pipe_wakeup.py``, kqueue on asyncio's own
selector, no thread spent) watches ``~/.claude/sessions/`` so a session
appearing or disappearing wakes the loop in microseconds rather than at
the end of the interval.

WHAT WAS VERIFIED ABOUT THAT DIRECTORY, because the plan asked, AND
HOW. Read out of the Claude Code 2.1.266 bundle: the registry updater
``Tn``, chained on ``pidFileWriteChain``, reads the existing
``<pid>.json``, merges the changed keys and writes the SAME PATH back,
and the storage-interface branch of that same function spells the
discipline out as ``publishDiscipline: "inPlace"``. The inode check that
would have confirmed it from the outside did NOT get a sample: across
about two and a half minutes of watching every file in the directory at
200 ms, no session changed status, so nothing was written at all. The
claim therefore rests on the binary, and it is stated that way rather
than as a measurement. A status change is an IN-PLACE REWRITE: the inode
does not change and the containing directory is not modified, which
means a directory watch does NOT see it. The directory watch therefore
covers registration and exit (create, unlink, rename) and THE TICK IS
WHAT COVERS A STATUS
CHANGE. That is the right trade for this loop: the tick is two seconds,
the toast it gates is a human-facing notification, and watching every
registry file individually would cost a kqueue descriptor per session to
buy less than two seconds on a notification a human reads at their own
pace. The plan's note that the tick is the backstop "either way" is why
this is a sizing decision and not a correctness one.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import structlog

from src.core.attention.evidence import (
    AttentionVerdict,
    Evidence,
    REASON_INPUT,
    REASON_NO_EVIDENCE,
    REASON_EVIDENCE_DISAGREES,
    STATE_UNKNOWN,
    TIER_NONE,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
)
from src.core.attention.ledger import AttentionLedger, Transition
from src.core.attention.raise_gate import policy_for, resolve_raise
from src.core.attention.registry_read import default_registry_directory
from src.core.attention.resolve import DONE_QUIET_SECONDS, resolve_attention
from src.core.attention.restart_floor import RestartFloors
from src.core.attention.startup_quiet import StartupQuiet
from src.core.attention.wake import WakeSources
from src.core.perf_hooks.monitor import PERF
from src.core.session_activity import (
    EVENT_NOTIFICATION,
    EVENT_PERMISSION_REQUEST,
    EVENT_STOP,
)

logger = structlog.get_logger()

DEFAULT_TICK_SECONDS: float = 2.0

RESTING_HOLD_SECONDS: float = 4.0
MAX_READ_CONCURRENCY: int = 4
SETTLE_MARGIN_SECONDS: float = 0.1
MISSED_CYCLES: int = 3
STALL_BACKSTOP_SECONDS: float = 30.0


@dataclass(frozen=True)
class WatchTarget:

    session_id: str

    key: str

    generation: Optional[tuple] = None


@dataclass(frozen=True)
class Observation:

    verdict: AttentionVerdict

    evidence: Evidence

    new_user_prompt_at: Optional[datetime]

    transcript_appended: bool
    revision: int = 0
    stale: bool = False
    cycle: int = 0

    @property
    def observed_at(self) -> datetime:
        return self.evidence.now


def _toast_kind_for(transition: Transition) -> Optional[str]:
    if transition.state == STATE_DONE_IDLE:
        return EVENT_STOP
    if transition.state == STATE_NEEDS_USER:
        if transition.reason == REASON_INPUT:
            return EVENT_NOTIFICATION
        return EVENT_PERMISSION_REQUEST
    return None


class AttentionWatcher:

    _last_pass_kind: str = "full"

    def __init__(
        self,
        *,
        list_targets: Callable[[], Sequence[WatchTarget]],
        read_evidence: Callable[[WatchTarget, datetime], Optional[Evidence]],
        raise_toast: Callable[[WatchTarget, str, Transition], None],
        set_unread: Callable[[WatchTarget], None],
        on_busy_edge: Callable[[WatchTarget, Transition], None],
        ledger: AttentionLedger,
        on_observation: Optional[Callable[[WatchTarget, "Observation"], None]] = None,
        on_done_edge: Optional[Callable[[WatchTarget, Transition], None]] = None,
        on_transition: Optional[Callable[[WatchTarget, Transition], None]] = None,
        read_policy: Optional[Callable[[WatchTarget], Tuple[bool, Any]]] = None,
        now: Optional[Callable[[], datetime]] = None,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        registry_directory: Optional[str] = None,
        watch_paths: Optional[Callable[[Set[str]], Mapping[str, Sequence[str]]]] = None,
        restart_floors: Optional[RestartFloors] = None,
    ) -> None:
        self._list_targets = list_targets
        self._read_evidence = read_evidence
        self._raise_toast = raise_toast
        self._set_unread = set_unread
        self._on_busy_edge = on_busy_edge
        self._on_observation = on_observation
        self._on_done_edge = on_done_edge
        self._on_transition = on_transition
        self._read_policy = read_policy
        self._ledger = ledger
        self._now = now if now is not None else _utc_now
        self.tick_seconds = tick_seconds
        self._registry_directory = (
            registry_directory
            if registry_directory is not None
            else default_registry_directory()
        )
        self._wake = WakeSources(self._registry_directory,
                                 watch_files=watch_paths is not None)
        self._resting_since: Dict[str, datetime] = {}
        self._observations: Dict[str, Observation] = {}
        self._targets: Dict[str, WatchTarget] = {}
        self._identities: Dict[str, tuple] = {}
        self._startup_quiet = StartupQuiet()
        self._restart_floors = restart_floors if restart_floors is not None else RestartFloors()
        self._revision = 0
        self._cycles = 0
        self._last_cycle_at: Optional[datetime] = None
        self._watch_paths = watch_paths


    async def run(self) -> None:
        self._open_watch()
        logger.info(
            "attention_watcher_started",
            tick_seconds=self.tick_seconds,
            registry_directory=self._registry_directory,
            early_wake=self._wake.early_wake,
            file_trigger=self._wake.file_trigger,
        )
        try:
            while True:
                try:
                    started = time.monotonic()
                    acted = await self._next_pass()
                    PERF.record_watcher_pass(time.monotonic() - started, self._last_pass_kind)
                    logger.debug("attention_watcher_tick", transitions=acted)
                    await self._wait_for_work()
                except asyncio.CancelledError:
                    logger.info("attention_watcher_stopping")
                    raise
                except Exception as exc:
                    logger.warning(
                        "attention_watcher_tick_failed",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    await asyncio.sleep(self.tick_seconds)
        finally:
            self._close_watch()

    async def _next_pass(self) -> int:
        self._last_pass_kind = "full" if self._wake.full_due() else "targeted"
        if self._last_pass_kind == "full":
            acted = await self.tick_once()
            self._wake.full_pass_done(self.tick_seconds)
            self._rearm_trigger()
            return acted
        return await self.tick_sessions(self._wake.take_files())

    async def tick_sessions(self, session_ids: Set[str]) -> int:
        try:
            listed = [t for t in self._list_targets() if t.session_id in session_ids]
        except Exception as exc:
            logger.warning("attention_targets_unreadable", error=str(exc),
                           error_type=type(exc).__name__)
            return 0
        targets = [t for t in listed if self._targets.get(t.session_id) == t]
        if not targets:
            return 0
        acted = await self._read_and_apply(targets, self._now(), complete_cycle=False)
        for target in targets:
            self._settle_wake(target.session_id)
        return acted

    def _settle_wake(self, session_id: str) -> None:
        observation = self._observations.get(session_id)
        if observation is None or observation.verdict.state == STATE_DONE_IDLE:
            return
        evidence = observation.evidence
        if evidence.codex is not None:
            return
        appended = getattr(evidence.transcript, "newest_append_at", None)
        if appended is None:
            return
        try:
            quiet = (evidence.now - appended).total_seconds()
        except TypeError:
            return
        if 0 <= quiet < DONE_QUIET_SECONDS:
            self._wake.wake_later(session_id, DONE_QUIET_SECONDS - quiet + SETTLE_MARGIN_SECONDS)

    def _rearm_trigger(self) -> None:
        if not self._wake.file_trigger or self._watch_paths is None:
            return
        try:
            by_session = self._watch_paths(set(self._targets))
        except Exception as exc:
            logger.warning("attention_watch_paths_unreadable", error=str(exc),
                           error_type=type(exc).__name__)
            return
        desired: Dict[str, Set[str]] = {}
        for session_id, paths in by_session.items():
            for path in paths:
                desired.setdefault(path, set()).add(session_id)
        self._wake.rearm(desired)

    async def tick_once(self) -> int:
        self._wake.full_pass_started()
        try:
            targets = list(self._list_targets())
        except Exception as exc:
            logger.warning(
                "attention_targets_unreadable",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            self._complete_cycle()
            for target in self._targets.values():
                self._expire(target, self._now())
            return 0
        live_keys = {target.key for target in targets}
        self._prune_resting(live_keys)
        for key in self._ledger.tracked_keys():
            if key not in live_keys:
                self._ledger.forget(key)
                self._identities.pop(key, None)
        live_ids = {target.session_id for target in targets}
        self._startup_quiet.retain_only(live_ids, self._now())
        self._observations = {
            key: value for key, value in self._observations.items() if key in live_ids
        }
        self._targets = {target.session_id: target for target in targets}
        return await self._read_and_apply(targets, self._now(), complete_cycle=True)

    async def _read_and_apply(
        self, targets: List[WatchTarget], now: datetime, *, complete_cycle: bool
    ) -> int:
        semaphore = asyncio.Semaphore(MAX_READ_CONCURRENCY)

        async def read(target: WatchTarget) -> Tuple[WatchTarget, Optional[Evidence]]:
            async with semaphore:
                return (await asyncio.to_thread(self._read_all, [target], now))[0]

        readings = await asyncio.gather(*(read(target) for target in targets))
        if complete_cycle:
            self._complete_cycle()
        try:
            current = {target.session_id: target for target in self._list_targets()}
        except Exception as exc:
            logger.warning("attention_targets_recheck_failed", error=str(exc),
                           error_type=type(exc).__name__)
            for target in targets:
                self._expire(target, self._now())
            return 0
        acted = 0
        for target, evidence in readings:
            if current.get(target.session_id) != target:
                self._observations.pop(target.session_id, None)
                continue
            if evidence is None:
                self._resting_since.pop(target.key, None)
                self._expire(target, now)
            elif self._apply(target, evidence):
                acted += 1
        return acted

    def observed_session_ids(self) -> List[str]:
        return list(self._observations)

    def begin_startup_quiet(self, session_id: str) -> None:
        self._startup_quiet.arm(session_id, self._now())

    def invalidate_session(self, session_id: str) -> None:
        self.begin_startup_quiet(session_id)
        self._restart_floors.stamp(session_id, self._now())
        self._observations.pop(session_id, None)
        target = self._targets.get(session_id)
        if target is not None:
            self._resting_since.pop(target.key, None)

    def process_floor_for(self, session_id: Optional[str]) -> Optional[datetime]:
        return self._restart_floors.floor_for(session_id)

    def abandon_process_floor(self, session_id: str) -> None:
        self._restart_floors.abandon(session_id)

    def _complete_cycle(self) -> None:
        self._cycles += 1
        self._last_cycle_at = self._now()

    def observation_for(
        self, session_id: str, now: Optional[datetime] = None
    ) -> Optional[Observation]:
        observation = self._observations.get(session_id)
        if observation is None or observation.stale:
            return observation
        missed = self._cycles - observation.cycle
        anchor = self._last_cycle_at or observation.observed_at
        since_cycle = ((now or self._now()) - anchor).total_seconds()
        stalled = since_cycle >= max(STALL_BACKSTOP_SECONDS, MISSED_CYCLES * self.tick_seconds)
        if missed < MISSED_CYCLES and not stalled:
            return observation
        return replace(
            observation,
            verdict=AttentionVerdict(
                STATE_UNKNOWN, REASON_NO_EVIDENCE, TIER_NONE,
                detail=("three observation cycles completed without fresh evidence"
                        if missed >= MISSED_CYCLES
                        else "no observation cycle completed within the stall backstop"),
            ),
            evidence=replace(observation.evidence, dialog=None, startup_screen=None),
            stale=True, new_user_prompt_at=None, transcript_appended=False,
        )

    def diagnostics(self, now: Optional[datetime] = None) -> List[dict]:
        instant = now or self._now()
        result = []
        for session_id in self._observations:
            observation = self.observation_for(session_id, instant)
            if observation is None:
                continue
            verdict = observation.verdict
            result.append({
                "session_id": session_id,
                "age_seconds": max(0, (instant - observation.observed_at).total_seconds()),
                "state": verdict.state, "source": verdict.tier,
                "matched_rule": verdict.reason,
                "disagreement_reason": verdict.reason if verdict.state == STATE_UNKNOWN else None,
                "stale": observation.stale, "revision": observation.revision,
            })
        return result

    def _expire(self, target: WatchTarget, now: datetime) -> None:
        previous = self._observations.get(target.session_id)
        observation = self.observation_for(target.session_id, now)
        if observation is None or not observation.stale or observation is previous:
            return
        self._revision += 1
        observation = replace(observation, revision=self._revision)
        self._observations[target.session_id] = observation
        if self._on_observation is not None:
            self._call("attention_observation_failed", target,
                       self._on_observation, target, observation)

    def _prune_resting(self, live_keys: Set[str]) -> None:
        for key in [k for k in self._resting_since if k not in live_keys]:
            del self._resting_since[key]

    def _resting_held(self, target: WatchTarget, evidence: Evidence) -> bool:
        """Has this pane's resting prompt been on screen long enough to act?

        Description: the only stateful thing in the tick besides the
          ledger. Records the FIRST instant a resting prompt was seen and
          answers True once :data:`RESTING_HOLD_SECONDS` have passed since
          it, so the resolver can withdraw a latched busy verdict without
          reading a clock itself.

          ONLY A POSITIVE READING CARRIES THE CLAIM FORWARD. A pane
          measured NOT resting clears the entry, and so does a pane we
          could not read at all (``None``) - continuity is continuity of
          OBSERVATION, and a hold reached by not looking is gotcha 11 in
          one line. Nothing here sleeps or schedules: the instant comes off
          ``evidence.now``, which the tick already stamped.
        Inputs:
          target (WatchTarget) - keyed on ``target.key``, the instance.
          evidence (Evidence) - this tick's bundle.
        Output: bool - False whenever the hold has not been reached.
        Example: watcher._resting_held(target, evidence) -> False
        """
        pane = evidence.codex.pane if evidence.codex is not None else evidence.pane
        if pane is None or pane.resting_prompt is not True:
            self._resting_since.pop(target.key, None)
            return False
        first = self._resting_since.get(target.key)
        if first is None:
            self._resting_since[target.key] = evidence.now
            return False
        try:
            held = (evidence.now - first).total_seconds()
        except TypeError:
            return False
        return held >= RESTING_HOLD_SECONDS

    def _read_all(
        self, targets: Sequence[WatchTarget], now: datetime
    ) -> List[Tuple[WatchTarget, Optional[Evidence]]]:
        readings: List[Tuple[WatchTarget, Optional[Evidence]]] = []
        for target in targets:
            try:
                readings.append((target, self._read_evidence(target, now)))
            except Exception as exc:
                logger.warning(
                    "attention_evidence_unreadable",
                    key=target.key,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                readings.append((target, None))
        return readings


    def _apply(self, target: WatchTarget, evidence: Evidence) -> bool:
        identity = evidence.identity
        if identity is not None:
            previous = self._identities.get(target.key)
            if previous is not None:
                changed = len(previous) != len(identity) or any(
                    old is not None and new is not None and old != new
                    for old, new in zip(previous, identity)
                )
                if changed:
                    self._ledger.forget(target.key)
                    self._resting_since.pop(target.key, None)
                else:
                    identity = tuple(new if new is not None else old
                                     for old, new in zip(previous, identity))
                    evidence = replace(evidence, identity=identity)
            self._identities[target.key] = identity
        evidence = replace(
            evidence, resting_prompt_held=self._resting_held(target, evidence)
        )
        verdict = resolve_attention(evidence)
        pane = evidence.codex.pane if evidence.codex is not None else evidence.pane
        clear = (
            pane is not None and pane.approval_dialog is False
            if evidence.codex is not None else pane is not None and pane.shows_no_dialog
        )
        if (self._ledger.confirmed_state(target.key) == STATE_NEEDS_USER
                and verdict.state in (STATE_BUSY, STATE_DONE_IDLE) and not clear):
            verdict = AttentionVerdict(
                STATE_UNKNOWN, REASON_EVIDENCE_DISAGREES, TIER_NONE,
                detail="screen did not confirm that the outstanding dialog closed",
            )
        facts = evidence.codex.transcript if evidence.codex is not None else evidence.transcript
        prompt_at = getattr(facts, "newest_user_prompt_at", None)
        append_at = (
            facts.last_append_at if evidence.codex is not None
            else facts.newest_append_at
        )
        new_prompt_at, appended = self._ledger.note_transcript(
            target.key, user_prompt_at=prompt_at, append_at=append_at,
        )
        self._revision += 1
        observation = Observation(verdict, evidence, new_prompt_at, appended,
                                  self._revision, cycle=self._cycles)
        self._observations[target.session_id] = observation
        if new_prompt_at is not None:
            self._startup_quiet.end(target.session_id)
        transition = self._ledger.observe(
            target.key, verdict, evidence.now, last_append_at=append_at,
        )
        if (transition is not None and transition.state == STATE_DONE_IDLE
                and self._startup_quiet.swallows_done(target.session_id, evidence.now)):
            logger.info("attention_startup_turn_quiet", session_id=target.session_id,
                        key=target.key)
            transition = None
        if transition is not None:
            if self._on_transition is not None:
                self._call("attention_transition_hook_failed", target, self._on_transition, target, transition)
            self._act(target, transition)
        if self._on_observation is not None:
            self._call("attention_observation_failed", target,
                       self._on_observation, target, observation)
        return transition is not None

    def _act(self, target: WatchTarget, transition: Transition) -> None:
        if transition.state == STATE_BUSY:
            self._call(
                "attention_busy_edge_failed",
                target,
                self._on_busy_edge,
                target,
                transition,
            )
            return
        if transition.state == STATE_DONE_IDLE:
            self._call(
                "attention_set_unread_failed", target, self._set_unread, target
            )
            if self._on_done_edge is not None:
                self._call("attention_done_edge_failed", target,
                           self._on_done_edge, target, transition)
        kind = _toast_kind_for(transition)
        if kind is None:
            return
        gate = resolve_raise(
            kind,
            policy_store_attached=self._read_policy is not None,
            policy=policy_for(self._read_policy, target),
        )
        if not gate.raises_toast:
            logger.info(
                gate.log_event or "attention_toast_suppressed",
                session_id=target.session_id,
                key=target.key,
                **gate.log_fields,
            )
            return
        logger.info(
            "attention_transition",
            session_id=target.session_id,
            key=target.key,
            state=transition.state,
            reason=transition.reason,
            previous_state=transition.previous_state,
            tier=transition.verdict.tier,
            toast_kind=kind,
        )
        self._call(
            "attention_raise_toast_failed",
            target,
            self._raise_toast,
            target,
            kind,
            transition,
        )

    def _call(
        self, event: str, target: WatchTarget, action: Callable, *args: Any
    ) -> None:
        try:
            action(*args)
        except Exception as exc:
            logger.warning(
                event,
                session_id=target.session_id,
                key=target.key,
                error=str(exc),
                error_type=type(exc).__name__,
            )


    def poke(self, key: str) -> None:
        self._wake.poke(key)

    @property
    def _waiter(self):
        return self._wake.waiter

    def _open_watch(self) -> None:
        self._wake.open()

    def _close_watch(self) -> None:
        self._wake.close()

    async def _wait_for_work(self) -> str:
        return await self._wake.wait(self.tick_seconds)

    async def _backstop(self, timeout: Optional[float] = None) -> bool:
        return await self._wake.backstop(self.tick_seconds if timeout is None else timeout)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
