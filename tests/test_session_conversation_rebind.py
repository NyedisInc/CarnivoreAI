
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
import types
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.attention.registry_record import REG_OK, REG_STALE, parse_registry_record
from src.core.attention.registry_index import registry_for_session
from src.core.db import connect, db_path_for, transaction
from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
    SESSION_ORIGIN_ADOPTED,
)
from src.core.session_claude_correlate_bind import bind_correlated_uuid
from src.core.session_conversation_rebind import (
    REBIND_DECLINED,
    REBIND_MARGIN_SECONDS,
    REBIND_UNRESOLVED,
    REBIND_WROTE,
    REASON_MATCH,
    REASON_REGISTRY_TRANSCRIPT_MISSING,
    REASON_REGISTRY_TRANSCRIPT_NEWER,
    REASON_ROW_TRANSCRIPT_MISSING,
    REASON_WITHIN_MARGIN,
    decide_conversation_rebind,
    rebind_conversation_uuid,
)
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row

ROW_UUID = "11111111-1111-1111-1111-111111111111"

REGISTRY_UUID = "22222222-2222-2222-2222-222222222222"

OTHER_UUID = "33333333-3333-3333-3333-333333333333"

NAME = "cloude_s7test_rebind"
EPOCH = 1_800_000_000
SESSION_ID = "ses_rebind"
WORKING_DIR = "/tmp/rebind-proj"

ROW_MTIME = 1_789_000_000.0


def _transcript(corpus: Path, uuid: str, mtime: float) -> Path:
    from src.core.claude_transcript_correlate import slugify_project_dir

    project = corpus / slugify_project_dir(WORKING_DIR)
    project.mkdir(parents=True, exist_ok=True)
    path = project / ("%s.jsonl" % uuid)
    path.write_text('{"type":"user"}\n', encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def corpus(tmp_path) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    return root


@pytest.fixture()
def home_corpus(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "home" / ".claude" / "projects"
    root.mkdir(parents=True)
    return root




def test_a_clearly_newer_registry_transcript_rebinds_the_row(corpus):
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)

    decision = decide_conversation_rebind(
        row_uuid=ROW_UUID,
        registry_uuid=REGISTRY_UUID,
        working_dir=WORKING_DIR,
        corpus_root=corpus,
    )

    assert decision.rebind is True
    assert decision.reason == REASON_REGISTRY_TRANSCRIPT_NEWER
    assert decision.row_transcript_mtime == ROW_MTIME
    assert decision.registry_transcript_mtime == ROW_MTIME + 120


def test_a_difference_inside_the_margin_does_not_rebind(corpus):
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 30)
    assert 30 < REBIND_MARGIN_SECONDS

    decision = decide_conversation_rebind(
        row_uuid=ROW_UUID,
        registry_uuid=REGISTRY_UUID,
        working_dir=WORKING_DIR,
        corpus_root=corpus,
    )

    assert decision.rebind is False
    assert decision.reason == REASON_WITHIN_MARGIN


def test_a_registry_conversation_with_no_transcript_never_wins(corpus):
    _transcript(corpus, ROW_UUID, ROW_MTIME)

    decision = decide_conversation_rebind(
        row_uuid=ROW_UUID,
        registry_uuid=REGISTRY_UUID,
        working_dir=WORKING_DIR,
        corpus_root=corpus,
    )

    assert decision.rebind is False
    assert decision.reason == REASON_REGISTRY_TRANSCRIPT_MISSING


def test_a_row_whose_own_transcript_is_gone_rebinds(corpus):
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME)

    decision = decide_conversation_rebind(
        row_uuid=ROW_UUID,
        registry_uuid=REGISTRY_UUID,
        working_dir=WORKING_DIR,
        corpus_root=corpus,
    )

    assert decision.rebind is True
    assert decision.reason == REASON_ROW_TRANSCRIPT_MISSING
    assert decision.row_transcript_mtime is None
    assert decision.registry_transcript_mtime == ROW_MTIME


def test_a_uuid_that_already_agrees_is_left_alone(corpus):
    _transcript(corpus, ROW_UUID, ROW_MTIME)

    decision = decide_conversation_rebind(
        row_uuid=ROW_UUID,
        registry_uuid=ROW_UUID,
        working_dir=WORKING_DIR,
        corpus_root=corpus,
    )

    assert decision.rebind is False
    assert decision.reason == REASON_MATCH


