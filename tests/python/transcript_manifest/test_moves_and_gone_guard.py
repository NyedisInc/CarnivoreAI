
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
import structlog

from src.core.backup_health import constants as HK
from src.core.backup_health.checks import FIRING, OK
from src.core.backup_health.transcript_check import check_transcripts_unprotected
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.deepsearch import fallback_hook as fb
from src.core.transcript_manifest import condition, gone_guard
from src.core.transcript_manifest import constants as K

A = "aaaaaaaa-0000-0000-0000-00000000000a"
B = "aaaaaaaa-0000-0000-0000-00000000000b"


def _line(serial: str) -> bytes:
    return json.dumps({"type": "user", "uuid": serial, "cwd": "/x"}).encode() + b"\n"


class _Vault:

    def __init__(self, held: List[str]) -> None:
        self.held = held

    def files(self, conversation_id: str):
        return [object()] if conversation_id in self.held else []


@pytest.fixture()
def world(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    corpus = tmp_path / "projects"
    (corpus / "-old").mkdir(parents=True)
    (corpus / "-new").mkdir()
    (corpus / "-old" / f"{A}.jsonl").write_bytes(_line("a1") + _line("a2"))
    (corpus / "-old" / f"{B}.jsonl").write_bytes(_line("b1"))
    fb.unregister("t")
    yield type("W", (), {"state": state, "corpus": corpus, "db": db_path_for(state)})()
    fb.unregister("t")
    condition.uninstall()


def _scan(world) -> dict:
    record = condition.run_scan(world.state, claude_roots=(world.corpus,), codex_home="")
    assert record["status"] == "ok", record
    return record


def test_a_file_moved_to_another_folder_in_one_scan_is_a_move_not_a_loss(world):
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").rename(world.corpus / "-new" / f"{A}.jsonl")
    record = _scan(world)
    assert (record[K.OUT_MOVED], record[K.OUT_REMOVED], record[K.OUT_ADDED]) == (1, 0, 0)


def test_a_file_that_changed_size_while_moving_is_still_a_removal_plus_an_addition(world):
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    (world.corpus / "-new" / f"{A}.jsonl").write_bytes(_line("a1") + _line("a2") + _line("a3"))
    record = _scan(world)
    assert (record[K.OUT_MOVED], record[K.OUT_REMOVED], record[K.OUT_ADDED]) == (0, 1, 1)


def test_a_different_last_line_at_the_same_size_is_not_the_same_file(world):
    _scan(world)
    (world.corpus / "-old" / f"{B}.jsonl").unlink()
    (world.corpus / "-new" / f"{B}.jsonl").write_bytes(_line("z1"))
    record = _scan(world)
    assert (record[K.OUT_MOVED], record[K.OUT_REMOVED], record[K.OUT_ADDED]) == (0, 1, 1)


def test_a_plain_removal_is_still_a_removal(world):
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    record = _scan(world)
    assert (record[K.OUT_MOVED], record[K.OUT_REMOVED]) == (0, 1)


def test_a_removal_the_vault_does_not_hold_is_an_error_a_record_and_a_backup_health_alert(world):
    fb.register("t", _Vault(held=[B]))
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    with structlog.testing.capture_logs() as logs:
        _scan(world)
    errors = [e for e in logs if e["event"] == "transcript_gone_without_vault_copy" and e["log_level"] == "error"]
    assert [e["conversation_id"] for e in errors] == [A]
    verdict = check_transcripts_unprotected(world.state)
    assert verdict.state == FIRING and verdict.severity == "error" and verdict.params["count"] == 1
    assert verdict.key == HK.KEY_TRANSCRIPTS_GONE_UNPROTECTED and A in verdict.params["samples"]


def test_a_removal_the_vault_holds_raises_nothing(world):
    fb.register("t", _Vault(held=[A, B]))
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    with structlog.testing.capture_logs() as logs:
        _scan(world)
    assert not [e for e in logs if e["event"] == "transcript_gone_without_vault_copy"]
    assert check_transcripts_unprotected(world.state).state == OK


def test_a_moved_file_never_reaches_the_audit(world):
    fb.register("t", _Vault(held=[]))
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").rename(world.corpus / "-new" / f"{A}.jsonl")
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == OK


def test_the_alert_clears_when_the_vault_gains_the_copy(world, monkeypatch):
    monkeypatch.setattr(gone_guard, "RECHECK_SECONDS", 0.0)
    vault = _Vault(held=[B])
    fb.register("t", vault)
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == FIRING
    vault.held.append(A)
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == OK


def test_with_no_vault_registered_nothing_is_asked_and_nothing_is_raised(world):
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    _scan(world)
    assert not (world.state / gone_guard.RECORD_FILE).exists()


def test_the_check_is_one_of_the_passes_backup_health_runs():
    import inspect

    from src.core.backup_health import runner

    assert "check_transcripts_unprotected" in inspect.getsource(runner.run_checks)




class _Down:

    def __init__(self, held: List[str]) -> None:
        self.held, self.up = held, False

    def files(self, conversation_id: str):
        if not self.up:
            raise OSError("vault volume not mounted")
        return [object()] if conversation_id in self.held else []


def test_a_removal_while_the_vault_is_unreadable_alerts_once_the_vault_answers(world):
    vault = _Down(held=[B])
    fb.register("t", vault)
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == OK
    assert A in gone_guard.read_record(world.state)["pending"]
    vault.up = True
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == FIRING
    assert not gone_guard.read_record(world.state)["pending"]


def test_a_pending_removal_the_vault_then_holds_is_forgotten(world):
    vault = _Down(held=[A, B])
    fb.register("t", vault)
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    _scan(world)
    vault.up = True
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == OK
    assert not gone_guard.read_record(world.state).get("pending")


def test_a_removal_during_startup_is_asked_again_after_startup(world):
    fb.register("t", _Vault(held=[B]))
    _scan(world)
    fb.begin_boot()
    try:
        (world.corpus / "-old" / f"{A}.jsonl").unlink()
        _scan(world)
    finally:
        fb.end_boot()
    assert check_transcripts_unprotected(world.state).state == OK
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == FIRING


def test_a_removal_before_any_plugin_registered_a_source_is_kept_pending(world):
    _scan(world)
    fb.begin_boot()
    try:
        (world.corpus / "-old" / f"{A}.jsonl").unlink()
        _scan(world)
    finally:
        fb.end_boot()
    fb.register("t", _Vault(held=[B]))
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == FIRING


def test_ids_past_the_record_cap_are_counted_and_named_in_the_alert(world, monkeypatch):
    monkeypatch.setattr(gone_guard, "MAX_IDS", 2)
    fb.register("t", _Vault(held=[]))
    extra = [f"bbbbbbbb-0000-0000-0000-00000000000{i}" for i in range(3)]
    for conv in extra:
        (world.corpus / "-old" / f"{conv}.jsonl").write_bytes(_line(conv[-4:]))
    _scan(world)
    for path in list((world.corpus / "-old").glob("*.jsonl")):
        path.unlink()
    _scan(world)
    record = gone_guard.read_record(world.state)
    assert record["count"] == 5 and len(record["ids"]) == 2 and record["overflow"] == 3
    verdict = check_transcripts_unprotected(world.state)
    assert verdict.params["count"] == 5 and verdict.params["more"] == 3
    assert verdict.detail_key == HK.DETAIL_TRANSCRIPTS_GONE_UNPROTECTED_MORE


def test_a_recorded_conversation_is_not_asked_of_the_vault_on_every_scan(world, monkeypatch):
    asked: List[str] = []

    class _Counting(_Vault):
        def files(self, conversation_id: str):
            asked.append(conversation_id)
            return super().files(conversation_id)

    fb.register("t", _Counting(held=[B]))
    _scan(world)
    (world.corpus / "-old" / f"{A}.jsonl").unlink()
    _scan(world)
    assert asked == [A]
    _scan(world)
    _scan(world)
    assert asked == [A]
    monkeypatch.setattr(gone_guard, "RECHECK_SECONDS", 0.0)
    _scan(world)
    assert asked == [A, A]


def test_a_pending_removal_survives_a_plugin_restart(world):
    _scan(world)
    fb.begin_boot()
    try:
        (world.corpus / "-old" / f"{A}.jsonl").unlink()
        _scan(world)
    finally:
        fb.end_boot()
    assert A in gone_guard.read_record(world.state)["pending"]
    _scan(world)
    assert A in gone_guard.read_record(world.state)["pending"]
    fb.register("t", _Vault(held=[B]))
    _scan(world)
    assert check_transcripts_unprotected(world.state).state == FIRING
