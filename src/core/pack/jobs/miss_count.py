
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Mapping, Optional, Set, Tuple

import structlog

from src.core.pack.jobs.store import JobStore
from src.core.pack.load.process_tree import Proc
from src.core.pack.reserve import session_demote

logger = structlog.get_logger()

OPEN_CORES, CLOSE_CORES = 1.0, 0.5
OPEN_BEATS, CLOSE_BEATS = 3, 2
DELEGATE_WINDOW_S = 120.0
PEER_CACHE_S = 30.0
DELEGATED, MISS, LOCAL_OK = "delegated", "miss", "local_ok"


class _State:

    def __init__(self, uid: str) -> None:
        self.uid, self.hot, self.cool = uid, 0, 0
        self.hot_since = 0.0
        self.last_active = 0.0
        self.outcome: Optional[str] = None


class MissCounter:

    def __init__(self, store: JobStore, *, sessions_of_marked: Callable[[], Mapping[str, Tuple[str, str]]],
                 recent_delegate: Callable[[str, float], bool], peer_free: Callable[[str], bool],
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> None:
        self._store, self._sessions, self._recent, self._peer = store, sessions_of_marked, recent_delegate, peer_free
        self._clock, self._wall = clock, wall
        self._states: Dict[str, _State] = {}
        self._peer_cache: Dict[str, Tuple[float, bool]] = {}

    def observe(self, procs: List[Proc], panes: Mapping[str, List[int]], argv: Mapping[int, Tuple[str, ...]], pegged: bool) -> None:
        if not pegged:
            for name in list(self._states):
                self._close(name)
            return
        sessions = self._sessions()
        for name in [n for n in self._states if n not in sessions]:
            self._close(name)
        trees = session_demote.session_trees(procs, {n: panes[n] for n in sessions if n in panes}, argv)
        cpu_of = {p.pid: p.cpu for p in procs}
        for name, (uid, session_uuid) in sessions.items():
            cores = sum(cpu_of.get(pid, 0.0) for pid in trees.get(name, ())) / 100.0
            self._step(name, uid, session_uuid, cores)

    def _step(self, name: str, uid: str, session_uuid: str, cores: float) -> None:
        st = self._states.setdefault(name, _State(uid))
        now = self._clock()
        if st.outcome is None:
            if cores < OPEN_CORES:
                st.hot = 0
                return
            st.hot += 1
            st.hot_since = st.hot_since if st.hot > 1 else now
            st.last_active = now
            if st.hot >= OPEN_BEATS:
                st.outcome = self._outcome(uid, session_uuid)
            return
        if cores < CLOSE_CORES:
            st.cool += 1
            if st.cool >= CLOSE_BEATS:
                self._close(name)
            return
        st.cool = 0
        st.last_active = now

    def _outcome(self, uid: str, session_uuid: str) -> str:
        if self._recent(session_uuid, DELEGATE_WINDOW_S):
            return DELEGATED
        return MISS if self._free(uid) else LOCAL_OK

    def _free(self, uid: str) -> bool:
        now = self._clock()
        cached = self._peer_cache.get(uid)
        if cached is None or now - cached[0] >= PEER_CACHE_S:
            try:
                answer = bool(self._peer(uid))
            except (OSError, ValueError, RuntimeError) as exc:
                logger.warning("pack_miss_peer_unread", error=type(exc).__name__)
                answer = False
            cached = self._peer_cache[uid] = (now, answer)
        return cached[1]

    def _close(self, name: str) -> None:
        st = self._states.pop(name, None)
        if st is None or st.outcome is None:
            return
        wall = self._wall()
        day = datetime.fromtimestamp(wall, timezone.utc).strftime("%Y-%m-%d")
        self._store.episode_add(day, st.uid, round(max(0.0, st.last_active - st.hot_since) / 60.0, 2), st.outcome, wall)
