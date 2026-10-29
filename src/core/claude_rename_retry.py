
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from src.core.claude_title_sync import (
    TITLE_APPLIED,
    TITLE_BASELINE_RECORDED,
    TITLE_NOT_MEASURED,
    TITLE_UNCHANGED,
)


MAX_PUSH_ATTEMPTS: int = 5

MIN_ATTEMPT_INTERVAL_SECONDS: float = 60.0

# could not

RETRY_PUSH: str = "push"

RETRY_AGREED: str = "agreed"

RETRY_SUPERSEDED: str = "superseded"

RETRY_UNORDERED: str = "unordered"

RETRY_UNREADABLE: str = "unreadable"

RETRY_EXHAUSTED: str = "exhausted"

RETRY_WAITING: str = "waiting"

TERMINAL_VERDICTS = (RETRY_SUPERSEDED, RETRY_EXHAUSTED)


@dataclass(frozen=True)
class RenameMark:

    agreed_title: Optional[str] = None
    attempted_label: Optional[str] = None
    attempts: int = 0
    last_attempt_at: Optional[float] = None


@dataclass(frozen=True)
class RetryDecision:

    verdict: str
    label: Optional[str] = None
    attempts_spent: int = 0
    detail: Optional[str] = None

    @property
    def acts(self) -> bool:
        return self.verdict == RETRY_PUSH


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def witness_agreement(
    *, title: Optional[str], claude_title: Optional[str]
) -> Optional[str]:
    left = _clean(title)
    right = _clean(claude_title)
    if left is not None and left == right:
        return left
    return None


def budget_for(mark: Optional[RenameMark], label: str) -> int:
    if mark is None or mark.attempted_label != label:
        return 0
    return max(0, int(mark.attempts or 0))


