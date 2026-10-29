
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
