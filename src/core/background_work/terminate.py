"""Stop a verified process and its subtree: SIGTERM, then SIGKILL (issue #1044).

ONLY WHAT THE GUARD ALLOWED, ONLY WHILE IT IS STILL THE SAME PROCESS. The
caller passes the ``(pid, start)`` pairs :func:`.guard.check` returned from
a fresh snapshot. Immediately before each signal this module asks ``ps``
again for exactly those pids and signals a pid only while it still reports
the same start: a process that exited, and a reused pid, are never
signalled. The window left between that ``ps`` and ``kill(2)`` is the
lifetime of one syscall, and to be hit a process must exit AND the kernel
hand its pid to a new one inside it; macOS offers no pidfd to close it.

WHY THE SUBTREE. A background Bash call is a ``zsh -c`` whose commands are
its children (``ssh`` and a ``head`` in the measured Daily Bulletin case).
SIGTERM to the shell alone leaves those running, re-parented to launchd.
Every member got its start token from the same snapshot, so re-parenting
after the shell dies does not change which processes are signalled.

A ZOMBIE IS GONE. An exited child its parent has not reaped still answers
``kill(pid, 0)``; ``ps`` reports it with a ``Z`` state, read here as gone.

BOUNDED: :data:`TERM_WAIT_SECONDS` for SIGTERM to work, then SIGKILL to the
survivors and :data:`KILL_WAIT_SECONDS` more. A process in uninterruptible
sleep can survive even SIGKILL for a while; that is reported, never hidden.
"""

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
    """``ps`` could not be run to check which members are alive."""


@dataclass
class TerminateResult:

    outcome: str
    term: List[int] = field(default_factory=list)
    kill: List[int] = field(default_factory=list)
    survivors: List[int] = field(default_factory=list)
    errors: Dict[int, str] = field(default_factory=dict)


def live_members(members: Sequence[Member]) -> FrozenSet[Member]:
    """Which of these (pid, start) pairs are still that process, alive.

    Inputs: members (Sequence[tuple[int, str]]).
    Output: frozenset of the members alive with the same start, not zombies.
    Raises: LivenessUnmeasured - ps could not run.
    Example: live_members([(os.getpid(), 'x')]) -> frozenset()  # start differs
    """
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
