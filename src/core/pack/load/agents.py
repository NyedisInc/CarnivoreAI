
from __future__ import annotations

import json
import sqlite3
import subprocess
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.pack.load import process_tree
from src.core.tmux_control.reader import control_read
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix

MAX_ROWS = 200
MAX_BYTES = 7 * 1024
_SQL = ("SELECT s.id, s.session_uuid, s.tmux_socket, s.tmux_name, a.id, a.display_name FROM sessions s "
        "LEFT JOIN swarm_agents a ON a.session_row_id = s.id "
        "WHERE s.host_key = ? AND s.lifecycle = 'running' AND s.tmux_name IS NOT NULL")


def _run(argv: List[str]) -> Optional[str]:
    if len(argv) > 3 and argv[1] == "-L":
        answered = control_read(argv[2], argv[3:])
        if answered is not None:
            return answered.decode("utf-8", errors="replace")
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def pane_pids(sockets: List[str], *, run: Callable[[List[str]], Optional[str]] = _run) -> Dict[tuple, List[int]]:
    out: Dict[tuple, List[int]] = {}
    for socket in sockets:
        try:
            argv = tmux_argv_prefix(socket)
        except TmuxVersionSkewError:
            continue
        text = run(argv + ["list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}"])
        for line in (text or "").splitlines():
            name, _, pid = line.rpartition("\t")
            if name and pid.isdigit():
                out.setdefault((socket, name), []).append(int(pid))
    return out


def summarise(rows: List[Dict[str, Any]], procs: List[process_tree.Proc]) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    counted: set = set()
    by_pid = {p.pid: p for p in procs}
    for row in rows:
        tree: set = set()
        for members in process_tree.trees(procs, row["pids"]).values():
            tree |= members
        if not tree:
            continue
        fresh = tree - counted
        counted |= tree
        out.append({"session_id": row["session_id"], "session_uuid": row["session_uuid"], "agent_id": row["agent_id"],
                    "name": row["name"], "cpu_pct": round(sum(by_pid[p].cpu for p in tree), 1),
                    "rss_mb": round(sum(by_pid[p].rss_kb for p in tree) / 1024.0, 1), "_fresh": fresh})
    out.sort(key=lambda r: -r["cpu_pct"])
    carn_cpu = sum(by_pid[p].cpu for p in counted)
    carn_rss = sum(by_pid[p].rss_kb for p in counted)
    kept: List[Dict[str, Any]] = []
    size = 0
    for r in out:
        r.pop("_fresh")
        size += len(json.dumps(r, separators=(",", ":"))) + 1
        if len(kept) >= MAX_ROWS or size > MAX_BYTES:
            break
        kept.append(r)
    return {"rows": kept, "truncated": len(out) - len(kept), "count": len(out),
            "carnivore": {"cpu_pct": round(carn_cpu, 1), "rss_mb": round(carn_rss / 1024.0, 1), "agents": len(out)},
            "machine": {"cpu_pct": round(sum(p.cpu for p in procs), 1), "rss_mb": round(sum(p.rss_kb for p in procs) / 1024.0, 1)}}


def collect(open_db: Callable[[], sqlite3.Connection], *, ps: Callable[[], Optional[List[process_tree.Proc]]] = process_tree.read,
            run: Callable[[List[str]], Optional[str]] = _run) -> Optional[Dict[str, Any]]:
    with closing(open_db()) as conn:
        found = conn.execute(_SQL, (LOCAL_HOST_KEY,)).fetchall()
    procs = ps()
    if procs is None:
        return None
    panes = pane_pids(sorted({str(r[2]) for r in found}), run=run)
    rows = [{"session_id": r[0], "session_uuid": r[1], "agent_id": r[4], "name": r[5] or r[3],
             "pids": panes.get((str(r[2]), str(r[3])), [])} for r in found]
    return summarise([r for r in rows if r["pids"]], procs)
