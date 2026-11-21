
from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import claude_transcript_correlate as correlate_mod
from src.core.attention.registry_record import REG_ABSENT, REG_OK, RegistryRecord, _empty_record
from src.core.claude_resume_argv import ProcessRow
from src.core.claude_session_correlate_ladder import (
    LADDER_METHOD_PANE_ARGV,
    LADDER_METHOD_TRANSCRIPT_TIMING,
    LadderResult,
)
from src.core.db import connect, db_path_for, transaction
from src.core.session_adopt_persist import persist_adoption
from src.core.session_conversation_takeover import decide_conversation_takeover
from src.core.session_create_persist import persist_creation
from src.core.session_identity import record_instance
from src.core.sessions import adopt_confirm
from src.core.tmux_listing import TmuxListing
from tests.s7_helpers import TEST_SOCKET, listing_of, listing_row, migrated_connection

WORKING_DIR = "/Users/tester/Development/carnivore"
NAME = "carnivore_Guards2977"
OLD_EPOCH = 1_794_572_296
NEW_EPOCH = 1_794_585_531
CONVERSATION = "2629dba5-234e-44d2-be54-ddaf69c8db4b"
PANE_PID = 77123


@pytest.fixture()
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    projects = tmp_path / "projects"
    project_dir = projects / correlate_mod.slugify_project_dir(WORKING_DIR)
    project_dir.mkdir(parents=True)
    (project_dir / f"{CONVERSATION}.jsonl").write_text(json.dumps({
        "type": "user", "isSidechain": False, "timestamp": "2026-11-13T09:00:00Z",
        "sessionId": CONVERSATION, "entrypoint": "cli", "message": {"role": "user", "content": "hi"},
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(correlate_mod, "default_projects_dir", lambda: projects)
    monkeypatch.setattr("src.core.session_transcript_presence.default_corpus_root", lambda: projects, raising=False)
    directory = tmp_path / "state"
    directory.mkdir()
    with closing(migrated_connection(directory)):
        pass
    return directory


def _owner(state: Path, *, name: str = NAME, socket: str = TEST_SOCKET, host: Optional[str] = None) -> str:
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            record_instance(conn, socket=socket, name=name, epoch=OLD_EPOCH, origin="created", lifecycle="stopped",
                            lifecycle_source="tmux_missing", working_dir=WORKING_DIR)
            conn.execute("UPDATE sessions SET claude_session_uuid = ?, title = 'Carnivore' WHERE tmux_name = ?",
                         (CONVERSATION, name))
            if host:
                conn.execute("UPDATE sessions SET host_key = ? WHERE tmux_name = ?", (host, name))
        return str(conn.execute("SELECT session_uuid FROM sessions WHERE tmux_name = ?", (name,)).fetchone()[0])


def _all(state: Path) -> List[Dict[str, Any]]:
    with closing(connect(db_path_for(state))) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sessions ORDER BY id")]


def _adopt(state: Path, *, method: str = LADDER_METHOD_PANE_ARGV, refusal: Optional[str] = None,
           name: str = NAME, listing: Optional[TmuxListing] = None):
    ladder = LadderResult(outcome="matched", claude_session_uuid=CONVERSATION, method=method)
    live = listing or listing_of([listing_row(name, NEW_EPOCH, working_dir=WORKING_DIR, tmux_session_id="$9")])
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            return persist_adoption(conn, socket=TEST_SOCKET, name=name, listing=live, correlate=False,
                                    correlation=ladder, takeover_refusal=refusal)


def test_a_timing_rule_match_never_moves_a_row(state: Path) -> None:
    owner = _owner(state)
    result = _adopt(state, method=LADDER_METHOD_TRANSCRIPT_TIMING)
    assert result.session_uuid != owner, "the takeover acted on the transcript-timing guess"
    assert len(_all(state)) == 2


def test_an_unconfirmed_pane_never_moves_a_row(state: Path) -> None:
    owner = _owner(state)
    result = _adopt(state, refusal="claude's registry says the pane has a different conversation open")
    assert result.session_uuid != owner
    assert len(_all(state)) == 2


def test_an_owner_on_another_socket_is_left_alone(state: Path) -> None:
    owner = _owner(state, socket="some-other-socket")
    result = _adopt(state)
    assert result.session_uuid != owner
    assert {r["tmux_socket"] for r in _all(state)} == {"some-other-socket", TEST_SOCKET}


def test_an_owner_on_another_machine_is_left_alone(state: Path) -> None:
    owner = _owner(state, host="host-b")
    result = _adopt(state)
    assert result.session_uuid != owner
    assert len(_all(state)) == 2


def test_a_different_name_owner_is_refused_on_an_incomplete_listing(state: Path) -> None:
    owner = _owner(state, name="carnivore_Elsewhere")
    incomplete = TmuxListing.answered([listing_row(NAME, NEW_EPOCH, working_dir=WORKING_DIR, tmux_session_id="$9")],
                                      refused_rows=1)
    assert not incomplete.complete
    result = _adopt(state, listing=incomplete)
    assert result.session_uuid != owner, "an incomplete listing is not proof the owner's session is gone"


def test_a_same_name_owner_is_taken_over_even_on_an_incomplete_listing(state: Path) -> None:
    owner = _owner(state)
    incomplete = TmuxListing.answered([listing_row(NAME, NEW_EPOCH, working_dir=WORKING_DIR, tmux_session_id="$9")],
                                      refused_rows=1)
    assert _adopt(state, listing=incomplete).session_uuid == owner


def test_an_unprefixed_hand_typed_same_name_owner_is_taken_over(state: Path) -> None:
    owner = _owner(state, name="my-hand-typed-name")
    assert _adopt(state, name="my-hand-typed-name").session_uuid == owner


def test_the_gate_checks_the_same_name_before_the_namespace() -> None:
    decision = decide_conversation_takeover(
        incumbent_row_id=1, incumbent_lifecycle="stopped", incumbent_tmux_name="hand-typed", live_row_id=None,
        live_instance_unrecorded=True, live_tmux_name="hand-typed", listing_ok=True, listing_complete=True,
        names=["hand-typed"], namespace_prefix="carnivore_")
    assert decision.may_take, decision.detail


def test_two_unarchived_rows_holding_the_conversation_refuse(state: Path) -> None:
    owner = _owner(state)
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            conn.execute("DROP INDEX IF EXISTS ux_sessions_claude_uuid")
            record_instance(conn, socket=TEST_SOCKET, name="carnivore_Twin", epoch=OLD_EPOCH, origin="created",
                            lifecycle="stopped", lifecycle_source="tmux_missing", working_dir=WORKING_DIR)
            conn.execute("UPDATE sessions SET claude_session_uuid = ? WHERE tmux_name = 'carnivore_Twin'", (CONVERSATION,))
    assert _adopt(state).session_uuid != owner



def _write_registry(directory: Path, *, uuid: str = CONVERSATION, pid: Optional[int] = None, proc_start: Optional[str] = "",
                    name: str = NAME) -> int:
    from src.core.attention.record_identity import read_lstarts

    pid = pid or os.getpid()
    if proc_start == "":
        proc_start = (read_lstarts([pid]) or {}).get(pid)
    payload: Dict[str, Any] = {
        "sessionId": uuid, "cwd": WORKING_DIR, "startedAt": (NEW_EPOCH + 10) * 1000, "version": "2.1.266",
        "kind": "interactive", "tmux": f"{name}:@1.%2", "status": "idle", "pid": pid,
        "statusUpdatedAt": (NEW_EPOCH + 20) * 1000,
    }
    if proc_start:
        payload["procStart"] = proc_start
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{pid}.json").write_text(json.dumps(payload), encoding="utf-8")
    return pid


def _table(pid: int, command: Optional[str] = None) -> List[ProcessRow]:
    return [ProcessRow(pid=PANE_PID, ppid=1, command="-zsh"),
            ProcessRow(pid=pid, ppid=PANE_PID, command=command or f"claude --resume {CONVERSATION}")]


def _confirm(tmp: Path, table: List[ProcessRow], identity: Any = None) -> Optional[str]:
    return adopt_confirm.confirm_pane_conversation(
        name=NAME, epoch=NEW_EPOCH, claude_uuid=CONVERSATION, working_dir=WORKING_DIR, pane_pid=PANE_PID,
        registry_dir=str(tmp / "registry"), identity=identity, table=table)


def test_confirmation_passes_on_a_real_registry_file_tied_to_this_pane(state: Path, tmp_path: Path) -> None:
    pid = _write_registry(tmp_path / "registry")
    assert _confirm(tmp_path, _table(pid)) is None


def test_a_same_named_session_on_another_server_cannot_supply_the_record(state: Path, tmp_path: Path) -> None:
    _write_registry(tmp_path / "registry")
    assert "not a claude process in this pane's tree" in (_confirm(tmp_path, _table(424242)) or "")


def test_an_unmeasured_start_time_is_refused(state: Path, tmp_path: Path) -> None:
    from src.core.attention.record_identity import RecordIdentity

    pid = _write_registry(tmp_path / "registry")
    unmeasured = RecordIdentity(lstarts=lambda _pids: None)
    assert "not proven" in (_confirm(tmp_path, _table(pid), unmeasured) or "")


def test_a_record_with_no_proc_start_is_refused(state: Path, tmp_path: Path) -> None:
    pid = _write_registry(tmp_path / "registry", proc_start=None)
    assert "no start time" in (_confirm(tmp_path, _table(pid)) or "")


def test_stale_argv_is_refused_when_the_registry_names_another_conversation(state: Path, tmp_path: Path) -> None:
    pid = _write_registry(tmp_path / "registry", uuid="11111111-2222-4333-8444-555555555555")
    assert "different conversation" in (_confirm(tmp_path, _table(pid)) or "")


def test_no_registry_record_is_refused(state: Path, tmp_path: Path) -> None:
    (tmp_path / "registry").mkdir()
    assert _confirm(tmp_path, _table(os.getpid())) is not None


def test_a_fork_session_launch_is_refused(state: Path, tmp_path: Path) -> None:
    pid = _write_registry(tmp_path / "registry")
    assert "--fork-session" in (_confirm(tmp_path, _table(pid, f"claude --resume {CONVERSATION} --fork-session")) or "")


def test_a_missing_transcript_is_refused(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _write_registry(tmp_path / "registry")
    monkeypatch.setattr(adopt_confirm, "conversation_presence", lambda *_a, **_k: type("P", (), {"outcome": "absent"})())
    assert "transcript" in (_confirm(tmp_path, _table(pid)) or "")


def test_a_failed_confirmation_is_a_refusal_never_a_failed_adoption(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.sessions import adopt_takeover

    def boom(**_kw: Any) -> None:
        raise OSError("registry unreadable")

    monkeypatch.setattr(adopt_confirm, "confirm_pane_conversation", boom)
    monkeypatch.setattr(adopt_takeover, "confirm_pane_conversation", boom, raising=False)
    live = listing_of([listing_row(NAME, NEW_EPOCH, working_dir=WORKING_DIR)])
    ladder = LadderResult(outcome="matched", claude_session_uuid=CONVERSATION, method=LADDER_METHOD_PANE_ARGV)
    reason = adopt_takeover.confirm_for_takeover(live, name=NAME, correlation=ladder, working_dir=WORKING_DIR, pane_pid=1)
    assert reason is not None and "OSError" in reason



def test_the_takeover_steps_aside_while_a_recreate_of_the_row_is_in_flight(state: Path) -> None:
    from src.core import restart_inflight

    owner = _owner(state)
    with restart_inflight.claim(owner):
        result = _adopt(state)
    assert result.session_uuid != owner, "the takeover raced a recreate of the same row"
    assert len(_all(state)) == 2


def test_a_takeover_under_a_different_name_reports_the_old_name_for_the_pin(state: Path) -> None:
    _owner(state, name="carnivore_OldName")
    from src.core.session_adopt_persist import AdoptPersistResult  # noqa: F401

    result = _adopt(state, name=NAME)
    assert result.taken_over_from == "carnivore_OldName"



def test_a_recreate_that_loses_the_race_is_refused_before_any_write(state: Path) -> None:
    from src.core.sessions.reuse_guard import ReuseRowTakenError

    owner = _owner(state)
    assert _adopt(state).session_uuid == owner
    row_id = _all(state)[0]["id"]
    spawned = "carnivore_Recreated"
    listing = listing_of([
        listing_row(NAME, NEW_EPOCH, working_dir=WORKING_DIR, tmux_session_id="$9"),
        listing_row(spawned, NEW_EPOCH + 5, working_dir=WORKING_DIR, tmux_session_id="$10"),
    ])
    with closing(connect(db_path_for(state))) as conn:
        with pytest.raises(ReuseRowTakenError):
            with transaction(conn):
                persist_creation(conn, socket=TEST_SOCKET, name=spawned, listing=listing, working_dir=WORKING_DIR,
                                 agent_launched=True, reuse_session_id=row_id)
    rows = _all(state)
    assert len(rows) == 1, "a second row was minted for the same conversation"
    assert rows[0]["tmux_name"] == NAME and rows[0]["tmux_created_epoch"] == NEW_EPOCH



def _manager_adopting(state: Path, monkeypatch: pytest.MonkeyPatch, rekey):
    from unittest.mock import patch

    from src.core.session_manager import SessionManager
    from src.core.sessions.adopt_measure import AdoptMeasurements

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        mgr = SessionManager()
    ladder = LadderResult(outcome="matched", claude_session_uuid=CONVERSATION, method=LADDER_METHOD_PANE_ARGV)
    listing = listing_of([listing_row(NAME, NEW_EPOCH, working_dir=WORKING_DIR, tmux_session_id="$9")])
    monkeypatch.setattr(mgr, "_probe_instances", lambda: (TEST_SOCKET, listing))
    monkeypatch.setattr(mgr, "_writable_datastore_connection", lambda: connect(db_path_for(state)))
    monkeypatch.setattr("src.core.sessions.adopt_measure.measure_adoption",
                        lambda *_a, **_k: AdoptMeasurements(WORKING_DIR, PANE_PID, False, ladder, None))
    monkeypatch.setattr("src.core.session_agent_infer_sweep.sweep_live_sessions", lambda _m: None)
    monkeypatch.setattr(mgr._theme_store, "rekey_pin", rekey)
    return mgr


def test_the_manager_rekeys_the_pin_after_a_takeover_under_a_different_name(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _owner(state, name="carnivore_OldName")
    calls: List[Any] = []
    mgr = _manager_adopting(state, monkeypatch, lambda old, new: calls.append((old, new)))
    assert mgr.persist_adoption(NAME).persisted
    assert calls == [("carnivore_OldName", NAME)]


def test_a_pin_file_that_cannot_be_saved_does_not_read_as_a_failed_adopt(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _owner(state, name="carnivore_OldName")

    def unwritable(_old: str, _new: str) -> None:
        raise OSError("read-only file system")

    mgr = _manager_adopting(state, monkeypatch, unwritable)
    result = mgr.persist_adoption(NAME)
    assert result.persisted and result.session_uuid == owner, result.detail
