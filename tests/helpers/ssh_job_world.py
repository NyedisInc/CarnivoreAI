
from __future__ import annotations

import hashlib
import os
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Tuple

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pack.jobs.place import PlaceView
from src.core.pack.jobs.types import CAP_JOBS
from src.core.pack.placement import rule


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


def fingerprint(repo: Path) -> Dict[str, object]:
    files = {}
    for root, _d, names in os.walk(repo / ".git"):
        for n in names:
            p = Path(root) / n
            rel = str(p.relative_to(repo))
            files[rel] = (p.stat().st_size, 0 if rel.startswith(".git/objects/") else p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return {"files": files, "refs": git(repo, "for-each-ref")}


def snap(load1: float) -> Dict[str, Any]:
    return {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": True}}


def make_project(tmp: Path) -> Tuple[Path, Path, Path, str]:
    state, jobs, root = tmp / "caller state", tmp / "caller jobs", tmp / "tra der"
    for folder in (state, jobs, root):
        folder.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    git(root, "init", "-q", "-b", "main")
    (root / "f.txt").write_text("one\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-q", "-m", "first")
    with closing(connect(db_path_for(state), create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, 'tra der', 'user', 't', 't')",
                     (str(root), str(root)))
        conn.commit()
        uid = conn.execute("SELECT uid FROM projects").fetchone()[0]
    return state, jobs, root, uid


def view_with(remote_id: str, label: str) -> PlaceView:
    me = rule.MachineInput("iid-a", "a", {**snap(9.5), "restrictions": {"may_host_agents": False}}, True, True, True, True, 0)
    other = rule.MachineInput(remote_id, label, snap(1.0), True, False, False, True, None)
    return PlaceView(me, [other], {remote_id: [CAP_JOBS]}, "iid-a", None)
