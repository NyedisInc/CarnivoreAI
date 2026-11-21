
from __future__ import annotations

import re
import time
from typing import Optional

from src.core.pack.jobs.precheck_hook import EXEMPT, _programs

HEAVY_SECONDS = 60.0
LAST_RUNS = 5
MAX_ROWS = 2000
MAX_AGE_S = 30 * 86400.0
_SAFE_WORD = re.compile(r"^[A-Za-z0-9_.@:/-]{1,60}$")


def shape(command: str) -> Optional[str]:
    try:
        parts = _programs(command)
    except ValueError:
        return None
    for name, args in parts:
        if name == "cd" or name in EXEMPT:
            continue
        words = [name]
        positional = [a for a in args if not a.startswith("-")]
        if positional:
            first = positional[0]
            words.append("<path>" if first.startswith(("/", "~")) else (re.sub(r"\d+", "N", first) if _SAFE_WORD.match(first) else "<arg>"))
            if name in ("npm", "pnpm", "yarn", "bun") and first == "run" and len(positional) > 1:
                words.append(re.sub(r"\d+", "N", positional[1]) if _SAFE_WORD.match(positional[1]) else "<arg>")
        words += sorted({a.split("=", 1)[0][:30] for a in args if a.startswith("-") and _SAFE_WORD.match(a.split("=", 1)[0].lstrip("-") or "x")})[:4]
        return " ".join(words)[:120]
    return None


def record(store, project_uid: str, command_shape: str, seconds: float, now: Optional[float] = None) -> None:
    at = time.time() if now is None else now
    with store._tx() as conn:  # noqa: SLF001
        conn.execute("INSERT INTO command_runs (project_uid, shape, seconds, at) VALUES (?,?,?,?)", (project_uid, command_shape, float(seconds), at))
        conn.execute("DELETE FROM command_runs WHERE project_uid=? AND shape=? AND id NOT IN "
                     "(SELECT id FROM command_runs WHERE project_uid=? AND shape=? ORDER BY id DESC LIMIT ?)",
                     (project_uid, command_shape, project_uid, command_shape, LAST_RUNS))
        conn.execute("DELETE FROM command_runs WHERE at<?", (at - MAX_AGE_S,))
        conn.execute("DELETE FROM command_runs WHERE id NOT IN (SELECT id FROM command_runs ORDER BY id DESC LIMIT ?)", (MAX_ROWS,))


def learned_heavy(store, project_uid: str, command_shape: Optional[str]) -> bool:
    if not command_shape:
        return False
    with store._borrow() as conn:  # noqa: SLF001
        row = conn.execute("SELECT MAX(seconds) FROM (SELECT seconds FROM command_runs WHERE project_uid=? AND shape=? ORDER BY id DESC LIMIT ?)",
                           (project_uid, command_shape, LAST_RUNS)).fetchone()
    return bool(row and row[0] is not None and row[0] >= HEAVY_SECONDS)