def decide_retry(
    *,
    sync_action: str,
    title: Optional[str],
    claude_title: Optional[str],
    mark: Optional[RenameMark],
    now: float,
    max_attempts: int = MAX_PUSH_ATTEMPTS,
    min_interval_seconds: float = MIN_ATTEMPT_INTERVAL_SECONDS,
) -> RetryDecision:
    """Whether to re-push a browser rename that never reached Claude.

    Description: PURE, and the whole policy. The ladder, in order, with
      the reason each rung sits where it does:

      1. The transcript could not be read -> :data:`RETRY_UNREADABLE`.
         FIRST, because a reading that did not happen decides nothing and
         must not be charged against the budget.
      2. The sync WROTE this pass -> :data:`RETRY_SUPERSEDED`. An
         ``APPLIED`` means Claude renamed after we last looked, so
         Claude's name is the newer one and pushing over it is exactly
         the clobber this module exists to avoid. A ``BASELINE`` means
         first sight, which by this project's standing rule establishes
         no ordering at all.
      3. The columns agree -> :data:`RETRY_AGREED`. The steady state.
      4. The ordering frame is missing or overtaken ->
         :data:`RETRY_UNORDERED`. See the module docstring: a divergence
         with no witnessed agreement behind it may be a baseline that
         landed on a row whose visible label was already different, and
         that case genuinely cannot be ordered.
      5. The budget for this label is spent -> :data:`RETRY_EXHAUSTED`.
      6. The last push is younger than the interval floor ->
         :data:`RETRY_WAITING`.
      7. Otherwise -> :data:`RETRY_PUSH`.

      Note rung 2 is reached only on a pass that actually wrote, so the
      surviving path into rung 4 is ``TITLE_UNCHANGED``: the transcript's
      newest ``custom-title`` was READ and equals ``claude_title``. That
      is the positive confirmation described in the module docstring, and
      it is why a ``CUSTOM_TITLE_NO_RECORD`` window - which arrives here
      as ``TITLE_NOT_MEASURED`` - authorises nothing.
    Inputs: sync_action (str) - a ``claude_title_sync.TITLE_*`` verdict
      from this same pass. title (str | None) - ``sessions.title`` after
      the pass. claude_title (str | None) - ``sessions.claude_title``
      after the pass. mark (RenameMark | None) - the row's ledger entry.
      now (float) - unix seconds. max_attempts (int). min_interval_seconds
      (float).
    Output: RetryDecision.
    Example: decide_retry(sync_action=TITLE_UNCHANGED, title='New',
      claude_title='Old', mark=RenameMark(agreed_title='Old'),
      now=0.0).verdict -> 'push'
    """
    if sync_action == TITLE_NOT_MEASURED:
        return RetryDecision(
            RETRY_UNREADABLE,
            detail=(
                "the transcript said nothing this pass, so whether claude "
                "still holds the recorded name is unknown and no attempt "
                "is spent"
            ),
        )

    if sync_action in (TITLE_APPLIED, TITLE_BASELINE_RECORDED):
        return RetryDecision(
            RETRY_SUPERSEDED,
            detail=(
                "the transcript moved this pass, so claude's name is the "
                "newer one and a browser push would overwrite it"
            ),
        )

    label = _clean(title)
    recorded = _clean(claude_title)

    if label is None or recorded is None or label == recorded:
        return RetryDecision(
            RETRY_AGREED,
            detail="both sides carry the same name, so nothing is pending",
        )

    if mark is None or mark.agreed_title is None:
        return RetryDecision(
            RETRY_UNORDERED,
            detail=(
                "the two names disagree and no agreement has ever been "
                "witnessed for this row, so which of them is newer cannot "
                "be established - refusing rather than guessing"
            ),
        )

    if mark.agreed_title != recorded:
        return RetryDecision(
            RETRY_UNORDERED,
            detail=(
                "claude's recorded name has moved since the last witnessed "
                "agreement, so the browser label can no longer be shown to "
                "be the newer one"
            ),
        )

    spent = budget_for(mark, label)
    if spent >= max(0, int(max_attempts)):
        return RetryDecision(
            RETRY_EXHAUSTED,
            label=label,
            attempts_spent=spent,
            detail=(
                f"{spent} pushes have been spent on this name and the bound "
                f"is {max_attempts}; this rename will not be attempted again"
            ),
        )

    last = mark.last_attempt_at if mark.attempted_label == label else None
    if last is not None and (now - float(last)) < float(min_interval_seconds):
        return RetryDecision(
            RETRY_WAITING,
            label=label,
            attempts_spent=spent,
            detail=(
                "the previous push for this name is younger than the "
                "interval floor, so this pass holds without spending an "
                "attempt"
            ),
        )

    return RetryDecision(
        RETRY_PUSH,
        label=label,
        attempts_spent=spent,
        detail=(
            "claude's name has not moved since the last witnessed "
            "agreement, so the browser label is the newer one and is "
            "pushed again"
        ),
    )


def record_attempt(
    mark: Optional[RenameMark], *, label: str, now: float
) -> RenameMark:
    base = mark or RenameMark()
    spent = budget_for(base, label)
    return replace(
        base, attempted_label=label, attempts=spent + 1, last_attempt_at=float(now)
    )


def record_agreement(mark: Optional[RenameMark], agreed: str) -> RenameMark:
    return RenameMark(
        agreed_title=agreed,
        attempted_label=None,
        attempts=0,
        last_attempt_at=None,
    )


__all__ = [
    "MAX_PUSH_ATTEMPTS",
    "MIN_ATTEMPT_INTERVAL_SECONDS",
    "RETRY_AGREED",
    "RETRY_EXHAUSTED",
    "RETRY_PUSH",
    "RETRY_SUPERSEDED",
    "RETRY_UNORDERED",
    "RETRY_UNREADABLE",
    "RETRY_WAITING",
    "TERMINAL_VERDICTS",
    "RenameMark",
    "RetryDecision",
    "budget_for",
    "decide_retry",
    "record_agreement",
    "record_attempt",
    "witness_agreement",
    "TITLE_UNCHANGED",
]
