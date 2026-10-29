
from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.approvals import carried_trust
from src.core.approvals.carried_trust import YES_LABEL
from tests.python.approvals.auto_helpers import make_engine
from src.core.approvals.auto_answer.engine import MAX_ATTEMPTS
from src.core.approvals.auto_answer.press import AckRefused
from src.core.approvals.extract import extract_dialog
from src.core.pack.identity import home, replicas
from src.core.pack.migrate import receive as receive_mod
from src.core.pack.trust_carry import store
from src.core.swarm import auto_trust
from tests.python.pack.test_trust_carry import _git, _migrate, _peer_reads_trust, _screen  # noqa: F401
from tests.python.pack.test_trust_carry import world  # noqa: F401

WAIT = auto_trust.CARRIED_WAIT_SECONDS


def _rows(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM pack_carried_trust").fetchone()[0]


def _carried(world, monkeypatch):
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: True)
    uid, root = _migrate(world, True)
    return b, os.path.realpath(root), uid


def _drive(b, folder, readings, *, refuse: int = 0):
    sent, tries = [], []
    state = {"gate": None, "now": 0.0}

    async def answer(sid, fingerprint, label):
        tries.append(1)
        if len(tries) <= refuse:
            raise AckRefused("dialog_changed")
        sent.append(label)

    async def info(_sid):
        return SimpleNamespace(session=SimpleNamespace(working_dir=folder), agent_family="claude", startup_gate=state["gate"])

    def lookup(path):
        with closing(b.conn()) as conn:
            return store.carried_op(conn, path)

    dialog = extract_dialog(_screen(folder), "claude")
    obs = SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=dialog, identity=("s", "n", 1, 9)))

    async def run():
        ack = make_engine(answer=answer, info=info, lookup=lookup, clock=lambda: state["now"])
        for gate, now in readings:
            state["gate"], state["now"] = gate, now
            task = ack.on_observation(SimpleNamespace(session_id="ses_1"), obs)
            if task is not None:
                await task

    asyncio.run(run())
    return sent, len(tries)


def test_unmeasured_readings_are_not_attempts_and_the_wait_is_bounded(world, monkeypatch) -> None:
    b, real, _uid = _carried(world, monkeypatch)
    awaiting = "awaiting_startup_prompt"
    sent, tries = _drive(b, real, [("unknown", 0), ("unknown", 2), ("unknown", 4), (awaiting, 6), (awaiting, 8)])
    assert sent == [YES_LABEL] and tries == 1
    for gate in ("unknown", None, "ready"):
        assert _drive(b, real, [(gate, n) for n in range(0, 40, 2)])[0] == []
    assert _drive(b, real, [("unknown", 0), ("unknown", WAIT / 2), (awaiting, WAIT + 1)]) == ([], 0)
    assert _drive(b, real, [("unknown", 0), (awaiting, WAIT - 1)])[0] == [YES_LABEL]
    sent, tries = _drive(b, real, [(awaiting, n) for n in range(0, 20, 2)], refuse=99)
    assert sent == [] and tries == MAX_ATTEMPTS
    assert _drive(b, real, [(awaiting, 0), (awaiting, 2), (awaiting, 4), (awaiting, 6)], refuse=MAX_ATTEMPTS - 1) == ([YES_LABEL], MAX_ATTEMPTS)


