
from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple

import structlog

from src.core.skill_fires.parse import HARNESS_CLAUDE
from src.core.skill_fires.store import SkillFireStore
from src.core.skill_watch.classify import (
    CREDENTIAL_ACCESS, FILE_DELETE, NETWORK, SETTINGS_WRITE,
)
from src.core.skill_watch.spans import SpanState, advance, new_state
from src.core.skill_watch.store import SkillWatchStore

logger = structlog.get_logger(__name__)

Context = Callable[[str, Optional[str]], Optional[FrozenSet[str]]]
Dynamic = Callable[[str, Optional[str]], FrozenSet[str]]

MAX_FIRES_PER_PASS = 25
MAX_OPEN_SPANS = 64

_NET_TOOL = re.compile(r"^(?:WebFetch|WebSearch)\b", re.I)
_NET_BASH = re.compile(r"\b(?:curl|wget|nc|ncat|ssh|scp|sftp|rsync)\b|https?:", re.I)
_DEL_BASH = re.compile(r"\b(?:rm|rmdir|unlink|shred|trash)\b|git\s+clean", re.I)


@dataclass(frozen=True)
class TripwireFinding:

    skill: str
    category: str


def disclosed_categories(review: Any, allowed_tools: Optional[Sequence[str]]) -> Optional[FrozenSet[str]]:
    reviewed = review is not None and getattr(review, "status", None) == "reviewed"
    if not reviewed and allowed_tools is None:
        return None
    found: set = set()
    if reviewed:
        found.update(str(w.kind) for w in (review.warnings or []))
    for entry in allowed_tools or []:
        text = str(entry)
        bare = text.strip() in ("Bash", "Bash(*)")
        if _NET_TOOL.match(text) or (text.startswith("Bash") and (bare or _NET_BASH.search(text))):
            found.add(NETWORK)
        if text.startswith("Bash") and (bare or _DEL_BASH.search(text)):
            found.add(FILE_DELETE)
        if "settings" in text and text.split("(")[0] in ("Write", "Edit", "MultiEdit"):
            found.add(SETTINGS_WRITE)
        if re.search(r"credentials|auth\.json|\.ssh", text):
            found.add(CREDENTIAL_ACCESS)
    return frozenset(found)


def undisclosed(observed: Sequence[str], disclosed: Optional[FrozenSet[str]]) -> List[str]:
    if disclosed is None:
        return []
    return sorted(set(observed) - disclosed)


class TripwireProbe:

    def __init__(self, fires: SkillFireStore, watch: SkillWatchStore, context: Context,
                 started_at: Optional[str] = None, *, dynamic: Optional[Dynamic] = None,
                 executor: Optional[Executor] = None) -> None:
        self._fires, self._watch, self._context, self._dynamic = fires, watch, context, dynamic
        self._started = started_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        self._executor = executor
        self._lock = threading.Lock()
        self._pending: Dict[str, Future] = {}
        self._seen: Dict[str, Tuple[int, int]] = {}
        self._states: "OrderedDict[Tuple[str, int], SpanState]" = OrderedDict()
        self._claimed: set = set()

    def scan(self, path: str, harness: str) -> Tuple[TripwireFinding, ...]:
        try:
            with self._lock:
                future = self._pending.get(path)
                out: Tuple[TripwireFinding, ...] = ()
                if future is not None and future.done():
                    del self._pending[path]
                    out = tuple(future.result())
                    future = None
                if future is None and harness == HARNESS_CLAUDE:
                    info = os.stat(path)
                    signature = (info.st_ino, info.st_size)
                    if self._seen.get(path) != signature:
                        self._seen[path] = signature
                        if self._executor is None:
                            self._executor = ThreadPoolExecutor(1, thread_name_prefix="tripwire")
                        self._pending[path] = self._executor.submit(self._safe_pass, path, harness)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill_tripwire_failed", error_type=type(exc).__name__)
            return ()

    def _safe_pass(self, path: str, harness: str) -> List[TripwireFinding]:
        try:
            return list(self.scan_now(path, harness))
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill_tripwire_failed", error_type=type(exc).__name__)
            with self._lock:
                self._seen.pop(path, None)
            return []

    def scan_now(self, path: str, harness: str) -> Tuple[TripwireFinding, ...]:
        cursor = self._watch.tripwire_offset(path)
        if cursor is None:
            cursor = self._fires.max_offset_before(path, self._started)
            self._watch.set_tripwire_offset(path, cursor)
        session_key = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        out: List[TripwireFinding] = []
        judged: Dict[Tuple[str, Optional[str]], Tuple[Optional[FrozenSet[str]], FrozenSet[str]]] = {}
        fires = self._fires.offsets_of(path, cursor)
        if len(fires) > MAX_FIRES_PER_PASS:
            with self._lock:
                self._seen.pop(path, None)
        for off, skill in fires[:MAX_FIRES_PER_PASS]:
            state = self._states.pop((path, off), None) or new_state(off)
            if harness != HARNESS_CLAUDE or not advance(path, state):
                self._watch.set_tripwire_offset(path, off)
                continue
            key = (skill, state.cwd)
            if key not in judged:
                disclosed = self._context(skill, state.cwd)
                extra = self._dynamic(skill, state.cwd) if self._dynamic and disclosed is not None else frozenset()
                judged[key] = (disclosed, extra)
            disclosed, extra = judged[key]
            for category in undisclosed(sorted(set(state.facts.categories) | extra), disclosed):
                claim = (session_key, skill, category)
                if claim in self._claimed:
                    continue
                self._claimed.add(claim)
                if self._watch.claim_alert(*claim):
                    out.append(TripwireFinding(skill, category))
            if not state.done:
                self._states[(path, off)] = state
                while len(self._states) > MAX_OPEN_SPANS:
                    self._states.popitem(last=False)
                break
            self._watch.set_tripwire_offset(path, off)
        return tuple(out)


def notice_copy(findings: Sequence[TripwireFinding]) -> Tuple[str, str]:
    detail = ", ".join(f"{f.skill}: {f.category.replace('_', ' ')}" for f in findings[:4])
    return ("a skill did something its review did not mention",
            f"{detail}. advisory only, nothing was blocked.")
