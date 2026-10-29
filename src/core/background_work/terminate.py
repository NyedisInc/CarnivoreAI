
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Sequence, Tuple

import structlog

from src.core.conversation_writers import normalise_lstart

logger = structlog.get_logger(__name__)

TERM_WAIT_SECONDS: float = 3.0
KILL_WAIT_SECONDS: float = 1.0
POLL_SECONDS: float = 0.1
PS_TIMEOUT_SECONDS: float = 5.0

OUTCOME_TERMINATED: str = "terminated"
OUTCOME_KILLED: str = "killed"
OUTCOME_STILL_RUNNING: str = "still_running"
OUTCOME_ALREADY_GONE: str = "already_gone"

Member = Tuple[int, str]


class LivenessUnmeasured(Exception):
    pass


@dataclass
class TerminateResult:

    outcome: str
    term: List[int] = field(default_factory=list)
    kill: List[int] = field(default_factory=list)
    survivors: List[int] = field(default_factory=list)
    errors: Dict[int, str] = field(default_factory=dict)


def live_members(members: Sequence[Member]) -> FrozenSet[Member]:
    if not members:
        return frozenset()
    wanted = {pid: normalise_lstart(start) for pid, start in members}
    argv = ["/bin/ps", "-o", "pid=,stat=,lstart=", "-p", ",".join(str(p) for p in wanted)]
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=PS_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LivenessUnmeasured(f"ps could not run: {exc}") from exc
    if done.returncode not in (0, 1):
        raise LivenessUnmeasured(f"ps exited {done.returncode}")
    alive = set()
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if parts[1].startswith("Z"):
            continue
        if wanted.get(pid) == normalise_lstart(" ".join(parts[2:7])):
            alive.add((pid, wanted[pid]))
    return frozenset(alive)


def _send(pids: Sequence[int], sig: int, result: TerminateResult, sent: List[int],
          sender: Callable[[int, int], None]) -> None:
    for pid in pids:
        try:
            sender(pid, sig)
            sent.append(pid)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            result.errors[pid] = f"{signal.Signals(sig).name} refused: {exc.strerror}"


def _wait_gone(members: Sequence[Member], seconds: float,
               prober: Callable[[Sequence[Member]], FrozenSet[Member]],
               sleep: Callable[[float], None]) -> FrozenSet[Member]:
    deadline = time.monotonic() + seconds
    alive = prober(members)
    while alive and time.monotonic() < deadline:
        sleep(POLL_SECONDS)
        alive = prober(list(alive))
    return alive


def terminate(
    members: Sequence[Member],
    *,
    sender: Callable[[int, int], None] = os.kill,
    prober: Callable[[Sequence[Member]], FrozenSet[Member]] = live_members,
    sleep: Callable[[float], None] = time.sleep,
) -> TerminateResult:
    order = [pid for pid, _ in members]
    alive = prober(members)
    if not alive:
        return TerminateResult(outcome=OUTCOME_ALREADY_GONE)
    result = TerminateResult(outcome=OUTCOME_TERMINATED)
    alive_pids = {pid for pid, _ in alive}
    _send([p for p in order if p in alive_pids], signal.SIGTERM, result, result.term, sender)
    try:
        left = _wait_gone(list(alive), TERM_WAIT_SECONDS, prober, sleep)
        if left:
            left = prober(list(left))
            left_pids = {pid for pid, _ in left}
            _send([p for p in order if p in left_pids], signal.SIGKILL, result, result.kill, sender)
            result.outcome = OUTCOME_KILLED
            left = _wait_gone(list(left), KILL_WAIT_SECONDS, prober, sleep)
    except LivenessUnmeasured as exc:
        logger.warning("background_work_liveness_unmeasured", error=str(exc), term=result.term)
        result.outcome = OUTCOME_STILL_RUNNING
        result.errors[order[0]] = f"could not re-check liveness: {exc}"
        return result
    result.survivors = sorted(pid for pid, _ in left)
    if result.survivors:
        result.outcome = OUTCOME_STILL_RUNNING
    return result


__all__ = [
    "KILL_WAIT_SECONDS", "LivenessUnmeasured", "OUTCOME_ALREADY_GONE", "OUTCOME_KILLED",
    "OUTCOME_STILL_RUNNING", "OUTCOME_TERMINATED", "TERM_WAIT_SECONDS", "TerminateResult",
    "live_members", "terminate",
]
