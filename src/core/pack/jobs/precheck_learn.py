
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.core.pack.jobs import load_store
from src.core.pack.jobs.precheck_hook import EXEMPT, HEAVY_ARGS, HEAVY_PROGRAMS, _programs

HEAVY_SECONDS = 60.0
MIN_RUNS_FOR_WALL = 2
MIN_HEAVY_CPU_S = 15.0
MIN_HEAVY_RAM_GB = 1.5
SINGLE_RUN_CPU_S = 60.0
LAST_RUNS = 5
MAX_ROWS = 2000
MAX_AGE_S = 30 * 86400.0
LEARN_AGE_S = 24 * 3600.0
MAX_GIVEWAYS = 500
_SAFE_WORD = re.compile(r"^[A-Za-z0-9_.@:/-]{1,60}$")
_INTERPRETERS = frozenset({"python", "python3", "python3.12", "python3.11", "node", "bun", "deno", "ruby", "perl", "bash", "sh", "zsh"})
_INLINE_FLAGS = frozenset({"-c", "-e", "--eval"})


@dataclass(frozen=True)
class ShapeProfile:

    shape: str
    runs: int
    p50_wall_s: float
    p75_cpu_cores: Optional[float]
    p75_ram_gb: Optional[float]


def _is_generic_inline(name: str, args: List[str]) -> bool:
    if name not in _INTERPRETERS:
        return False
    if not args:
        return True
    first = args[0]
    if first == "-" or first in _INLINE_FLAGS:
        return True
    if first == "-m" and len(args) >= 2:
        return False
    return False


def _segment_priority(name: str, args: List[str]) -> int:
    if name in HEAVY_PROGRAMS or (name in HEAVY_ARGS and HEAVY_ARGS[name] & set(args)):
        return 40
    if name in ("node", "bun") and any("build" in a for a in args):
        return 40
    if name in _INTERPRETERS and args and args[0] == "-m" and len(args) >= 2 and args[1] in HEAVY_PROGRAMS:
        return 40
    if name.endswith((".sh", ".py", ".mjs", ".js", ".ts")) or "/" in name:
        return 30
    if name in _INTERPRETERS:
        return 20
    return 10


def _format_shape(name: str, args: List[str]) -> str:
    words = [name]
    positional = [a for a in args if not a.startswith("-")]
    if name in _INTERPRETERS and args and args[0] == "-m" and len(args) >= 2:
        mod = args[1]
        words.append(re.sub(r"\d+", "N", mod) if _SAFE_WORD.match(mod) else "<arg>")
    elif positional:
        first = positional[0]
        words.append("<path>" if first.startswith(("/", "~")) else (re.sub(r"\d+", "N", first) if _SAFE_WORD.match(first) else "<arg>"))
        if name in ("npm", "pnpm", "yarn", "bun") and first == "run" and len(positional) > 1:
            words.append(re.sub(r"\d+", "N", positional[1]) if _SAFE_WORD.match(positional[1]) else "<arg>")
    words += sorted({a.split("=", 1)[0][:30] for a in args if a.startswith("-") and _SAFE_WORD.match(a.split("=", 1)[0].lstrip("-") or "x")})[:4]
    return " ".join(words)[:120]


def shape(command: str) -> Optional[str]:
    try:
        parts = _programs(command)
    except ValueError:
        return None
    candidates: List[Tuple[int, int, str, List[str]]] = []
    for idx, (name, args) in enumerate(parts):
        if name == "cd" or name in EXEMPT:
            continue
        if _is_generic_inline(name, args):
            continue
        candidates.append((_segment_priority(name, args), -idx, name, args))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, _, best_name, best_args = candidates[0]
    return _format_shape(best_name, best_args)


def _percentile(values: List[float], frac: float) -> float:
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int((len(s) - 1) * frac)))
    return s[idx]


