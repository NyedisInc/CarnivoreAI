"""Is the permission prompt this session claims to be blocked on ACTUALLY there?

THE INCIDENT, TRACED TO THE ID. ``cloude_Image_Tool`` painted the
orange permission light with NO dialog on its pane: the tail read a settings
warning, a typed-but-unsubmitted prompt line, and ``bypass permissions on``.
The flag was set at 17:55:12.165Z on session id ``ses_d366e076``. The claude
running in that pane was measured (its own process environment) to hold
``CLOUDECODE_SESSION_ID=adopted:cloude_Image_Tool`` - a spawn-time
value tmux cannot rewrite into a running process - so the pane's own
``UserPromptSubmit`` 8s later, and both of its later ``Stop`` events, all
landed on a DIFFERENT tracker key. The hook store held tokens for both ids
against the one tmux name, so nothing was rejected and nothing looked wrong.

         Bash command

           date +%s
           Print current Unix timestamp

         Ask rule Bash overrides auto mode for this command.
         /permissions to let auto mode decide

         Do you want to proceed?
         > 1. Yes
           2. No

         Esc to cancel . Tab to amend

    Write tool, ask rule on "Write", Bash denied so it could not fall back

         Create file
         note2.txt
         ...
         Do you want to create note2.txt?
         > 1. Yes
           2. No

         Esc to cancel . Tab to amend

DIRECTION OF ERROR, STATED OUT LOUD. A false POSITIVE here (matching text that
is not a dialog) keeps a flag that is already set, which is the status quo and
costs nothing new. A false NEGATIVE (failing to see a real dialog) clears a
flag that should have stood, and paints a blocked session as idle - the
false-green shape this project keeps removing. So the matcher is deliberately
broad, three independent markers, ANY of which keeps the flag; and a tail that
could not be READ keeps it too, because not having looked is not evidence of
absence.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Pattern, Union

PERMISSION_TAIL_GRACE_SECONDS: int = 20

# : conversation,
PERMISSION_TAIL_LINES: int = 60

# could not be read
PERMISSION_TAIL_RECHECK_SECONDS: int = 30

PERMISSION_KEPT_DIALOG: str = "kept_dialog_present"
PERMISSION_KEPT_UNREADABLE: str = "kept_tail_unreadable"
PERMISSION_CLEARED_NO_DIALOG: str = "cleared_no_dialog"
PERMISSION_CLEARED_PANE_DEAD: str = "cleared_pane_dead"
PERMISSION_NOT_CHECKED: str = "not_checked"

PERMISSION_DIALOG_MARKERS: tuple[Union[str, Pattern[str]], ...] = (
    re.compile(r"^\s*Do you want to .{0,120}\?\s*$", re.M),
    re.compile(r"^\s*❯\s*1\.\s*Yes\b", re.M),
    "Esc to cancel · Tab to amend",
)


def detect_permission_dialog(tail: Optional[str]) -> Optional[bool]:
    """Does this scrollback tail show a permission dialog?

    Description: the matcher, split from the ladder so it can be tested on
        text alone - including against NEGATIVE CONTROLS, which for this
        family are mandatory. ``tests/test_session_permission_verify.py``
        feeds it the real steady-state footer of a busy claude AND the
        actual captured tail of the stuck live session, and requires
        ``False`` for both; a matcher that always finds something would
        pass every positive test and clear nothing, forever.
    Inputs:
        tail: captured pane text, or None when no capture was made.
    Output:
        bool | None - True when a marker matched, False when the text was
        read and no marker matched, None when there was no text to read.
        The None is load-bearing: "we did not look" and "we looked and it
        is not there" route differently in ``resolve_permission_check``.
    Example:
        >>> detect_permission_dialog("  Do you want to proceed?")
        True
        >>> detect_permission_dialog(None) is None
        True
    """
    if tail is None:
        return None
    for marker in PERMISSION_DIALOG_MARKERS:
        if isinstance(marker, str):
            if marker in tail:
                return True
        elif marker.search(tail):
            return True
    return False


def should_capture_permission_tail(
    *,
    pane_alive: Optional[bool],
    permission_open: bool,
    opened_at: Optional[datetime],
    now: datetime,
    grace_seconds: int = PERMISSION_TAIL_GRACE_SECONDS,
    last_check_at: Optional[datetime] = None,
    recheck_seconds: int = PERMISSION_TAIL_RECHECK_SECONDS,
) -> bool:
    """Is reading this pane's scrollback worth a subprocess call?

    Description: the COST GATE, and the reason this feature is free in
        steady state - the same shape as
        ``session_startup_gate.should_capture_tail``, and separate from
        the resolver for the same reason: the resolver must stay pure and
        the caller must decide whether to PAY for a tail before it has
        one.

        The gated set is normally EMPTY, and unlike its sibling in
        ``session_startup_gate`` that claim has been checked. It admits
        only a pane that is measured alive, holds an OPEN permission
        claim, and has held it for longer than the grace window. Every
        one of those refusals is FAIL-CLOSED: a session with no record at
        all has no open claim and no stamp, so it refuses. The startup
        gate's equivalent refusal is fail-OPEN (a missing in-memory hook
        record makes it PASS), which is exactly why that one was costing
        13 of 13 healthy sessions a capture per poll while this one costs
        nothing. Do not move this capture into the unconditional listing
        path.

        THE FOURTH REFUSAL IS THE RE-LOOK, and it is the only cost that
        was ever real here. Both verdicts that KEEP the flag leave this
        gate passing again next poll, so a genuinely open claim paid one
        subprocess every 5s until a human answered it. A reading younger
        than ``recheck_seconds`` now stands instead. A ``last_check_at``
        of None means nothing has been read for this claim, which reads
        as "look now" - so the FIRST look is never delayed and the
        stuck-flag case this module exists for is caught exactly as
        promptly as before.
    Inputs:
        pane_alive: True/False/None from the caller's liveness read. Only
            True qualifies - a pane that could not be read cannot be
            captured either, and a dead one has no dialog to answer.
            ``False`` (MEASURED dead, as opposed to unmeasured) refuses a
            capture here for that reason, but is not the same as "leave
            the flag alone": ``verify_open_permission`` checks for a
            measured-dead pane BEFORE calling this gate at all and clears
            the flag directly, with no tail needed, since there is
            nothing left to capture a tail from. This gate's False and
            None therefore agree only on "do not spend a subprocess" -
            they disagree on what happens to the flag, one level up.
        permission_open: the flag as the tracker holds it.
        opened_at: when the flag went False -> True, or None. None with
            the flag SET means the stamp was lost (a signal that predates
            this field, e.g. across a hot reload); it refuses rather than
            capturing, because a claim that cannot be dated cannot be
            shown to be past its grace window.
        now: injectable clock.
        grace_seconds: override for tests.
        last_check_at: when this claim's pane was last READ, or None when
            it has not been. None never throttles - not having looked is
            not a reason to keep not looking.
        recheck_seconds: how long a reading stands. Override for tests.
    Output:
        bool - True when the caller should capture a tail and pass it to
        ``resolve_permission_check``.
    Example:
        >>> from datetime import datetime, timedelta
        >>> t0 = datetime(2026, 9, 9, 12, 0, 0)
        >>> should_capture_permission_tail(
        ...     pane_alive=True, permission_open=True, opened_at=t0,
        ...     now=t0 + timedelta(seconds=99))
        True
    """
    if pane_alive is not True:
        return False
    if not permission_open:
        return False
    if opened_at is None:
        return False
    if (now - opened_at).total_seconds() < grace_seconds:
        return False
    if (
        last_check_at is not None
        and (now - last_check_at).total_seconds() < recheck_seconds
    ):
        return False
    return True


def resolve_permission_check(
    *,
    captured: bool,
    tail: Optional[str],
) -> str:
    """Turn one pane read into a verdict on the open permission claim.

    Description: the pure ladder. THREE OUTCOMES AND ONLY ONE OF THEM
        CLEARS, which is the whole design:

          1. No capture was attempted (the cost gate refused, or the flag
             is not open) -> ``PERMISSION_NOT_CHECKED``. Says nothing
             about the flag.
          2. A tail was read and a marker matched -> ``KEPT_DIALOG``. The
             agent really is parked; the hook was right.
          3. A tail was read and NO marker matched -> ``CLEARED_NO_DIALOG``.
             The one branch that retires the flag, and the only one with
             positive evidence behind it.
          4. A capture was attempted and produced nothing readable ->
             ``KEPT_UNREADABLE``. REFUSES TO CLEAR. Not having managed to
             look is not evidence that the dialog is gone, and clearing
             here would turn every transient tmux hiccup into a green
             light on a blocked session.

        Note ``captured`` is passed rather than inferred from
        ``tail is None``: both a refused capture and a failed one hand back
        None, and they are different facts. Only the second is a
        measurement that did not answer.
    Inputs:
        captured: True when the caller actually ran a capture for this
            session on this poll.
        tail: what the capture returned - text, or None when it failed.
    Output:
        str - one of the four ``PERMISSION_*`` verdicts.
    Example:
        >>> resolve_permission_check(captured=True, tail="idle prompt")
        'cleared_no_dialog'
        >>> resolve_permission_check(captured=True, tail=None)
        'kept_tail_unreadable'
        >>> resolve_permission_check(captured=False, tail=None)
        'not_checked'
    """
    if not captured:
        return PERMISSION_NOT_CHECKED
    seen = detect_permission_dialog(tail)
    if seen is None:
        return PERMISSION_KEPT_UNREADABLE
    return PERMISSION_KEPT_DIALOG if seen else PERMISSION_CLEARED_NO_DIALOG
