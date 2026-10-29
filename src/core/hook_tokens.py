"""Durable per-session hook tokens, so a restart does not silence hooks.

Restart the server and those two facts collide. The agent keeps posting
perfectly well-formed hooks, forever, to a server that has forgotten the
token, and every one is rejected:

    POST /api/v1/hooks/claude-event  ->  {"detail":"invalid token"}  403

Nothing about that is visible from the pane. And because everything
downstream of hooks dies at once - activity status, toasts, session
lineage - and the fallback tier reports a CONSTANT ``idle`` under this
app's launch path, a session whose hooks are dead is indistinguishable
from a healthy one sitting at a prompt.

WHY PERSISTING IS THE RIGHT FIX AND NOT A WEAKENING. The original design
kept the token in memory on purpose, so a compromised process could not
learn one. That property is mostly notional here: the token is ALREADY
readable by the same user, out of the pane's own environment
(``tmux show-environment``), which is where the agent reads it from. A
0600 file in the state dir adds no reader who could not already run that
command. What the memory-only design actually bought was "the token stops
being valid when the session ends", and that is preserved exactly - the
entry is dropped on destroy, and any entry whose session is gone is
garbage-collected on load.

The loopback check is untouched and remains the layer that matters
against anything off-box.

THREE OUTCOMES, because a token store that fails quietly recreates the
very bug it fixes. Load and save both report whether they worked; a
caller that cannot persist is told so and can degrade to memory-only
WITH the reason, rather than believing it is durable.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

TOKENS_FILENAME: str = "hook_tokens.json"

_FILE_MODE = 0o600

_SCHEMA = 2
_SCHEMA_READABLE = (1, 2)

LOAD_OK = "ok"
LOAD_ABSENT = "absent"
LOAD_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class LoadResult:

    tokens: Dict[str, str]
    status: str
    detail: Optional[str] = None
    tmux_names: Dict[str, str] = field(default_factory=dict)

    @property
    def durable(self) -> bool:
        return self.status in (LOAD_OK, LOAD_ABSENT)


def tokens_path(state_dir: Path) -> Path:
    return Path(state_dir) / TOKENS_FILENAME


def load_tokens(
    state_dir: Path, live_session_ids: Optional[Iterable[str]] = None
) -> LoadResult:
    """Read the stored tokens, dropping any whose session is gone.

    Description: ``live_session_ids``, when supplied, garbage-collects the
      file. A token whose session no longer exists can never be presented
      by anything, so keeping it is pure credential accumulation - the
      file would grow for the life of the install. Passing None keeps
      everything, which is correct before the session list is known.

      A file that cannot be parsed yields an EMPTY store with status
      ``unreadable`` rather than raising. That is a deliberate choice and
      the reason ``status`` exists: the caller must be able to tell "no
      tokens were stored" from "I could not read what was stored", and
      only the second one warrants a warning to the user.
    Inputs: state_dir (Path). live_session_ids (iterable[str] | None) -
      session ids currently known; entries outside it are dropped.
    Output: LoadResult.
    Example: load_tokens(Path('/tmp')).status -> 'absent'
    """
    path = tokens_path(state_dir)
    if not path.exists():
        return LoadResult(tokens={}, status=LOAD_ABSENT)
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("hook_tokens_unreadable", error=str(exc))
        return LoadResult(tokens={}, status=LOAD_UNREADABLE, detail=str(exc))

    if not isinstance(raw, dict) or raw.get("schema") not in _SCHEMA_READABLE:
        return LoadResult(
            tokens={},
            status=LOAD_UNREADABLE,
            detail=f"unrecognised schema (want {_SCHEMA})",
        )
    stored = raw.get("tokens")
    if not isinstance(stored, dict):
        return LoadResult(
            tokens={}, status=LOAD_UNREADABLE, detail="tokens is not an object"
        )

    tokens: Dict[str, str] = {}
    names: Dict[str, str] = {}
    for k, v in stored.items():
        if not isinstance(k, str) or not k:
            continue
        if isinstance(v, str) and v:
            tokens[k] = v
        elif isinstance(v, dict):
            tok = v.get("token")
            nm = v.get("tmux_name")
            if isinstance(tok, str) and tok:
                tokens[k] = tok
            if isinstance(nm, str) and nm:
                names[k] = nm
    if live_session_ids is not None:
        live = set(live_session_ids)
        tokens = {k: v for k, v in tokens.items() if k in live}
        names = {k: v for k, v in names.items() if k in live}
    return LoadResult(tokens=tokens, status=LOAD_OK, tmux_names=names)


def save_tokens(
    state_dir: Path,
    tokens: Dict[str, str],
    tmux_names: Optional[Dict[str, str]] = None,
) -> Tuple[bool, Optional[str]]:
    path = tokens_path(state_dir)
    names = tmux_names or {}
    entries = {
        sid: {"token": tok, "tmux_name": names.get(sid)}
        for sid, tok in tokens.items()
    }
    payload = json.dumps({"schema": _SCHEMA, "tokens": entries}, indent=2)
    tmp_path = None
    try:
        if not path.parent.is_dir():
            return (False, f"state dir does not exist: {path.parent}")
        fd, tmp = tempfile.mkstemp(
            prefix=".hook_tokens.", suffix=".tmp", dir=str(path.parent)
        )
        tmp_path = Path(tmp)
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, _FILE_MODE)
        os.replace(tmp_path, path)
        return (True, None)
    except OSError as exc:
        logger.warning("hook_tokens_save_failed", error=str(exc))
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return (False, str(exc))