def record(store, project_uid: str, command_shape: str, seconds: float, now: Optional[float] = None, *,
           cpu_s: Optional[float] = None, peak_ram_gb: Optional[float] = None, source: str = "local") -> None:
    if not command_shape:
        return
    at = time.time() if now is None else now
    with store._tx() as conn:  # noqa: SLF001
        conn.execute(
            "INSERT INTO command_runs (project_uid, shape, seconds, cpu_s, peak_ram_gb, source, at) VALUES (?,?,?,?,?,?,?)",
            (project_uid, command_shape, float(seconds),
             None if cpu_s is None else float(cpu_s),
             None if peak_ram_gb is None else float(peak_ram_gb),
             str(source or "local")[:16], at),
        )
        conn.execute("DELETE FROM command_runs WHERE project_uid=? AND shape=? AND id NOT IN "
                     "(SELECT id FROM command_runs WHERE project_uid=? AND shape=? ORDER BY id DESC LIMIT ?)",
                     (project_uid, command_shape, project_uid, command_shape, LAST_RUNS))
        conn.execute("DELETE FROM command_runs WHERE at<?", (at - MAX_AGE_S,))
        conn.execute("DELETE FROM command_runs WHERE id NOT IN (SELECT id FROM command_runs ORDER BY id DESC LIMIT ?)", (MAX_ROWS,))


def learned_heavy(store, project_uid: str, command_shape: Optional[str], now: Optional[float] = None) -> bool:
    if not command_shape:
        return False
    override = load_store.shape_override_get(store, project_uid, command_shape)
    if override == "local_only":
        return False
    if override == "always_offload":
        return True
    cutoff = (time.time() if now is None else now) - LEARN_AGE_S
    with store._borrow() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT seconds, cpu_s, peak_ram_gb FROM command_runs WHERE project_uid=? AND shape=? AND at>=? ORDER BY id DESC LIMIT ?",
            (project_uid, command_shape, cutoff, LAST_RUNS),
        ).fetchall()
    if not rows:
        return False
    walls = [float(r["seconds"]) for r in rows]
    cpus = [float(r["cpu_s"]) for r in rows if r["cpu_s"] is not None]
    rams = [float(r["peak_ram_gb"]) for r in rows if r["peak_ram_gb"] is not None]
    if any(c >= SINGLE_RUN_CPU_S for c in cpus):
        return True
    if len(walls) < MIN_RUNS_FOR_WALL:
        return False
    if _percentile(walls, 0.5) < HEAVY_SECONDS:
        return False
    if cpus or rams:
        med_cpu = _percentile(cpus, 0.5) if cpus else 0.0
        med_ram = _percentile(rams, 0.5) if rams else 0.0
        if med_cpu < MIN_HEAVY_CPU_S and med_ram < MIN_HEAVY_RAM_GB:
            return False
    return True


def profile(store, project_uid: str, command_shape: Optional[str], now: Optional[float] = None) -> Optional[ShapeProfile]:
    if not command_shape:
        return None
    cutoff = (time.time() if now is None else now) - MAX_AGE_S
    with store._borrow() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT seconds, cpu_s, peak_ram_gb FROM command_runs WHERE project_uid=? AND shape=? AND at>=? ORDER BY id DESC LIMIT ?",
            (project_uid, command_shape, cutoff, LAST_RUNS),
        ).fetchall()
    if not rows:
        return None
    walls = [max(0.1, float(r["seconds"])) for r in rows]
    cores = [min(64.0, max(0.25, float(r["cpu_s"]) / max(0.5, float(r["seconds"]))))
             for r in rows if r["cpu_s"] is not None and float(r["seconds"]) > 0]
    rams = [min(64.0, max(0.25, float(r["peak_ram_gb"]))) for r in rows if r["peak_ram_gb"] is not None]
    return ShapeProfile(
        shape=command_shape,
        runs=len(rows),
        p50_wall_s=round(_percentile(walls, 0.5), 1),
        p75_cpu_cores=round(_percentile(cores, 0.75), 2) if len(cores) >= 2 else None,
        p75_ram_gb=round(_percentile(rams, 0.75), 2) if len(rams) >= 2 else None,
    )


def record_giveway(store, project_uid: str, command_shape: str, now: Optional[float] = None) -> None:
    at = time.time() if now is None else now
    with store._tx() as conn:  # noqa: SLF001
        conn.execute("INSERT INTO guard_giveways (at, project_uid, shape) VALUES (?,?,?)", (at, project_uid, command_shape[:120]))
        conn.execute("DELETE FROM guard_giveways WHERE at<?", (at - MAX_AGE_S,))
        conn.execute("DELETE FROM guard_giveways WHERE id NOT IN (SELECT id FROM guard_giveways ORDER BY id DESC LIMIT ?)", (MAX_GIVEWAYS,))


def giveways_since(store, cutoff: float) -> int:
    with store._borrow() as conn:  # noqa: SLF001
        return int(conn.execute("SELECT COUNT(*) FROM guard_giveways WHERE at>=?", (cutoff,)).fetchone()[0])
