
from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.project_move.plan import PaneListing
from src.core.project_pack.env import PackEnv
from src.core.project_pack.jobs import Progress
from src.core.project_writes import create_project

NO_PANES = PaneListing(ok=True)
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=GIT_ENV, check=True)
    return done.stdout


def make_repo(path: Path, remote: Path | None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    (path / "README").write_text("hello\n")
    git(path, "add", "README")
    git(path, "commit", "-q", "-m", "first")
    if remote is not None:
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=GIT_ENV)
        git(path, "remote", "add", "origin", str(remote))
        git(path, "push", "-q", "-u", "origin", "main")


def fake_trash_factory(trash_dir: Path):
    def trash(paths: Sequence[str]) -> None:
        for p in paths:
            dest = trash_dir / f"{len(list(trash_dir.iterdir()))}-{os.path.basename(p)}"
            shutil.move(p, dest)
    return trash


def build_world(tmp_path: Path, monkeypatch: Any) -> SimpleNamespace:
    from src.config import settings

    base = tmp_path.resolve()
    state = base / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(base / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    home = base / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    root = base / "dev" / "oldsite"
    (root / "src" / "deep").mkdir(parents=True)
    (root / "src" / "a.py").write_text("print('a')\n" * 200)
    (root / "src" / "deep" / "b.bin").write_bytes(os.urandom(5000))
    (root / "empty").mkdir()
    (root / "src" / "link").symlink_to("a.py")
    (root / "src" / "tool.sh").write_text("#!/bin/sh\n")
    os.chmod(root / "src" / "tool.sh", 0o750)
    make_repo(root, base / "remote.git")
    kid = root / "kid"
    kid.mkdir()
    (kid / "k.txt").write_text("kid\n")
    trash_dir = base / "trash"
    trash_dir.mkdir()
    db = db_path_for(state)
    with closing(connect(db)) as conn:
        main = create_project(conn, name="oldsite", path=str(root))
        child = create_project(conn, name="kid", path=str(kid))
        for pid in (main["id"], child["id"]):
            conn.execute("UPDATE projects SET archived_at = '2026-01-01T00:00:00Z' WHERE id = ?", (pid,))
    env = PackEnv(trash=fake_trash_factory(trash_dir), level=3, margin=0, transcript_roots=lambda: (base / "claude",),
                  state_dir=state)
    w = SimpleNamespace(base=base, state=state, db=db, root=root, kid=kid, trash_dir=trash_dir, env=env, home=home,
                        ids={"oldsite": main["id"], "kid": child["id"]})
    monkeypatch.setattr("src.api.project_pack_routes.make_env", lambda: env)
    monkeypatch.setattr("src.api.project_pack_routes.read_live_panes", lambda: NO_PANES)
    return w


def conn_of(w: SimpleNamespace):
    return connect(w.db, create=False)


def project_row(w: SimpleNamespace, name: str = "oldsite") -> dict:
    with closing(conn_of(w)) as conn:
        return dict(conn.execute("SELECT * FROM projects WHERE id = ?", (w.ids[name],)).fetchone())


def pack_plan(w: SimpleNamespace, panes: PaneListing = NO_PANES, **kwargs: Any):
    from src.core.project_pack.plan_pack import build_pack_plan

    with closing(conn_of(w)) as conn:
        return build_pack_plan(conn, project_row(w), panes=panes, env=w.env, **kwargs)


def unpack_plan(w: SimpleNamespace):
    from src.core.project_pack.plan_unpack import build_unpack_plan

    with closing(conn_of(w)) as conn:
        return build_unpack_plan(conn, project_row(w), env=w.env)


def run_pack_now(w: SimpleNamespace, plan=None) -> None:
    from src.core.project_pack.pack import run_pack

    run_pack(lambda: conn_of(w), plan or pack_plan(w), w.env, Progress(w.ids["oldsite"]), "t1")


def run_unpack_now(w: SimpleNamespace, plan=None) -> None:
    from src.core.project_pack.unpack import run_unpack

    run_unpack(lambda: conn_of(w), plan or unpack_plan(w), w.env, Progress(w.ids["oldsite"]), "t2")


def storage_row(w: SimpleNamespace, name: str = "oldsite") -> dict:
    with closing(conn_of(w)) as conn:
        row = conn.execute("SELECT * FROM project_storage WHERE project_id = ?", (w.ids[name],)).fetchone()
        return dict(row) if row else {}


def tree_digest(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = ("l", os.readlink(p), None)
        elif p.is_dir():
            out[rel] = ("d", None, p.stat().st_mode & 0o7777)
        else:
            out[rel] = ("f", p.read_bytes(), p.stat().st_mode & 0o7777)
    return out
