"""Parsing one ``tmux list-sessions`` row, and deciding whether it is OURS.

Split out of src/core/tmux_backend.py for two reasons. The obvious one is
that the backend is 76K and already does too much. The load-bearing one is
that BOTH decisions in this file used to be made on a caller-controlled
string, inline, with no way to unit-test them without shelling out to
tmux - so neither was ever tested against a hostile input.

THE DELIMITER PROBLEM, AND WHY THE FIELD ORDER IS THE FIX.

The old format string was::

    #{session_name}|#{session_created}|#{session_windows}

parsed with ``line.split("|")`` taking fields 0, 1 and 2. tmux forbids
only ``.`` and ``:`` in a session name; ``|`` is legal. So a session
named ``victim|1755000000|1`` prints::

    victim|1755000000|1|1787070480|1

and fields 0, 1, 2 read back as name ``victim``, created ``1755000000``,
windows ``1`` - an instance triple the CALLER chose, not one tmux
reported. Both halves of the app's identity key were forgeable, and no
attacker was required: a project named ``api|prod`` does it by accident.

THE FIX IS STRUCTURAL, NOT A BLOCKLIST. Two properties together:

  2. THE THREE LEADING FIELDS ARE TMUX-GENERATED AND STRICTLY VALIDATED.
     ``session_id`` is ``$`` followed by digits, ``session_created`` and
     ``session_windows`` are decimal integers. None of them can contain a
     ``|`` because tmux generates all three; none is caller-influenced in
     any way. Each is matched against an anchored pattern, and a row
     whose leading fields do not match is REJECTED, not guessed at.

Property 1 alone makes the name unforgeable WITHIN A ROW. Property 2 is
what makes the rejection honest: it is the only reason a malformed row
can be told apart from a valid one.

THE ROW DELIMITER IS THE SECOND HALF OF THE SAME PROBLEM, AND THIS
DOCSTRING USED TO GET IT WRONG. It previously claimed property 2 "would
catch a wrapped or truncated line, since a continuation could not begin
with ``$<digits>|``". That guarantee is FALSE and was disproven by
measurement. A continuation begins with whatever the session name says it
begins with, and a name is caller-controlled, so a name containing
``<boundary>$99|1755000000|1|cloude_work`` writes a continuation that
begins with exactly ``$<digits>|``, parses cleanly, and forges the whole
identity triple.

The gap was never the field parser. It was one layer up, in the CALLER,
which split the stdout blob with ``str.splitlines()``. Python recognises
TEN line boundaries; tmux rejects only SEVEN of them in a session name.
Measured against tmux 3.7b, tmux ACCEPTS ``U+0085`` (NEL), ``U+2028``
(LS) and ``U+2029`` (PS), and Python splits on all three - so ONE tmux
line became TWO parser rows, the second of them entirely attacker-chosen.

Two properties close it, and BOTH are applied because they are different
kinds of guarantee:

  3. THE ROW SPLIT IS THE ONE tmux ACTUALLY EMITS. :func:`split_listing_rows`
     splits on ``"\\n"`` and nothing else, because that is the only row
     terminator ``tmux list-sessions`` writes. This is the CORRECT PARSE:
     it makes the injected characters ordinary content inside a single
     row, where the bounded split of property 1 already renders them
     harmless. Every enumeration site in the backend uses it.

BE PRECISE ABOUT WHAT PROPERTY 4 DOES NOT DO, because the previous
version of this docstring was wrong in exactly this way and a wrong
guarantee is worse than none. It does NOT protect a caller that reaches
for ``splitlines()`` anyway: that splitter CONSUMES the boundary
character, so the forged row arrives here with a perfectly clean name
and nothing in this function can tell it from a real one. The check is
only reachable when the row was split correctly to begin with.

The guarantee that a caller cannot regress is therefore NOT a runtime
check and cannot be one. It is enforced structurally, by a test that
walks the AST of the backend and fails if any tmux listing output is
ever handed to ``splitlines()``. See
tests/test_tmux_row_delimiter.py::test_no_listing_site_uses_splitlines.
That test lives at the layer that actually enforces the property - the
call site - which is the lesson from the previous round, where an AST
proof constrained the field parser while the hole sat one layer up.

WHY ``session_id`` IS A DISCRIMINATOR AND NOT THE IDENTITY. tmux's
``#{session_id}`` (``$0``, ``$1``, ...) is unique per SERVER LIFETIME and
is never reused while that server lives, which makes it strictly better
than a one-second timestamp at telling two sessions apart RIGHT NOW. It
is strictly WORSE as a durable key, because the counter restarts at
``$0`` when the server does - so ``$3`` today and ``$3`` after a reboot
are different sessions with the same id. The stored identity therefore
stays the instance triple (socket, name, created epoch), which survives a
restart, and ``session_id`` is carried alongside it as a discriminator
that can only ever REFUSE a match, never widen one. See
src/core/session_identity.py for where that refusal is enforced.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core.product_identity import is_owned_session_name
from src.core.tmux_control.names import is_control_input_session

logger = structlog.get_logger()

LISTING_FORMAT = "#{session_id}|#{session_created}|#{session_windows}|#{session_name}"

CONTROL_SESSION_NAME = "_carnivore_ctl"


def is_plumbing_session(name: str) -> bool:
    return name == CONTROL_SESSION_NAME or is_control_input_session(name)

FIELD_SEPARATOR = "|"

_MAXSPLIT = 3

_SESSION_ID_RE = re.compile(r"^\$\d+$")

_INTEGER_RE = re.compile(r"^\d+$")

ROW_SEPARATOR = "\n"

LINE_BOUNDARY_CHARS: Tuple[str, ...] = (
    "\n",
    "\r",
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    " ",
    " ",
)


def split_listing_rows(stdout_text: str) -> List[str]:
    rows: List[str] = []
    for raw in (stdout_text or "").split(ROW_SEPARATOR):
        row = raw.rstrip("\r")
        if row.strip():
            rows.append(row)
    return rows


def name_has_line_boundary(name: str) -> bool:
    return any(char in name for char in LINE_BOUNDARY_CHARS)


def parse_listing_row(line: str) -> Optional[Dict[str, Any]]:
    stripped = (line or "").rstrip("\r\n")
    if not stripped.strip():
        return None

    parts = stripped.split(FIELD_SEPARATOR, _MAXSPLIT)
    if len(parts) != _MAXSPLIT + 1:
        return None

    session_id, created_raw, windows_raw, name = parts

    if not _SESSION_ID_RE.match(session_id):
        return None
    if not _INTEGER_RE.match(created_raw):
        return None
    if not _INTEGER_RE.match(windows_raw):
        return None
    if not name:
        return None
    if name_has_line_boundary(name):
        return None

    return {
        "session_id": session_id,
        "created_at_epoch": int(created_raw),
        "window_count": int(windows_raw),
        "name": name,
    }


def resolve_ownership(
    name: str,
    created_at_epoch: int,
    owned_instances: Optional[Set[Tuple[str, int]]],
    owned_names: Optional[Set[str]],
    prefix: str = "",
) -> bool:
    if owned_instances is not None:
        if (name, created_at_epoch) in owned_instances:
            return True
        if any(
            owned_name == name and owned_epoch is not None
            for owned_name, owned_epoch in owned_instances
        ):
            return False

    if owned_names is not None:
        return name in owned_names

    if owned_instances is not None:
        return False

    return bool(prefix) and is_owned_session_name(name)


SCREEN_STAMP_FORMAT = (
    "|#{window_activity}|#{pane_width}|#{pane_height}|#{window_active}|#{pane_active}"
)
SCREEN_STAMP_FIELDS = 5


def _stamp_int(raw: Any) -> Optional[int]:
    text = str(raw).strip()
    return int(text) if text.isdigit() else None


def parse_screen_stamp(fields: Any) -> Dict[str, Any]:
    values = list(fields)
    if len(values) != SCREEN_STAMP_FIELDS:
        return {"window_activity": None, "pane_width": None, "pane_height": None,
                "pane_is_current": None}
    activity, width, height, window_active, pane_active = (_stamp_int(v) for v in values)
    current = None
    if window_active is not None and pane_active is not None:
        current = window_active == 1 and pane_active == 1
    return {"window_activity": activity, "pane_width": width, "pane_height": height,
            "pane_is_current": current}