def test_the_swarm_path_answers_a_carried_folder_only_when_measured_awaiting_and_waits_without_a_card(world, monkeypatch) -> None:
    b, real, uid = _carried(world, monkeypatch)
    dialog = extract_dialog(_screen(real), "claude")
    agent = {"id": 1, "repo_dir": real, "torn_down_at": None}
    wake = {"id": 5}

    def info(gate, work=real):
        return SimpleNamespace(agent_family="claude", startup_gate=gate, session=SimpleNamespace(working_dir=work))

    monkeypatch.setattr("src.core.swarm.delivery.kickoff_recorded", lambda *a, **k: False)
    with closing(b.conn()) as conn:
        assert auto_trust.may_auto_answer(conn, agent, wake, info("awaiting_startup_prompt"), dialog) is True
        for gate in ("unknown", None, "ready"):
            assert auto_trust.may_auto_answer(conn, agent, wake, info(gate), dialog) is False, gate
        assert auto_trust.may_auto_answer(conn, agent, wake, info("unknown"), dialog, allow_unmeasured=True) is True
        assert auto_trust.may_auto_answer(conn, agent, wake, info("ready"), dialog, allow_unmeasured=True) is False
        warned = extract_dialog(_screen(real, warning=" ⚠ This folder configures hooks that run commands: .claude/settings.json"), "claude")
        assert auto_trust.may_auto_answer(conn, agent, wake, info("awaiting_startup_prompt"), warned) is False
        assert auto_trust.may_auto_answer(conn, agent, wake, info("unknown"), warned, allow_unmeasured=True) is False


def test_the_swarm_wake_waits_on_an_unmeasured_gate_without_a_card_for_the_window_then_the_card_takes_over(world, monkeypatch) -> None:
    from src.core.swarm import body, delivery

    b, real, _uid = _carried(world, monkeypatch)
    dialog = extract_dialog(_screen(real), "claude")
    agent, now = {"id": 1, "repo_dir": real, "torn_down_at": None}, [1000.0]
    info = SimpleNamespace(agent_family="claude", startup_gate="unknown", session=SimpleNamespace(id="ses_1", working_dir=real))

    async def run_db(fn):
        with closing(b.conn()) as conn:
            return fn(conn)

    async def get_wake(_c, _id):
        return None

    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(delivery.store, "get_open_wake", lambda conn, agent_id: {"id": 5})
    monkeypatch.setattr(delivery, "kickoff_recorded", lambda *a, **k: False, raising=False)
    monkeypatch.setattr("src.core.swarm.delivery.kickoff_recorded", lambda *a, **k: False)
    monkeypatch.setattr(delivery, "time", SimpleNamespace(monotonic=lambda: now[0]))
    sent = []

    async def send(_state, sid, fingerprint, label):
        sent.append(label)

    monkeypatch.setattr(delivery, "_send_answer", send)
    monkeypatch.setattr(delivery, "AUTO_TRUST_CONFIRM_S", 0.05)
    monkeypatch.setattr(delivery, "AUTO_TRUST_POLL_S", 0.01)
    delivery._trust_carried_since.clear()
    delivery._trust_auto_tries.clear()
    delivery._trust_auto_at.clear()
    run = lambda: asyncio.run(delivery._auto_trust(SimpleNamespace(attention_watcher=None), agent, 5, info, dialog))  # noqa: E731
    assert run() is True and sent == [] and not delivery._trust_auto_tries
    now[0] += WAIT / 2
    assert run() is True and sent == []
    now[0] += WAIT
    assert run() is False and sent == []
    delivery._trust_carried_since.clear()
    info.startup_gate = "awaiting_startup_prompt"
    run()
    assert sent == [YES_LABEL]
    info.startup_gate = "ready"
    delivery._trust_carried_since.clear()
    assert run() is False
    for table in (delivery._trust_carried_since, delivery._trust_auto_tries, delivery._trust_auto_at):
        table.clear()


