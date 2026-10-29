"""Is this session blocked on an unanswered STARTUP prompt?

  - Launched in an UNTRUSTED directory: pane born at epoch 1788880316,
    alive, ``#{pane_dead}=0``. At +15s the trust dialog was on screen and
    the listener had received ZERO POSTs. The dialog was answered at
    +34s; the FIRST hook of the session, ``SessionStart``, landed 1.76s
    later, at +35.8s.
  - Launched in the SAME directory once trusted, three consecutive runs:
    ``SessionStart`` landed 0.49s, 0.50s and 0.41s after pane birth.

So a hook for this instance is positive proof startup finished, and
roughly half a second is the normal cost of getting one.

WHY A SEPARATE FIELD AND NOT A SIXTH ``activity_status``. The activity
vocabulary in ``session_status.py`` describes what the AGENT is doing
once it is running. This describes whether it has started running at
all, which is a different question with a different evidence base (no
hook has EVER fired here, so the activity machine is by definition in
its tmux-fallback path). Folding them would make every existing consumer
of ``activity_status`` handle a state it has no vocabulary for.

THE THREE OUTCOMES, AND WHAT EACH ONE CLAIMS.

  ``ready``                    measured NO. Either a hook has fired for
                               this instance, or the pane's process is
                               gone, or the scrollback was READ and
                               carries no startup prompt. Note the exact
                               claim: "not blocked on a startup prompt".
                               It is NOT a claim that the session is
                               healthy - a dead pane answers ``ready``
                               here because a corpse is certainly not
                               waiting for a keypress, and
                               ``activity_status`` is the field that says
                               it is dead.
  ``awaiting_startup_prompt``  measured YES. A live pane, past the grace
                               window, no hook for this instance, and a
                               startup prompt POSITIVELY MATCHED in the
                               scrollback tail.
  ``unknown``                  could not determine. Pane liveness did not
                               answer, the instance could not be dated,
                               the grace window has not elapsed, or the
                               tail could not be captured. Not having
                               looked is never evidence of absence.

A HOOK OUTRANKS THE SCROLLBACK, ALWAYS, AND THAT ORDER IS THE POINT. The
trust dialog does not clear itself off the pane's history when it is
answered: ``capture-pane`` keeps showing it for as long as it is in
scrollback. So a session that answered the prompt an hour ago still has
the marker text sitting in its tail. Reading the tail first would pin
that session at ``awaiting_startup_prompt`` forever. Old scrollback is
STALE EVIDENCE, and the hook is the fresh fact that supersedes it.
``resolve_startup_gate`` therefore tests the hook before it ever looks at
the text, and ``tests/test_session_startup_gate.py`` pins that ordering.

THIS MODULE IS PURE. The per-instance bookkeeping (``StartupGateLedger``)
and the one tmux read (``capture_pane_tail``) live next door in
``src/core/session_startup_gate_ledger.py``, so the ladder above can be
tested without a tmux server and without mutable state.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Pattern, Union



GATE_READY: str = "ready"

GATE_AWAITING: str = "awaiting_startup_prompt"

GATE_UNKNOWN: str = "unknown"

ALL_STARTUP_GATES: tuple[str, ...] = (GATE_READY, GATE_AWAITING, GATE_UNKNOWN)


STARTUP_HOOK_GRACE_SECONDS: int = 20

STARTUP_TAIL_LINES: int = 200

STARTUP_TAIL_RECHECK_SECONDS: int = 30



Marker = Union[str, Pattern[str]]

SCREEN_TRUST: str = "trust"
SCREEN_OAUTH: str = "oauth_login"
SCREEN_CODEX_TRUST: str = "codex_trust"
SCREEN_EXTERNAL_IMPORTS: str = "external_imports"
SCREEN_MCP_SERVER: str = "mcp_server"
SCREEN_BYPASS_PERMISSIONS: str = "bypass_permissions"
SCREEN_RESUME_PICKER: str = "resume_picker"
SCREEN_ONBOARDING_THEME: str = "onboarding_theme"
SCREEN_LOGIN_METHOD: str = "login_method"
SCREEN_DEV_CHANNELS: str = "dev_channels"
SCREEN_CHROME: str = "chrome_extension"
SCREEN_UNRECOGNIZED: str = "unrecognized"

SHARED_FOOTER_MARKER: str = "Enter to confirm · Esc to cancel"

STARTUP_SCREEN_MARKERS: tuple[tuple[str, Marker], ...] = (
    (SCREEN_TRUST, "Quick safety check: Is this a project you created or one you trust?"),
    (SCREEN_TRUST, "Claude Code'll be able to read, edit, and execute files here."),
    (SCREEN_TRUST, re.compile(r"Yes, I trust this folder", re.M)),
    (SCREEN_OAUTH, re.compile(r"claude\.com/cai/oauth/authorize")),
    (SCREEN_CODEX_TRUST, "Do you trust the contents of this directory?"),
    (SCREEN_EXTERNAL_IMPORTS, re.compile(r"Allow\s+external\s+CLAUDE\.md\s+file\s+imports\?")),
    (SCREEN_EXTERNAL_IMPORTS, re.compile(r"Yes,\s+allow\s+external\s+imports")),
    (SCREEN_MCP_SERVER, re.compile(r"New\s+MCP\s+server\s+found\s+in\s+this\s+project")),
    (SCREEN_MCP_SERVER, re.compile(r"Continue\s+without\s+using\s+this\s+MCP\s+server")),
    (SCREEN_BYPASS_PERMISSIONS, re.compile(r"WARNING:\s+Claude\s+Code\s+running\s+in\s+Bypass\s+Permissions\s+mode")),
    (SCREEN_RESUME_PICKER, re.compile(r"Ctrl\+A\s+to\s+show\s+all\s+projects")),
    (SCREEN_ONBOARDING_THEME, re.compile(r"Choose\s+the\s+text\s+style\s+that\s+looks\s+best\s+with\s+your\s+terminal")),
    (SCREEN_LOGIN_METHOD, re.compile(r"Select\s+login\s+method:")),
    (SCREEN_DEV_CHANNELS, re.compile(r"WARNING:\s+Loading\s+development\s+channels")),
    (SCREEN_CHROME, re.compile(r"Claude\s+in\s+Chrome\s+extension\s+detected")),
    (SCREEN_TRUST, SHARED_FOOTER_MARKER),
)

STARTUP_PROMPT_MARKERS: tuple[Marker, ...] = tuple(marker for _, marker in STARTUP_SCREEN_MARKERS)


def _marker_hits(marker: Marker, text: str) -> bool:
    if isinstance(marker, str):
        return marker in text
    return marker.search(text) is not None


def startup_screen_kind(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for kind, marker in STARTUP_SCREEN_MARKERS:
        if _marker_hits(marker, text):
            return kind
    return None


def named_startup_marker_spans(text: Optional[str]) -> list[tuple[str, int, int]]:
    if not text:
        return []
    spans: list[tuple[str, int, int]] = []
    for kind, marker in STARTUP_SCREEN_MARKERS:
        if marker == SHARED_FOOTER_MARKER:
            continue
        if isinstance(marker, str):
            at = text.find(marker)
            if at >= 0:
                spans.append((kind, at, at + len(marker)))
        else:
            found = marker.search(text)
            if found is not None:
                spans.append((kind, found.start(), found.end()))
    return spans


def detect_startup_prompt(tail: Optional[str]) -> Optional[bool]:
    """Does this scrollback tail show a blocking startup prompt?

    Description: the matcher, split out from the ladder so it can be
        tested on text alone - including against a NEGATIVE CONTROL. A
        matcher that always finds something is worse than useless, so
        ``tests/test_session_startup_gate.py`` feeds it a steady-state
        claude footer and requires ``False``.
    Inputs:
        tail: captured scrollback text, or None when no capture was made.
    Output:
        bool | None - True when a marker matched, False when the text was
        read and no marker matched, None when there was no text to read.
        The None is not a convenience: "we did not look" and "we looked
        and it is not there" are different answers and the caller routes
        them differently.
    Example:
        >>> detect_startup_prompt("  Yes, I trust this folder")
        True
        >>> detect_startup_prompt(None) is None
        True
    """
    if tail is None:
        return None
    return any(_marker_hits(marker, tail) for marker in STARTUP_PROMPT_MARKERS)


def should_capture_tail(
    *,
    pane_alive: Optional[bool],
    first_hook_at: Optional[datetime],
    instance_age_seconds: Optional[float],
    grace_seconds: int = STARTUP_HOOK_GRACE_SECONDS,
    tail_age_seconds: Optional[float] = None,
    recheck_seconds: int = STARTUP_TAIL_RECHECK_SECONDS,
) -> bool:
    """Is reading this pane's scrollback worth a subprocess call?

    Description: the COST GATE, and the reason this feature is free in
        steady state. Capturing a tail is one ``tmux capture-pane`` per
        session per listing poll, which would be an unacceptable tax on
        the home screen if it ran for every row. It does not need to: a
        session that has fired a hook can never be awaiting a startup
        prompt (see the module docstring on evidence ordering), and a
        healthy session fires one within half a second of birth. So the
        capture runs only for a pane that is alive, past the grace
        window, and has produced NO hook.

        The fourth refusal is what closes it: a reading that is still
        fresh stands rather than being re-taken. A ``tail_age_seconds``
        of None means nothing is on record for this instance, which reads
        as "look now" - so the FIRST look is never delayed and the case
        the gate exists for (a session parked on its folder-trust dialog
        since birth) is detected exactly as promptly as before.

        Deliberately a separate predicate from ``resolve_startup_gate``
        rather than an early return inside it: the resolver must stay
        pure so it can be tested without tmux, and the caller must be
        able to decide whether to pay for the tail BEFORE it has one.
    Inputs:
        pane_alive: True/False/None from the caller's liveness read.
        first_hook_at: when the first hook for THIS instance landed, or
            None if none has.
        instance_age_seconds: age of the tmux instance, or None when it
            could not be dated.
        grace_seconds: override for tests.
        tail_age_seconds: seconds since the last usable tail reading for
            THIS instance, or None when there is none on record.
        recheck_seconds: how long a reading stands. Override for tests.
    Output:
        bool - True when the caller should capture a tail and pass it to
        ``resolve_startup_gate``.
    Example:
        >>> should_capture_tail(pane_alive=True, first_hook_at=None,
        ...                     instance_age_seconds=99.0)
        True
    """
    if pane_alive is not True:
        return False
    if first_hook_at is not None:
        return False
    if instance_age_seconds is None:
        return False
    if instance_age_seconds < grace_seconds:
        return False
    if tail_age_seconds is not None and tail_age_seconds < recheck_seconds:
        return False
    return True


def resolve_startup_gate(
    *,
    pane_alive: Optional[bool],
    first_hook_at: Optional[datetime],
    instance_age_seconds: Optional[float],
    tail: Optional[str],
    grace_seconds: int = STARTUP_HOOK_GRACE_SECONDS,
    remembered_match: Optional[bool] = None,
) -> str:
    """
    Description: the whole ladder, pure and side-effect free. Rung order
        is load-bearing and is pinned by tests:

          1. A hook has landed for THIS instance -> ``ready``. Tested
             FIRST so lingering prompt text in old scrollback can never
             override the fresh fact.
          2. Pane liveness did not answer -> ``unknown``.
          3. Pane measured not alive -> ``ready`` (a gone process is not
             waiting for a keypress; see the module docstring on what
             ``ready`` does and does not claim).
          4. The instance could not be dated, or is younger than the
             grace window -> ``unknown``. A session that is merely young
             has not been observed to be stuck.
          5. No tail was captured AND none is remembered for this
             instance -> ``unknown``.
          6. A marker matched -> ``awaiting_startup_prompt``.
          7. The tail was read and nothing matched -> ``ready``.

        A FRESH READING ALWAYS OUTRANKS A REMEMBERED ONE, and the
        remembered one is consulted only at rung 5, where the alternative
        is refusing. ``should_capture_tail`` throttles how often a tail
        is re-read (see ``STARTUP_TAIL_RECHECK_SECONDS``), so without
        this the row would flap between a measured verdict and
        ``unknown`` on alternating polls - a throttle that made the
        answer worse rather than cheaper.

        Rung 7 is the one asymmetry worth naming, and it matches the rule
        this codebase already applies to transcripts: not having looked
        is not evidence of absence, but having looked and found nothing
        is. Rung 5 refuses; rung 7 answers.
    Inputs:
        pane_alive: True (measured alive) / False (measured not alive) /
            None (could not determine).
        first_hook_at: timestamp of the first hook event recorded for
            this instance, or None. Presence alone is what rung 1 reads;
            the value is carried for logging and for future rungs.
        instance_age_seconds: seconds since the tmux instance was
            created, or None when it could not be dated.
        tail: captured scrollback text, or None when no capture was made.
        grace_seconds: override for tests.
        remembered_match: the verdict of the last capture taken for THIS
            instance, when the caller declined to take a fresh one; None
            when nothing is remembered. Used only where a fresh reading
            is absent.
    Output:
        str - one of ``ALL_STARTUP_GATES``.
    Example:
        >>> resolve_startup_gate(pane_alive=True, first_hook_at=None,
        ...                      instance_age_seconds=60.0,
        ...                      tail="Yes, I trust this folder")
        'awaiting_startup_prompt'
    """
    if first_hook_at is not None:
        return GATE_READY
    if pane_alive is None:
        return GATE_UNKNOWN
    if pane_alive is False:
        return GATE_READY
    if instance_age_seconds is None:
        return GATE_UNKNOWN
    if instance_age_seconds < grace_seconds:
        return GATE_UNKNOWN
    matched = detect_startup_prompt(tail)
    if matched is None:
        matched = remembered_match
    if matched is None:
        return GATE_UNKNOWN
    return GATE_AWAITING if matched else GATE_READY
