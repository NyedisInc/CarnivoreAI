"""Stop several background processes at once, each one guarded (issue #1053).

The foot bar's control center has two "stop many" controls: "stop all"
over the background processes section, and a sub-agent's "stop", which
stops the processes that sub-agent launched (:mod:`.attribution`). Both
send the ``(pid, start)`` pairs the listing handed out, and only those.

EVERY TARGET GOES THROUGH THE SAME GUARD AS A SINGLE STOP. One fresh
measurement of the pane, then :func:`.guard.check` for each target
against it: a refused target is reported with its code and nothing of it
is signalled, while the others proceed. The allowed targets' subtrees
are merged (a pid under two targets is signalled once) and handed to ONE
:func:`.terminate.terminate` call, so the batch costs one bounded
SIGTERM wait, not one per target, and the terminator's identity re-check
before every signal still applies to every member.

THE CLIENT'S LIST IS A CEILING, NEVER A FLOOR. A process that started
after the listing was read is not in the pairs and is never stopped by
"stop all": the user confirmed a count, and that count is what is acted on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from src.core.background_work import guard as bw_guard
from src.core.background_work.terminate import (
    OUTCOME_ALREADY_GONE,
    OUTCOME_KILLED,
    OUTCOME_STILL_RUNNING,
    OUTCOME_TERMINATED,
    Member,
    TerminateResult,
)
from src.core.background_work.tree import PaneTree

OUTCOME_REFUSED: str = "refused"


@dataclass(frozen=True)
class TargetOutcome:

    pid: int
    outcome: str
    code: Optional[str]
    detail: str


def plan(
    tree: PaneTree,
    targets: Sequence[Tuple[int, str]],
    *,
    self_pids: Iterable[int] = (),
) -> Tuple[List[Tuple[int, bw_guard.Verdict]], Tuple[Member, ...]]:
    protected = tuple(self_pids)
    verdicts: List[Tuple[int, bw_guard.Verdict]] = []
    seen_targets = set()
    for pid, start in targets:
        if pid in seen_targets:
            continue
        seen_targets.add(pid)
        verdicts.append((pid, bw_guard.check(tree, pid, start, self_pids=protected)))
    members: List[Member] = []
    seen_members = set()
    for _pid, verdict in verdicts:
        for member in verdict.subtree:
            if member[0] not in seen_members:
                seen_members.add(member[0])
                members.append(member)
    return verdicts, tuple(members)


def outcomes(
    verdicts: Sequence[Tuple[int, bw_guard.Verdict]],
    result: Optional[TerminateResult],
) -> List[TargetOutcome]:
    unmeasured = (result is not None and result.outcome == OUTCOME_STILL_RUNNING
                  and not result.survivors)
    answers: List[TargetOutcome] = []
    for pid, verdict in verdicts:
        if not verdict.allowed:
            gone = verdict.code == bw_guard.REFUSE_GONE
            answers.append(TargetOutcome(
                pid=pid, outcome=OUTCOME_ALREADY_GONE if gone else OUTCOME_REFUSED,
                code=None if gone else verdict.code, detail=verdict.detail,
            ))
            continue
        if result is None:
            outcome = OUTCOME_ALREADY_GONE
        elif pid in result.survivors:
            outcome = OUTCOME_STILL_RUNNING
        elif pid in result.kill:
            outcome = OUTCOME_KILLED
        elif pid in result.term:
            outcome = OUTCOME_STILL_RUNNING if unmeasured else OUTCOME_TERMINATED
        else:
            outcome = OUTCOME_ALREADY_GONE
        answers.append(TargetOutcome(pid=pid, outcome=outcome, code=None,
                                     detail=result.errors.get(pid, verdict.detail)
                                     if result is not None else verdict.detail))
    return answers


__all__ = ["OUTCOME_REFUSED", "TargetOutcome", "outcomes", "plan"]