def test_rows_are_stored_under_the_canonical_spelling_and_a_symlinked_folder_is_refused(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    real_projects = tmp_path / "realprojects"
    real_projects.mkdir()
    via_link = tmp_path / "linkprojects"
    os.symlink(real_projects, via_link)
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: via_link, raising=True)
    with closing(b.conn()) as conn:
        (real_projects / "sub").mkdir()
        for n, root in enumerate((via_link / "fresh", f"{real_projects}/sub/../dotdot")):
            replicas.accept_replica(conn, home_install_id="iid-a", project_uid=f"{n}1a2" * 8, name=f"p{n}", root=str(root), source_trusted=True)
            want = os.path.realpath(root)
            assert store.carried_op(conn, want) is not None and store.carried_op(conn, str(root)) is not None, root
            assert conn.execute("SELECT folder FROM pack_carried_trust WHERE project_uid = ?", (f"{n}1a2" * 8,)).fetchone()[0] == want
        target = real_projects / "target"
        target.mkdir()
        os.symlink(target, real_projects / "swapped")
        before = _rows(conn)
        assert store.record(conn, str(real_projects / "swapped"), "s" * 32, "iid-a", "op-s", projects_dir=str(real_projects)) is False
        assert store.canonical_folder(str(real_projects / "swapped")) is None
        assert _rows(conn) == before
        assert store.record(conn, str(target), "t" * 32, "iid-a", "op-t", projects_dir=str(real_projects)) is True
        assert store.record(conn, str(real_projects) + "/", "u" * 32, "iid-a", "op-u", projects_dir=str(real_projects)) is False


def test_the_receive_time_measurement_decides_not_the_prepare_time_one(world, monkeypatch) -> None:
    a, b, current, link = world
    monkeypatch.setattr(store, "source_trusted", lambda folder: True)
    real_bring = receive_mod.code.bring

    def bring_then_lose_the_claim(rung, root, undo, **kw):
        real_bring(rung, root, undo, **kw)
        undo.pop("root_created", None)
    monkeypatch.setattr(receive_mod.code, "bring", bring_then_lose_the_claim)
    uid, root = _migrate(world, True)
    with closing(b.conn()) as conn:
        assert _rows(conn) == 0
    monkeypatch.setattr(receive_mod.code, "bring", lambda rung, root, undo, **kw: (real_bring(rung, root, undo, **kw), undo.update(aside="/x"))[0])
    (b.projects / "trader2").mkdir()


def test_inherit_runs_the_guards_of_record(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: b.projects, raising=True)
    uid = "c0f1" * 8
    with closing(b.conn()) as conn:
        replicas.accept_replica(conn, home_install_id="iid-a", project_uid=uid, name="carried", root=str(b.projects / "carried"), source_trusted=True)
        main = b.projects / "carried"
        _git(main, "init", "-q", "-b", "main")
        (main / "f").write_text("x")
        _git(main, "add", "f")
        _git(main, "commit", "-q", "-m", "c")
        _git(main, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "agent/w")
        wt = os.path.realpath(tmp_path / "wt")
        elsewhere = tmp_path / "not-the-projects-folder"
        elsewhere.mkdir()
        assert store.inherit(conn, wt, uid, projects_dir=str(elsewhere)) is False
        assert store.inherit(conn, wt, uid, projects_dir=str(b.projects)) is True
        _git(main, "worktree", "add", "-q", str(tmp_path / "wt2"), "-b", "agent/x")
        os.symlink(tmp_path / "wt2", tmp_path / "wt2link")
        assert store.inherit(conn, str(tmp_path / "wt2link"), uid, projects_dir=str(b.projects)) is False
        assert conn.execute("SELECT COUNT(*) FROM pack_carried_trust WHERE folder = ?", (os.path.realpath(tmp_path / "wt2"),)).fetchone()[0] == 0
        assert store.inherit(conn, os.path.realpath(tmp_path / "wt2"), "d0f1" * 8, projects_dir=str(b.projects)) is False


def test_the_body_host_inherits_a_carried_projects_trust_into_its_worktree(world, monkeypatch, tmp_path) -> None:
    from src.core.pack.span import body_host

    seen = []
    monkeypatch.setattr(body_host.trust_store, "inherit", lambda conn, repo, uid, *, projects_dir: seen.append((repo, uid, projects_dir)) or False)
    source = Path(body_host.__file__).read_text()
    assert "trust_store.inherit(c, repo, packet.project_uid, projects_dir=str(settings.get_working_dir()))" in source
    assert body_host.settings is settings