def test_the_conversation_gate_accepts_the_record_after_a_rebind(corpus):
    record = parse_registry_record(
        {
            "pid": 4242,
            "status": "busy",
            "sessionId": REGISTRY_UUID,
            "cwd": WORKING_DIR,
            "tmux": "%s:@0.%%0" % NAME,
            "version": "2.1.266",
        },
        path_pid=4242,
    )

    before = registry_for_session(
        tmux_name=NAME, index={NAME: record}, claude_session_uuid=ROW_UUID
    )
    assert before.verdict == REG_STALE

    after = registry_for_session(
        tmux_name=NAME, index={NAME: record}, claude_session_uuid=REGISTRY_UUID
    )
    assert after.verdict == REG_OK
    assert after.status == "busy"




class RebindManager:

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def _writable_datastore_connection(self):
        return connect(db_path_for(self._state_dir))

    def tmux_socket_name(self) -> str:
        return TEST_SOCKET


@pytest.fixture()
def anchored(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    with closing(migrated_connection(state_dir)) as conn:
        with transaction(conn):
            record_instance(
                conn,
                socket=TEST_SOCKET,
                name=NAME,
                epoch=EPOCH,
                origin=SESSION_ORIGIN_ADOPTED,
                working_dir=WORKING_DIR,
            )
            bind_correlated_uuid(
                conn,
                socket=TEST_SOCKET,
                name=NAME,
                epoch=EPOCH,
                claude_uuid=ROW_UUID,
            )
    return RebindManager(state_dir), state_dir


def test_the_rebind_writes_the_column_once_with_registry_provenance(
    anchored, corpus
):
    manager, state_dir = anchored
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)

    result = rebind_conversation_uuid(
        manager,
        session_id=SESSION_ID,
        tmux_name=NAME,
        epoch=EPOCH,
        registry_uuid=REGISTRY_UUID,
        corpus_root=corpus,
    )

    assert result.outcome == REBIND_WROTE
    with closing(connect(db_path_for(state_dir))) as conn:
        row = session_row(conn, NAME)
        assert row["claude_session_uuid"] == REGISTRY_UUID
        assert (
            row["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_REGISTRY
        )
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_a_refused_decision_writes_nothing(anchored, corpus):
    manager, state_dir = anchored
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 30)

    result = rebind_conversation_uuid(
        manager,
        session_id=SESSION_ID,
        tmux_name=NAME,
        epoch=EPOCH,
        registry_uuid=REGISTRY_UUID,
        corpus_root=corpus,
    )

    assert result.outcome == REBIND_DECLINED
    with closing(connect(db_path_for(state_dir))) as conn:
        assert session_row(conn, NAME)["claude_session_uuid"] == ROW_UUID


def test_a_conversation_recorded_on_a_LIVE_row_is_not_moved(anchored, corpus):
    manager, state_dir = anchored
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)
    with closing(connect(db_path_for(state_dir))) as conn:
        with transaction(conn):
            record_instance(
                conn,
                socket=TEST_SOCKET,
                name=NAME,
                epoch=EPOCH + 1,
                origin=SESSION_ORIGIN_ADOPTED,
                working_dir=WORKING_DIR,
            )
            bind_correlated_uuid(
                conn,
                socket=TEST_SOCKET,
                name=NAME,
                epoch=EPOCH + 1,
                claude_uuid=REGISTRY_UUID,
            )

    result = rebind_conversation_uuid(
        manager,
        session_id=SESSION_ID,
        tmux_name=NAME,
        epoch=EPOCH,
        registry_uuid=REGISTRY_UUID,
        corpus_root=corpus,
    )

    assert result.outcome == REBIND_UNRESOLVED
    with closing(connect(db_path_for(state_dir))) as conn:
        rows = conn.execute(
            "SELECT tmux_created_epoch, claude_session_uuid FROM sessions "
            "ORDER BY tmux_created_epoch"
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        (EPOCH, ROW_UUID),
        (EPOCH + 1, REGISTRY_UUID),
    ]




