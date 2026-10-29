
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import pack_migrate_env as env_mod
from src.config import settings
from src.core import claude_folder_trust
from src.core.approvals.carried_trust import YES_LABEL
from tests.python.approvals.auto_helpers import make_engine
from src.core.approvals.extract import extract_dialog
from src.core.pack.identity import replicas
from src.core.pack.migrate import apply, plan
from src.core.federation import peer_links
from src.core.pack.trust_carry import store, wire
from tests.python.pack.test_migrate_two_machines import seed, world  # noqa: F401

SCREENS = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"
CODEX_TRUST = "> You are in /tmp/x\n\n  Do you trust the contents of this directory? Working with untrusted contents\n  comes with higher risk of prompt injection.\n\n› 1. Yes, continue\n  2. No, quit\n\n  Press enter to continue\n"


@pytest.fixture(autouse=True)
def _peer_reads_trust(monkeypatch):
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(capabilities=lambda iid: [wire.CAP_TRUST_CARRY]))


def _screen(folder: str, warning: str = "", no_row: str = "No, exit", shown: str = "") -> str:
    text = (SCREENS / "trust_dialog.txt").read_text()
    path_block = re.search(r"Accessing workspace:\n\n(.*?)\n\n Quick", text, re.S).group(1)
    text = text.replace(path_block, " " + (shown or folder))
    if warning:
        text = text.replace(" Security guide", f" {warning}\n\n Security guide")
    return text.replace("No, exit", no_row)


def _migrate(world, trusted: bool):
    a, b, current, link = world
    uid = seed(a)
    with closing(a.conn()) as conn:
        project = dict(conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone())
    env = env_mod.source_env()
    made = asyncio.run(plan.plan_project(env, project, "iid-b", apply.guarded(link(a, b))))
    asyncio.run(apply.apply_project(env, made, link(a, b)))
    return uid, b.project(uid)["root"]


def _answers(conn_of, folder, screen=None, family="claude", gate="awaiting_startup_prompt", session="ses_1", info_family="claude") -> list:
    sent = []

    async def answer(sid, fingerprint, label):
        sent.append((sid, label))

    async def info(_sid):
        return SimpleNamespace(session=SimpleNamespace(working_dir=folder), agent_family=info_family, startup_gate=gate)

    def lookup(path):
        with closing(conn_of()) as conn:
            return store.carried_op(conn, path)

    dialog = extract_dialog(screen if screen is not None else _screen(folder), family)
    obs = SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=dialog, identity=("s", "n", 1, 9)))

    async def run():
        ack = make_engine(answer=answer, info=info, lookup=lookup)
        task = ack.on_observation(SimpleNamespace(session_id=session), obs)
        if task is not None:
            await task

    asyncio.run(run())
    return sent


def _git(path: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env=env, check=True)


def test_carried_trust_decides_yes_only_for_the_exact_folder_the_receiver_made(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: True)
    uid, root = _migrate(world, True)
    real = os.path.realpath(root)
    assert _answers(b.conn, real) == [("ses_1", YES_LABEL)]

    for other in (os.path.dirname(real), os.path.join(real, "sub"), real + "2", str(tmp_path / "elsewhere")):
        os.makedirs(other, exist_ok=True)
        assert _answers(b.conn, other) == [], other
    assert _answers(b.conn, real, screen=(SCREENS / "trust_dialog_permissions.txt").read_text()) == []
    assert _answers(b.conn, real, screen=CODEX_TRUST, family="codex") == []
    assert _answers(b.conn, real, info_family="codex") == []
    assert _answers(b.conn, real, gate="ready") == []
    assert _answers(b.conn, real, gate="unknown") == []
    assert _answers(b.conn, real, gate=None) == []
    assert _answers(b.conn, real, session="adopted:x") == [] and _answers(b.conn, real, session="remote:peer-x") == []
    moved = Path(real + ".was")
    os.rename(real, moved)
    os.symlink(tmp_path, real)
    assert _answers(b.conn, real) == []
    os.unlink(real)
    os.rename(moved, real)
    assert _answers(b.conn, real) == [("ses_1", YES_LABEL)]
    status, answer = asyncio.run(link(a, b)("POST", "/federation/pack/migrate/back", json={"op_id": "back-op-0001", "project_uid": uid}))
    assert status == 200, answer
    assert _answers(b.conn, real) == []