def test_a_project_that_moved_away_keeps_no_row_and_a_return_never_revives_it(world, monkeypatch) -> None:
    b, real, uid = _carried(world, monkeypatch)
    with closing(b.conn()) as conn:
        pid = conn.execute("SELECT id FROM projects WHERE uid = ?", (uid,)).fetchone()[0]
        assert store.carried_op(conn, real) is not None
        home.set_state(conn, pid, home.MOVED_AWAY, moved_to_install_id="iid-a")
        assert _rows(conn) == 0
        home.set_state(conn, pid, home.HOME)
        assert store.carried_op(conn, real) is None and _rows(conn) == 0


def test_delete_move_and_detach_each_drop_the_projects_rows(world, monkeypatch) -> None:
    from src.core import project_writes
    from src.core.project_move import apply as move_apply

    b, real, uid = _carried(world, monkeypatch)
    with closing(b.conn()) as conn:
        pid = conn.execute("SELECT id FROM projects WHERE uid = ?", (uid,)).fetchone()[0]
        plan = SimpleNamespace(old_root=real, new_root=real + "-moved", project={"id": pid}, children=[], transcript_moves=[])
        move_apply._rewrite_db(conn, plan)
        assert _rows(conn) == 0
    b2, real2, uid2 = _carried_again(b)
    with closing(b.conn()) as conn:
        pid2 = conn.execute("SELECT id FROM projects WHERE uid = ?", (uid2,)).fetchone()[0]
        project_writes.delete_project(conn, pid2)
        assert _rows(conn) == 0
    uid3 = _carried_again(b)[2]
    with closing(b.conn()) as conn:
        conn.execute("UPDATE projects SET pack_state = 'replica', home_install_id = 'iid-a' WHERE uid = ?", (uid3,))
        conn.commit()
        assert replicas.detach_replica(conn, home_install_id="iid-a", project_uid=uid3) is True
        assert _rows(conn) == 0


def _carried_again(b):
    n = os.urandom(3).hex()
    folder = os.path.join(os.path.realpath(b.projects), f"again-{n}")
    uid = (n * 6)[:32]
    os.makedirs(folder)
    with closing(b.conn()) as conn:
        from src.core.project_writes import create_project
        create_project(conn, name=f"again-{n}", path=folder)
        conn.execute("UPDATE projects SET uid = ? WHERE root = ?", (uid, folder))
        conn.commit()
        assert store.record(conn, folder, uid, "iid-a", f"op-{n}", projects_dir=str(b.projects))
        assert store.carried_op(conn, folder) is not None
    return b, folder, uid


def test_plain_dialog_must_match_head_and_tail_text_exactly_and_only_the_claude_family(tmp_path) -> None:
    import dataclasses

    folder = str(tmp_path)
    good = extract_dialog(_screen(folder), "claude")
    assert auto_trust.plain_dialog_folder(good) == folder
    for old, new in (("Accessing workspace:", "Accessing workspacf:"), ("Claude Code'll be able to read", "Claude Code'll be able to reaf")):
        dialog = extract_dialog(_screen(folder).replace(old, new), "claude")
        assert dialog is not None and auto_trust.is_claude_trust_dialog(dialog), old
        assert auto_trust.plain_dialog_folder(dialog) is None, old
    assert auto_trust.is_claude_trust_dialog(dataclasses.replace(good, family="codex")) is False


def test_inherit_of_the_carried_main_repo_itself_writes_nothing(world, monkeypatch) -> None:
    a, b, current, link = world
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: b.projects, raising=True)
    uid = "e0f1" * 8
    with closing(b.conn()) as conn:
        replicas.accept_replica(conn, home_install_id="iid-a", project_uid=uid, name="selfmain", root=str(b.projects / "selfmain"), source_trusted=True)
        main = b.projects / "selfmain"
        _git(main, "init", "-q", "-b", "main")
        before = _rows(conn)
        assert store.inherit(conn, str(main), uid, projects_dir=str(b.projects)) is False
        assert _rows(conn) == before