def test_the_watcher_side_effect_no_longer_swallows_a_mismatch(
    anchored, home_corpus
):
    from datetime import datetime, timezone

    from src.core.attention.evidence import (
        AttentionVerdict,
        Evidence,
        FAMILY_CLAUDE,
        REASON_TURN_ENDED,
        STATE_DONE_IDLE,
        TIER_REGISTRY,
    )
    from src.core.attention.side_effects import AttentionSideEffects
    from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
    from src.core.attention.watcher import Observation, WatchTarget
    from src.core.session_startup_gate_ledger import StartupGateLedger
    from src.core.session_status import LIVENESS_LIVE

    manager, state_dir = anchored
    _transcript(home_corpus, ROW_UUID, ROW_MTIME)
    _transcript(home_corpus, REGISTRY_UUID, ROW_MTIME + 120)

    manager._registry = types.SimpleNamespace(backends={})
    manager.hook_tokens = types.SimpleNamespace(name_for=lambda sid: NAME)
    manager._instance_epochs = {SESSION_ID: EPOCH}
    manager._startup_gate_ledger = StartupGateLedger()
    manager._persist_settled_activity_state = lambda *a, **k: None

    record = parse_registry_record(
        {
            "pid": 4242,
            "status": "busy",
            "sessionId": REGISTRY_UUID,
            "cwd": WORKING_DIR,
            "tmux": "%s:@0.%%0" % NAME,
            "version": "2.1.266",
        },
        path_pid=4242,
    )
    stale = registry_for_session(
        tmux_name=NAME, index={NAME: record}, claude_session_uuid=ROW_UUID
    )
    assert stale.verdict == REG_STALE

    effects = AttentionSideEffects(manager)
    effects._infer_agent = lambda *a: None
    effects._sync_title = lambda *a: None

    observation = Observation(
        verdict=AttentionVerdict(
            state=STATE_DONE_IDLE, reason=REASON_TURN_ENDED, tier=TIER_REGISTRY
        ),
        evidence=Evidence(
            tmux_liveness=LIVENESS_LIVE,
            agent_family=FAMILY_CLAUDE,
            registry=stale,
            transcript=TranscriptFacts(verdict=FACTS_FOUND),
            pane=None,
            now=datetime(2026, 9, 18, 6, 0, 0, tzinfo=timezone.utc),
        ),
        new_user_prompt_at=None,
        transcript_appended=False,
    )
    effects.on_observation(
        WatchTarget(session_id=SESSION_ID, key="%s@%d" % (NAME, EPOCH)), observation
    )

    with closing(connect(db_path_for(state_dir))) as conn:
        assert session_row(conn, NAME)["claude_session_uuid"] == REGISTRY_UUID




def _retire(state_dir: Path, *, uuid: str, name: str = NAME, epoch: int | None = None) -> int:
    with closing(connect(db_path_for(state_dir))) as conn:
        with transaction(conn):
            cursor = conn.execute(
                "INSERT INTO sessions (session_uuid, working_dir, tmux_socket, "
                "tmux_name, tmux_created_epoch, origin, agent_type, "
                "claude_session_uuid, lifecycle, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'claude', ?, 'stopped', ?, ?)",
                (
                    "retired-%s" % uuid,
                    WORKING_DIR,
                    TEST_SOCKET,
                    name,
                    epoch,
                    SESSION_ORIGIN_ADOPTED,
                    uuid,
                    "2026-09-10T19:22:13.113419Z",
                    "2026-09-10T19:22:13.113419Z",
                ),
            )
        return int(cursor.lastrowid)


def _live_uuid(conn) -> object:
    return conn.execute(
        "SELECT claude_session_uuid FROM sessions WHERE tmux_created_epoch = ?",
        (EPOCH,),
    ).fetchone()[0]


def _listing(*names: str, ok: bool = True, refused: int = 0):
    from src.core.tmux_listing import TmuxListing

    if not ok:
        listing = TmuxListing.unavailable("timeout")
    else:
        listing = TmuxListing.answered(list(names), refused_rows=refused)
    return lambda: listing


