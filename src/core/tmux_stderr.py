"""Reading tmux's STDERR: the no-server / could-not-look decision.

Split out of src/core/tmux_listing.py, which keeps the RESULT TYPE. The
seam follows the risk rather than the file: everything here reads
UNTRUSTED TEXT and turns it into a verdict, and every historical defect
in this area was a decision made on text the caller could influence.
The type itself cannot get that wrong; these functions can.

  ANCHORING. Markers match at the START of a stderr line, never as a
  bare substring. tmux's wording always begins a line; the path never
  does. A substring test let a socket path containing the literal text
  "no server running" turn a measured "(Permission denied)" into a
  confident answer of zero sessions - which walks a caller through the
  first-run import gate and stamps a one-way latch over a user's whole
  session history.

  THE ERRNO DECIDES FIRST. A connect-error line is resolved by its
  parenthesised errno before any marker is consulted, so injected text
  cannot get in front of the authoritative signal. This also covers a
  socket name containing a NEWLINE, where the forged marker starts a
  line of its own.

THE ALLOWLIST IS ONE ERRNO, AND THE ASYMMETRY IS DELIBERATE. Only
``No such file or directory`` means an absent server; every other errno,
and every errno this module does not recognise, is could-not-look. A
future tmux rewording therefore degrades to CANNOT DETERMINE, which
retries, rather than to a confident zero, which is permanent.

Because that allowlist is English and glibc translates ``strerror``,
this module also owns the LOCALE PIN applied to the listing subprocess.
The classifier and the environment that makes it valid belong together;
separating them is how one gets changed without the other.
"""

from __future__ import annotations

import os
import re
from typing import Dict

# (No such file or directory)
# (Permission denied)
# CANNOT DETERMINE
# (No such file or directory)


_NO_SERVER_MARKERS = (
    "no server running",
    "failed to connect to server",
    "no current server",
)

# could not
_NO_SERVER_CONNECT_ERRNOS = frozenset({"no such file or directory"})

_CONNECT_ERROR_MARKER = "error connecting to"

_CONNECT_ERRNO_RE = re.compile(r"\(([^()]*)\)\s*$")


STDERR_NO_SERVER = "no_server"

STDERR_CONNECT_FAILED = "connect_failed"

# something else
# could not
STDERR_UNRECOGNISED = "unrecognised"

# could not reach
REASON_CONNECT_FAILED = "connect_failed"


def classify_tmux_stderr(stderr_text: str) -> str:
    """Read tmux's stderr as one of three outcomes, never two.

    Description: the single place the no-server / could-not-look split is
      decided. An ``error connecting to`` line is resolved by its
      PARENTHESISED ERRNO and by nothing else; only
      ``No such file or directory`` is an absent server. An errno this
      function does not recognise, or a connect line with no readable
      errno at all, is ``STDERR_UNRECOGNISED`` - never ``STDERR_NO_SERVER``.
      That asymmetry is deliberate and is the entire safety property: a
      new tmux release inventing new wording degrades to CANNOT DETERMINE,
      which retries, rather than to a confident zero, which is permanent.

      TWO RULES KEEP USER-CONTROLLED TEXT OUT OF THE VERDICT, because the
      socket path is echoed into stderr and comes from config.json.

      FIRST, matching is per LINE and ANCHORED to the line start. tmux's
      own wording always begins a line; the path never does. A bare
      substring test let a socket path containing the literal text "no
      server running" turn a measured ``(Permission denied)`` into a
      confident answer of zero sessions.
    """
    lines = [line.strip() for line in (stderr_text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return STDERR_UNRECOGNISED

    # did not answer
    connect_verdicts = [
        _classify_connect_line(line)
        for line in lines
        if line.lower().startswith(_CONNECT_ERROR_MARKER)
    ]
    if connect_verdicts:
        for verdict in connect_verdicts:
            if verdict != STDERR_NO_SERVER:
                return verdict
        return STDERR_NO_SERVER

    for line in lines:
        lowered = line.lower()
        if any(lowered.startswith(marker) for marker in _NO_SERVER_MARKERS):
            return STDERR_NO_SERVER

    return STDERR_UNRECOGNISED


def _classify_connect_line(line: str) -> str:
    match = _CONNECT_ERRNO_RE.search(line)
    if match is None:
        return STDERR_UNRECOGNISED
    errno_text = match.group(1).strip().lower()
    if errno_text in _NO_SERVER_CONNECT_ERRNOS:
        return STDERR_NO_SERVER
    return STDERR_CONNECT_FAILED


def looks_like_no_server(stderr_text: str) -> bool:
    """
    Description: the boolean face of :func:`classify_tmux_stderr`, kept
      for call sites that only need the one bit. True ONLY for
      ``STDERR_NO_SERVER``; both of the other outcomes are False, because
      from this function's caller's point of view "I could not look" and
      "I do not recognise this" have the same consequence - do not treat
      it as an answer.
    Inputs:
        stderr_text (str): decoded stderr from a failed tmux invocation.
    Output:
        bool: True when the text is a KNOWN no-server message, so the
            correct listing is a trustworthy EMPTY one. False for every
            other failure, including an empty stderr and including a
            connect error whose errno is anything but
            ``No such file or directory``.
    Example:
        >>> looks_like_no_server("no server running on /tmp/tmux-501/cloude")
        True
        >>> looks_like_no_server("error connecting to /x (Permission denied)")
        False
    """
    return classify_tmux_stderr(stderr_text) == STDERR_NO_SERVER


# CANNOT DETERMINE
LISTING_ENV_OVERRIDES = {"LC_ALL": "C"}


def listing_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.update(LISTING_ENV_OVERRIDES)
    return env
