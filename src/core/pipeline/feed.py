
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, Dict, FrozenSet, Optional, Set, Tuple

import structlog

from src.core.pipeline import runtime
from src.core.pipeline.observe import TRIGGER_LIVE

logger = structlog.get_logger()

WORKING: FrozenSet[str] = frozenset({"working", "working_subagent", "running"})
WORKING_LOOK_SECONDS: float = 2.0

PathsFor = Callable[[str], Optional[Tuple[str, str]]]


class LiveFeed:

    def __init__(self, *, paths_for: Callable[[], Optional[PathsFor]],
                 rollout_for: Callable[[], Optional[Callable[[str], Optional[str]]]] = lambda: None,
                 engine: Callable[[], Any] = runtime.current, clock: Callable[[], float] = time.monotonic) -> None:
        self._paths_for = paths_for
        self._rollout_for = rollout_for
        self._engine = engine
        self._clock = clock
        self._last: Dict[str, str] = {}
        self._looked: Dict[str, float] = {}
        self._running: Set[str] = set()
        self._again: Set[str] = set()
        self._tasks: Set["asyncio.Task[None]"] = set()
        self.counters: Dict[str, int] = {"looks": 0, "marked": 0, "errors": 0}

    def on_observation(self, session_id: str, observation: Any, display: str) -> None:
        engine = self._engine()
        if engine is None:
            return
        prior = self._last.get(session_id)
        self._last[session_id] = display
        working = display in WORKING
        edge = prior in WORKING and not working
        appended = bool(getattr(observation, "transcript_appended", False))
        if not (working or edge or appended):
            self._looked.pop(session_id, None)
            return
        now = self._clock()
        if not (edge or appended) and now - self._looked.get(session_id, -WORKING_LOOK_SECONDS) < WORKING_LOOK_SECONDS:
            return
        self._looked[session_id] = now
        if session_id in self._running:
            self._again.add(session_id)
            return
        self._start(session_id, engine)

    def _start(self, session_id: str, engine: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._running.add(session_id)
        task = loop.create_task(self._run(session_id, engine))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, session_id: str, engine: Any) -> None:
        try:
            await asyncio.to_thread(self.look, session_id, engine)
        finally:
            self._running.discard(session_id)
        if session_id in self._again:
            self._again.discard(session_id)
            self._start(session_id, engine)

    def look(self, session_id: str, engine: Any) -> int:
        try:
            paths_for = self._paths_for()
            located = paths_for(session_id) if paths_for is not None else None
            transcript, subagents = located if located is not None else (None, None)
            if transcript is None:
                rollout_for = self._rollout_for()
                transcript = rollout_for(session_id) if rollout_for is not None else None
            if transcript is None:
                return 0
            marked = engine.observer.session_changed(os.path.realpath(transcript),
                                                     os.path.realpath(subagents) if subagents else None, TRIGGER_LIVE)
            self.counters["looks"] += 1
            self.counters["marked"] += marked
            return marked
        except Exception as exc:  # noqa: BLE001
            self.counters["errors"] += 1
            logger.warning("pipeline_feed_look_failed", session=session_id[:12], error=str(exc),
                           error_type=type(exc).__name__)
            return 0
