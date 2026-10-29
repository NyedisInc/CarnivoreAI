
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rcx_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rcx_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.attention_wiring import build_attention_watcher  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.hosts import store  # noqa: E402
from src.core.hosts.identity import remote_session_id  # noqa: E402
from src.core.hosts.remote_codex_files import CODEX_READ_SCOPE, files_for  # noqa: E402
from tests.test_hosts_remote_listing import _row  # noqa: E402
from tests.test_hosts_remote_sessions import HOST, TMUX, rig  # noqa: E402,F401

pytestmark = pytest.mark.skipif(TMUX is None or not shutil.which("sqlite3")
                                or not shutil.which("lsof"),
                                reason="tmux, sqlite3 or lsof is not installed")

UUID = "01a0e68d-37d2-7112-b5a8-9611731b38bd"
CHILD = "01a0e68f-2aa7-79d3-944c-6bd580c97de6"

THREADS_DDL = """CREATE TABLE threads (
    id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL, source TEXT NOT NULL, model_provider TEXT NOT NULL,
    cwd TEXT NOT NULL, title TEXT NOT NULL, sandbox_policy TEXT NOT NULL,
    approval_mode TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
    has_user_event INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
    archived_at INTEGER, git_sha TEXT, git_branch TEXT, git_origin_url TEXT,
    cli_version TEXT NOT NULL DEFAULT '', first_user_message TEXT NOT NULL DEFAULT '',
    agent_nickname TEXT, agent_role TEXT, memory_mode TEXT NOT NULL DEFAULT 'enabled',
    model TEXT, reasoning_effort TEXT, agent_path TEXT, created_at_ms INTEGER,
    updated_at_ms INTEGER, thread_source TEXT, preview TEXT NOT NULL DEFAULT '',
    recency_at INTEGER NOT NULL DEFAULT 0, recency_at_ms INTEGER NOT NULL DEFAULT 0,
    history_mode TEXT NOT NULL DEFAULT 'legacy', name TEXT)"""