def test_retired_dead_pane_releases_uuid_but_live_or_unmeasured_panes_do_not(anchored, corpus):
    from src.core.session_conversation_takeover import _all_panes_dead

    manager, state_dir = anchored
    retired_name, retired_epoch = "cloude_retired", EPOCH - 1
    retired = _retire(state_dir, uuid=REGISTRY_UUID, name=retired_name, epoch=retired_epoch)
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)
    assert _all_panes_dead([f"{retired_epoch}|1|{retired_name}"], retired_name, retired_epoch) is True
    assert _all_panes_dead([f"{retired_epoch}|1|{retired_name}",
                            f"{retired_epoch}|0|{retired_name}"], retired_name, retired_epoch) is False
    assert _all_panes_dead([f"{retired_epoch + 1}|1|{retired_name}"], retired_name, retired_epoch) is None
    assert _all_panes_dead([], retired_name, retired_epoch) is None

    def rebind(panes_dead):
        return rebind_conversation_uuid(
            manager, session_id=SESSION_ID, tmux_name=NAME, epoch=EPOCH,
            registry_uuid=REGISTRY_UUID, corpus_root=corpus,
            listing_reader=_listing(NAME, retired_name),
            pane_probe=lambda socket, name, epoch: panes_dead,
        )

    for result in (False, None):
        assert rebind(result).outcome == REBIND_UNRESOLVED
        with closing(connect(db_path_for(state_dir))) as conn:
            assert _live_uuid(conn) == ROW_UUID
            assert conn.execute("SELECT claude_session_uuid FROM sessions WHERE id=?", (retired,)).fetchone()[0] == REGISTRY_UUID

    assert rebind(True).outcome == REBIND_WROTE
    with closing(connect(db_path_for(state_dir))) as conn:
        assert _live_uuid(conn) == REGISTRY_UUID
        assert conn.execute("SELECT claude_session_uuid FROM sessions WHERE id=?", (retired,)).fetchone()[0] is None


def test_retired_pane_probe_reads_every_pane_of_the_exact_tmux_instance():
    from src.core.session_conversation_takeover import probe_dead_instance_panes
    from tests.socket_guard import TEST_SOCKET_NAME

    socket = TEST_SOCKET_NAME
    name = "cloude_retired_probe"

    def tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["tmux", "-L", socket, "-f", "/dev/null", *args],
                              capture_output=True, text=True, check=check, timeout=5)

    try:
        tmux("new-session", "-d", "-s", name, "sleep 30")
        tmux("set-window-option", "-t", "=" + name, "remain-on-exit", "on")
        rows = tmux("list-sessions", "-F", "#{session_name}|#{session_created}").stdout.splitlines()
        epoch = int(next(row.split("|", 1)[1] for row in rows if row.startswith(name + "|")))
        tmux("send-keys", "-t", name + ":0.0", "C-c")
        for _ in range(40):
            if probe_dead_instance_panes(socket, name, epoch) is True:
                break
            time.sleep(0.05)
        else:
            pytest.fail("isolated tmux pane did not exit")
        tmux("new-window", "-d", "-t", "=" + name, "sleep 30")
        assert probe_dead_instance_panes(socket, name, epoch) is False
        tmux("kill-window", "-t", "=" + name + ":1")
        assert probe_dead_instance_panes(socket, name, epoch) is True
        assert probe_dead_instance_panes(socket, name, epoch + 1) is None
        tmux("kill-session", "-t", "=" + name)
        assert probe_dead_instance_panes(socket, name, epoch) is None
    finally:
        tmux("kill-session", "-t", "=" + name, check=False)


def test_a_retired_row_sharing_the_live_name_releases_the_conversation(
    anchored, corpus
):
    manager, state_dir = anchored
    retired = _retire(state_dir, uuid=REGISTRY_UUID)
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)

    result = rebind_conversation_uuid(
        manager,
        session_id=SESSION_ID,
        tmux_name=NAME,
        epoch=EPOCH,
        registry_uuid=REGISTRY_UUID,
        corpus_root=corpus,
        listing_reader=_listing(NAME),
    )

    assert result.outcome == REBIND_WROTE
    with closing(connect(db_path_for(state_dir))) as conn:
        live = conn.execute(
            "SELECT claude_session_uuid, claude_session_uuid_source FROM "
            "sessions WHERE tmux_created_epoch = ?",
            (EPOCH,),
        ).fetchone()
        held = conn.execute(
            "SELECT claude_session_uuid, lifecycle FROM sessions WHERE id = ?",
            (retired,),
        ).fetchone()
    assert live[0] == REGISTRY_UUID
    assert live[1] == SESSION_CLAUDE_UUID_SOURCE_REGISTRY
    assert held[0] is None
    assert held[1] == "stopped"