def test_any_warning_line_or_another_shown_folder_is_refused(world, monkeypatch) -> None:
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: True)
    uid, root = _migrate(world, True)
    real = os.path.realpath(root)
    assert _answers(b.conn, real) == [("ses_1", YES_LABEL)]
    for warning in (" ⚠ This folder configures hooks that run commands: .claude/settings.json",
                    " ⚠ This folder sets environment variables for every session",
                    " ⚠ This folder runs credential helper commands",
                    " ⚠ This folder runs commands to mint HTTP headers",
                    " ⚠ This folder is part of the repository at /Users/owner/code/enclosing",
                    " an unknown line a newer claude adds"):
        assert _answers(b.conn, real, screen=_screen(real, warning=warning)) == [], warning
    assert _answers(b.conn, real, screen=_screen(real, no_row="No, continue without these permissions")) == []
    assert _answers(b.conn, real, screen=_screen(real, shown="/somewhere/else")) == []
    assert _answers(b.conn, real, screen=_screen(real, shown=real + "/sub")) == []


def test_untrusted_source_and_preexisting_folders_get_no_row(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: False)
    uid, root = _migrate(world, False)
    assert _answers(b.conn, os.path.realpath(root)) == []


def test_migrate_into_a_preexisting_empty_folder_carries_nothing(world, monkeypatch) -> None:
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: True)
    (b.projects / "trader").mkdir()
    uid, root = _migrate(world, True)
    assert os.path.realpath(root) == os.path.realpath(b.projects / "trader")
    assert _answers(b.conn, os.path.realpath(root)) == []


def test_replica_carries_only_a_new_folder_inside_the_projects_folder_and_outside_any_repo(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: b.projects, raising=True)
    repo = tmp_path / "ownerrepo"
    repo.mkdir()
    _git(repo, "init", "-q")
    inside_projects_repo = b.projects / "gitparent"
    inside_projects_repo.mkdir()
    _git(inside_projects_repo, "init", "-q")
    pre = b.projects / "existing"
    pre.mkdir()
    cases = {
        "fresh": (b.projects / "fresh", True),
        "pre": (pre, False),
        "outside": (tmp_path / "outside-projects", False),
        "inrepo": (repo / "newsub", False),
        "nested": (inside_projects_repo / "child", False),
        "plain": (b.projects / "plain", False),
    }
    with closing(b.conn()) as conn:
        for n, (name, (root, carried)) in enumerate(cases.items()):
            replicas.accept_replica(conn, home_install_id="iid-a", project_uid=f"{n}0f1" * 8, name=name, root=str(root), source_trusted=name != "plain")
            assert (store.carried_op(conn, os.path.realpath(root)) is not None) is carried, name


def test_a_worktree_inherits_only_from_a_carried_folder_that_is_its_exact_main_repo(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: b.projects, raising=True)
    with closing(b.conn()) as conn:
        replicas.accept_replica(conn, home_install_id="iid-a", project_uid="c0f1" * 8, name="carried", root=str(b.projects / "carried"), source_trusted=True)
        main = b.projects / "carried"
        _git(main, "init", "-q", "-b", "main")
        (main / "f").write_text("x")
        _git(main, "add", "f")
        _git(main, "commit", "-q", "-m", "c")
        enclosing = tmp_path / "enclosing"
        enclosing.mkdir()
        _git(enclosing, "init", "-q", "-b", "main")
        (enclosing / "f").write_text("x")
        _git(enclosing, "add", "f")
        _git(enclosing, "commit", "-q", "-m", "c")
        _git(enclosing, "worktree", "add", "-q", str(tmp_path / "wt-enclosing"), "-b", "agent/x")
        assert store.inherit(conn, str(tmp_path / "wt-enclosing"), "c0f1" * 8, projects_dir=str(b.projects)) is False
        _git(main, "worktree", "add", "-q", str(tmp_path / "wt-carried"), "-b", "agent/y")
        wt = os.path.realpath(tmp_path / "wt-carried")
        assert store.inherit(conn, wt, "c0f1" * 8, projects_dir=str(b.projects)) is True
        assert store.carried_op(conn, wt) is not None
        (main / "sub").mkdir()
        assert store.inherit(conn, str(main / "sub"), "c0f1" * 8, projects_dir=str(b.projects)) is False
        conn.execute("DELETE FROM pack_carried_trust WHERE folder = ?", (os.path.realpath(main),))
        assert store.carried_op(conn, wt) is None


