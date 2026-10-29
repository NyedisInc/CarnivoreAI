
from __future__ import annotations

import re
from typing import Iterator

PANE_ID_RE = re.compile(r"%[0-9]{1,10}")

HEX_ARGS_PER_LINE = 1024

PANE_GONE_TEXT = "can't find pane"

SESSION_GONE_TEXT = "can't find session"

SESSION_NAME_RE = re.compile(r"[A-Za-z0-9_@-]+")


def marker_option(nonce: str) -> str:
    return f"@cvseq_{nonce}"


def chunks(data: bytes) -> Iterator[bytes]:
    for start in range(0, len(data), HEX_ARGS_PER_LINE):
        yield data[start:start + HEX_ARGS_PER_LINE]


def keys_line(pane_id: str, option: str, seq: int, data: bytes) -> bytes:
    if not PANE_ID_RE.fullmatch(pane_id):
        raise ValueError(f"not a tmux pane id: {pane_id!r}")
    return (f"send-keys -H -t {pane_id} {data.hex(' ')} ; "
            f"set-option -p -t {pane_id} {option} {seq}\n").encode("ascii")


def marker_read_line(pane_id: str, option: str) -> str:
    if not PANE_ID_RE.fullmatch(pane_id):
        raise ValueError(f"not a tmux pane id: {pane_id!r}")
    return f"show-options -pqv -t {pane_id} {option}"


def active_pane_line(session: str) -> str:
    if not SESSION_NAME_RE.fullmatch(session):
        raise ValueError(f"not a session name safe for a control line: {session!r}")
    return f'display-message -p -t ={session}: "#{{pid}}|#{{pane_id}}|#{{session_name}}"'