HISTORY_DDL = """CREATE TABLE thread_turns (
    thread_id TEXT NOT NULL, turn_id TEXT NOT NULL, rollout_ordinal INTEGER NOT NULL,
    status TEXT NOT NULL, error_json TEXT, started_at INTEGER, completed_at INTEGER,
    duration_ms INTEGER, first_user_item_id TEXT, final_agent_item_id TEXT,
    rollout_byte_offset INTEGER, rollout_end_ordinal INTEGER, rollout_end_byte_offset INTEGER,
    PRIMARY KEY (thread_id, turn_id));
CREATE UNIQUE INDEX idx_thread_turns_page ON thread_turns(thread_id, rollout_ordinal);
CREATE TABLE thread_history_projection_state (
    thread_id TEXT PRIMARY KEY, next_rollout_byte_offset INTEGER NOT NULL,
    next_rollout_ordinal INTEGER NOT NULL);"""


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FarCodex:

    def __init__(self, home) -> None:
        self.dir = home / ".codex"
        (self.dir / "thread-writer-locks").mkdir(parents=True)
        (self.dir / "auth.json").write_text('{"sentinel": "never read"}')
        sessions = self.dir / "sessions" / "2026" / "09" / "28"
        sessions.mkdir(parents=True)
        self.rollout = sessions / f"rollout-2026-09-28T09-00-00-{UUID}.jsonl"
        self.append({"type": "session_meta", "payload": {"id": UUID}},
                    {"type": "event_msg", "payload": {"type": "user_message", "message": "go"}})
        with closing(sqlite3.connect(self.dir / "state_5.sqlite")) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(THREADS_DDL)
            for tid, source in ((UUID, "user"), (CHILD, "subagent")):
                conn.execute("INSERT INTO threads (id, rollout_path, created_at, updated_at, "
                             "source, model_provider, cwd, title, sandbox_policy, approval_mode, "
                             "thread_source) VALUES (?, ?, 1, 1, 'cli', 'openai', ?, 't', 'x', "
                             "'y', ?)", (tid, str(self.rollout), str(home / "proj"), source))
            conn.commit()
        assert not (self.dir / "state_5.sqlite-wal").exists()
        self.history = sqlite3.connect(self.dir / "thread_history_1.sqlite")
        self.history.execute("PRAGMA journal_mode=WAL")
        self.history.execute("PRAGMA wal_autocheckpoint=0")
        self.history.executescript(HISTORY_DDL)
        self.turn(1, "completed")

    def append(self, *records) -> None:
        with open(self.rollout, "a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps({"timestamp": _ts(), **record}) + "\n")

    def turn(self, ordinal: int, status: str) -> None:
        self.history.execute("INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, "
                             "status) VALUES (?, ?, ?, ?)", (UUID, f"t{ordinal}", ordinal, status))
        self.history.execute("INSERT OR REPLACE INTO thread_history_projection_state VALUES "
                             "(?, ?, ?)", (UUID, self.rollout.stat().st_size, ordinal))
        self.history.commit()
        assert (self.dir / "thread_history_1.sqlite-wal").stat().st_size > 0


def _fake_codex(rig) -> None:
    locks = '"$HOME/.codex/thread-writer-locks"'
    rig.fake.add_tool("codex", f'exec 3>>{locks}/{UUID}.lock 4>>{locks}/{CHILD}.lock\n'
                               'echo "fake-codex:$*"; exec /bin/sh\n')
    with closing(connect(db_path_for(rig.state), create=False)) as conn:
        store.record_probe(conn, HOST, {
            "probe_state": "ok", "probe_detail": None, "login_shell": "/bin/sh",
            "login_path": f"{rig.fake.bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "tmux_path": str(TMUX), "tmux_version": "tmux 3.7c",
            "agent_paths_json": json.dumps({"claude": f"{rig.fake.bin_dir}/claude",
                                            "codex": f"{rig.fake.bin_dir}/codex"}),
            "machine_id": None, "remote_carnivore": "none"})


def _no_sqlite_path(rig) -> str:
    shim = rig.fake.root / "nosqlite"
    shim.mkdir()
    for tool in ("ps", "lsof", "sed", "sort", "head", "tail", "wc", "tr", "printf"):
        found = shutil.which(tool)
        if found:
            (shim / tool).symlink_to(found)
    return f"{shim}:/bin"


_SCOPE_REF = re.compile(r'(?:"\$C"/|\.codex/)([^\s"\';|)]+)')


def scope_ok(command: str) -> bool:
    if "auth.json" in command or "credentials" in command:
        return False
    return all(ref.startswith(CODEX_READ_SCOPE) for ref in _SCOPE_REF.findall(command))


async def _wait_far_text(rig, text: str) -> None:
    pipes = rig.fake.root / "home" / ".cache" / "carnivore" / "pipes"
    for _ in range(100):
        if any(text in p.read_text(errors="replace") for p in pipes.glob("*.pipe")):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{text!r} never reached the far pane")


async def _wait_lock_held(rig) -> None:
    host = await rig.mgr.hosts.get(HOST)
    lock = rig.fake.root / "home" / ".codex" / "thread-writer-locks" / f"{UUID}.lock"
    for _ in range(100):
        if (await host.exec(["lsof", "-t", str(lock)])).stdout_text.strip():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the far codex never held its writer lock")


async def _far_dead(rig, name: str) -> bool:
    host = await rig.mgr.hosts.get(HOST)
    result = await host.exec([str(TMUX), "-L", "carnivore-remote", "list-panes", "-t",
                              f"={name}", "-F", "#{pane_dead}"])
    return result.stdout_text.strip() == "1"


@pytest.mark.asyncio
async def test_a_remote_codex_session_gets_the_far_record_transcript_bind_and_resume(rig):
    mgr, far = rig.mgr, FarCodex(rig.fake.root / "home")
    _fake_codex(rig)
    (rig.fake.root / "home" / "proj").mkdir()
    try:
        remote = await mgr.create_session(session_id="ses_c0de0001", working_dir="~/proj",
                                          auto_start_claude=True, project_name="rcx",
                                          agent_type="codex", host_key=HOST)
        name = remote.tmux_session
        await _wait_lock_held(rig)
        watcher = build_attention_watcher(mgr, tick_seconds=0.0)

        def seen():
            observation = watcher.observation_for(remote.id)
            return observation.verdict, observation.evidence.codex

        far.turn(2, "inProgress")
        for _ in range(2):
            await watcher.tick_once()
        verdict, codex = seen()
        assert (verdict.state, verdict.tier, codex.record.verdict) == ("busy", "registry", "busy")
        assert _row(rig, HOST, name)["claude_session_uuid"] == UUID
        host = await mgr.hosts.get(HOST)
        assert files_for(host).holders[CHILD] == files_for(host).holders[UUID]

        far.append({"type": "response_item", "payload": {
            "type": "function_call", "name": "request_user_input", "call_id": "q1",
            "arguments": "{}"}})
        start = files_for(host)._windows[UUID].start
        await watcher.tick_once()
        verdict, codex = seen()
        assert (verdict.state, verdict.reason, verdict.tier) == ("needs_user", "question",
                                                                 "transcript")
        window = files_for(host)._windows[UUID]
        assert (window.start, window.end) == (start, far.rollout.stat().st_size)

        far.append({"type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "q1", "output": "ok"}},
            {"type": "event_msg", "payload": {"type": "task_complete"}})
        far.turn(3, "completed")
        await watcher.tick_once()
        verdict, codex = seen()
        assert (verdict.state, verdict.tier, codex.record.rest_kind) == (
            "done_idle", "registry", "completed")

        history = far.dir / "thread_history_1.sqlite"
        state = far.dir / "state_5.sqlite"
        rig.fake.set("path", _no_sqlite_path(rig))
        await watcher.tick_once()
        verdict, codex = seen()
        assert (verdict.state, codex.record.verdict, codex.pane is not None) == (
            "unknown", "absent", True)
        assert "no sqlite3" in codex.detail
        rig.fake.set("path", "/usr/bin:/bin:/usr/sbin:/sbin")
        far.history.execute("ALTER TABLE thread_turns RENAME TO thread_turns_v9")
        far.history.commit()
        await watcher.tick_once()
        verdict, codex = seen()
        assert (verdict.state, codex.record.verdict, codex.pane is not None) == (
            "unknown", "absent", True)
        assert "unknown schema" in codex.detail
        far.history.execute("ALTER TABLE thread_turns_v9 RENAME TO thread_turns")
        far.history.commit()
        state.chmod(0)
        await watcher.tick_once()
        verdict, codex = seen()
        assert (verdict.state, codex.record.verdict, codex.pane is not None) == (
            "unknown", "absent", True)
        state.chmod(0o644)
        await watcher.tick_once()
        assert seen()[1].record.verdict == "rest"
        assert history.exists()

        await mgr.send_input("exit\r", session_id=remote.id)
        for _ in range(100):
            if await _far_dead(rig, name):
                break
            await asyncio.sleep(0.1)
        result = await mgr.respawn_session(remote_session_id(HOST, name))
        assert result["ok"] is True and f"'resume' '{UUID}'" in result["command"], result
        await _wait_far_text(rig, f"fake-codex:resume {UUID}")

        commands = [" ".join(call["argv"]) for call in rig.fake.calls()]
        assert any("thread-writer-locks" in c for c in commands)
        assert all(scope_ok(c) for c in commands), [c for c in commands if not scope_ok(c)]
        assert not scope_ok('cat "$C"/auth.json') and not scope_ok("cat ~/.codex/config.toml")
    finally:
        far.history.close()