def test_rows_are_dropped_with_the_project_and_on_move(world, monkeypatch) -> None:
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: True)
    uid, root = _migrate(world, True)
    real = os.path.realpath(root)
    with closing(b.conn()) as conn:
        project_id = conn.execute("SELECT id FROM projects WHERE uid = ?", (uid,)).fetchone()[0]
        assert store.carried_op(conn, real) is not None
        with conn:
            store.forget_project(conn, project_id)
        assert conn.execute("SELECT COUNT(*) FROM pack_carried_trust WHERE project_uid = ?", (uid,)).fetchone()[0] == 0


def _config(monkeypatch, tmp_path, trusted: list) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"projects": {str(k): {"hasTrustDialogAccepted": True} for k in trusted}}))
    monkeypatch.setattr(claude_folder_trust, "claude_json_path", lambda: cfg)


def test_source_trusted_mirrors_claude_2_1_296_and_stops_at_the_git_root(monkeypatch, tmp_path) -> None:
    tmp = Path(os.path.realpath(tmp_path))
    outer = tmp / "outer"
    repo = outer / "repo"
    (repo / "mid" / "deep").mkdir(parents=True)
    (repo / "other").mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "f").write_text("x")
    _git(repo, "add", "f")
    _git(repo, "commit", "-q", "-m", "c")
    plain = outer / "plain" / "child"
    plain.mkdir(parents=True)

    _config(monkeypatch, tmp, [outer])
    assert not store.source_trusted(str(repo)) and not store.source_trusted(str(repo / "mid" / "deep"))
    assert store.source_trusted(str(plain)) and store.source_trusted(str(outer / "plain"))
    _config(monkeypatch, tmp, [repo])
    assert store.source_trusted(str(repo)) and store.source_trusted(str(repo / "mid" / "deep")) and store.source_trusted(str(repo / "other"))
    assert not store.source_trusted(str(outer / "plain"))
    _config(monkeypatch, tmp, [repo / "mid"])
    assert store.source_trusted(str(repo / "mid" / "deep")) and store.source_trusted(str(repo / "mid"))
    assert not store.source_trusted(str(repo / "other")) and not store.source_trusted(str(repo))
    _config(monkeypatch, tmp, [repo])
    _git(repo, "worktree", "add", "-q", str(tmp / "wt"), "-b", "agent/z")
    assert store.source_trusted(str(tmp / "wt"))
    forged = tmp / "forged"
    forged.mkdir()
    (forged / ".git").write_text(f"gitdir: {repo}/.git/worktrees/none\n")
    assert not store.source_trusted(str(forged))
    (tmp / ".claude.json").unlink()
    assert not store.source_trusted(str(repo))


def test_a_peer_without_the_capability_gets_no_source_trusted_field_so_an_older_receiver_does_not_answer_400(world, monkeypatch) -> None:
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: True)
    seen = []

    def spy(sender, receiver):
        send = link(sender, receiver)

        async def request(method, path, **kw):
            if path.endswith("/migrate/prepare"):
                seen.append(dict(kw.get("json") or {}))
            return await send(method, path, **kw)
        return request

    uid = seed(a)
    with closing(a.conn()) as conn:
        project = dict(conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone())
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(capabilities=lambda iid: []))
    env = env_mod.source_env()
    made = asyncio.run(plan.plan_project(env, project, "iid-b", apply.guarded(spy(a, b))))
    asyncio.run(apply.apply_project(env, made, spy(a, b)))
    assert seen and all("source_trusted" not in body for body in seen)
    assert wire.source_trusted_field("iid-b", True) == {}
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(capabilities=lambda iid: [wire.CAP_TRUST_CARRY]))
    assert wire.source_trusted_field("iid-b", True) == {"source_trusted": True} and wire.source_trusted_field("iid-b", False) == {}