def test_a_listing_that_did_not_run_releases_nothing(anchored, corpus):
    manager, state_dir = anchored
    retired = _retire(state_dir, uuid=REGISTRY_UUID)
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)

    result = rebind_conversation_uuid(
        manager,
        session_id=SESSION_ID,
        tmux_name=NAME,
        epoch=EPOCH,
        registry_uuid=REGISTRY_UUID,
        corpus_root=corpus,
        listing_reader=_listing(ok=False),
    )

    assert result.outcome == REBIND_UNRESOLVED
    with closing(connect(db_path_for(state_dir))) as conn:
        assert _live_uuid(conn) == ROW_UUID
        assert (
            conn.execute(
                "SELECT claude_session_uuid FROM sessions WHERE id = ?",
                (retired,),
            ).fetchone()[0]
            == REGISTRY_UUID
        )


def test_a_retired_row_whose_own_pane_is_on_the_socket_releases_nothing(
    anchored, corpus
):
    manager, state_dir = anchored
    other_name = "cloude_s7test_rebind_other"
    retired = _retire(state_dir, uuid=REGISTRY_UUID, name=other_name)
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)

    result = rebind_conversation_uuid(
        manager,
        session_id=SESSION_ID,
        tmux_name=NAME,
        epoch=EPOCH,
        registry_uuid=REGISTRY_UUID,
        corpus_root=corpus,
        listing_reader=_listing(NAME, other_name),
    )

    assert result.outcome == REBIND_UNRESOLVED
    with closing(connect(db_path_for(state_dir))) as conn:
        assert session_row(conn, NAME)["claude_session_uuid"] == ROW_UUID
        assert (
            conn.execute(
                "SELECT claude_session_uuid FROM sessions WHERE id = ?",
                (retired,),
            ).fetchone()[0]
            == REGISTRY_UUID
        )


def test_a_retired_row_whose_own_pane_is_off_the_socket_releases_it(
    anchored, corpus
):
    manager, state_dir = anchored
    retired = _retire(
        state_dir, uuid=REGISTRY_UUID, name="cloude_s7test_rebind_gone"
    )
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)

    result = rebind_conversation_uuid(
        manager,
        session_id=SESSION_ID,
        tmux_name=NAME,
        epoch=EPOCH,
        registry_uuid=REGISTRY_UUID,
        corpus_root=corpus,
        listing_reader=_listing(NAME),
    )

    assert result.outcome == REBIND_WROTE
    with closing(connect(db_path_for(state_dir))) as conn:
        assert session_row(conn, NAME)["claude_session_uuid"] == REGISTRY_UUID
        assert (
            conn.execute(
                "SELECT claude_session_uuid FROM sessions WHERE id = ?",
                (retired,),
            ).fetchone()[0]
            is None
        )


def test_the_release_and_the_bind_are_one_transaction(anchored, corpus):
    manager, state_dir = anchored
    retired = _retire(state_dir, uuid=REGISTRY_UUID)
    _transcript(corpus, ROW_UUID, ROW_MTIME)
    _transcript(corpus, REGISTRY_UUID, ROW_MTIME + 120)

    from src.core import session_claude_correlate_bind as binder

    real_bind = binder.bind_correlated_uuid

    mid_transaction = {}

    def explode_after_release(conn, **kwargs):
        real_bind(conn, **kwargs)
        mid_transaction["holder_uuid"] = conn.execute(
            "SELECT claude_session_uuid FROM sessions WHERE id = ?", (retired,)
        ).fetchone()[0]
        raise sqlite3.OperationalError("disk I/O error after the release")

    binder.bind_correlated_uuid = explode_after_release
    try:
        result = rebind_conversation_uuid(
            manager,
            session_id=SESSION_ID,
            tmux_name=NAME,
            epoch=EPOCH,
            registry_uuid=REGISTRY_UUID,
            corpus_root=corpus,
            listing_reader=_listing(NAME),
        )
    finally:
        binder.bind_correlated_uuid = real_bind

    assert result.outcome == REBIND_UNRESOLVED
    assert mid_transaction["holder_uuid"] is None
    with closing(connect(db_path_for(state_dir))) as conn:
        assert _live_uuid(conn) == ROW_UUID
        assert (
            conn.execute(
                "SELECT claude_session_uuid FROM sessions WHERE id = ?",
                (retired,),
            ).fetchone()[0]
            == REGISTRY_UUID
        )
