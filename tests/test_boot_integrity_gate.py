
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bgate_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bgate_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import db_integrity_gate as gate
from src.core.db import connect, db_path_for
from src.core.db_integrity import ENABLE_ENV, latest_path, read_verdict
from src.core.db_integrity_status import classify_record
from src.core.db_migration import ensure_db_migrated
from src.core.db_state import STATUS_DEGRADED_DB_UNREADABLE, STATUS_OK

APP_VERSION = "0.0.0-test"




@pytest.fixture
def checker_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLE_ENV, "1")


def _walk_counter(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    seen: List[str] = []
    real = gate.integrity_check

    def _counting(conn: sqlite3.Connection) -> str:
        verdict = real(conn)
        seen.append(verdict)
        return verdict

    monkeypatch.setattr(gate, "integrity_check", _counting, raising=True)
    return seen


def _built_state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for _ in range(2):
        result = ensure_db_migrated(state_dir, 4, APP_VERSION)
        assert result.status == STATUS_OK, result.message
    bound = read_verdict(state_dir)
    assert bound and bound.get("install_id"), "the artifact never bound"
    return state_dir


def _rewrite_artifact(state_dir: Path, **changes: Any) -> Dict[str, Any]:
    path = latest_path(state_dir)
    record = json.loads(path.read_text())
    record.update(changes)
    path.write_text(json.dumps(record, indent=2, sort_keys=True))
    return record


def _stamp(seconds_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.isoformat().replace("+00:00", "Z")


def _corrupt(db_path: Path) -> None:
    seed = sqlite3.connect(str(db_path))
    try:
        seed.execute("CREATE TABLE gate_probe(id INTEGER PRIMARY KEY, v TEXT)")
        seed.execute("CREATE INDEX gate_probe_v ON gate_probe(v)")
        seed.executemany(
            "INSERT INTO gate_probe(v) VALUES(?)",
            [("x" * 180 + str(i),) for i in range(4000)],
        )
        seed.commit()
        seed.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        seed.execute("PRAGMA journal_mode=DELETE")
        seed.commit()
    finally:
        seed.close()
    page_size = 4096
    pages = db_path.stat().st_size // page_size
    assert pages > 40, "the probe table did not make the file big enough"
    with open(db_path, "r+b") as handle:
        handle.seek(page_size * (pages - 5) + 1000)
        handle.write(b"\x00\xff\x00\xff")


def _sound_record(db_path: Path) -> Dict[str, Any]:
    return {
        "status": "ok",
        "finished_at": _stamp(60),
        "detail": None,
        "db_path": str(db_path),
        "install_id": "install-abc",
        "db_size_bytes": 1000,
        "source": "scheduled",
    }


def _decide(record: Optional[Dict[str, Any]], **over: Any) -> Any:
    db_path = over.pop("db_path", Path("/s/cloude.db"))
    return gate.resolve_boot_integrity(
        enabled=over.pop("enabled", True),
        record=record,
        reading=classify_record(record),
        pair_verdict=over.pop("pair_verdict", "ok"),
        pair_reason=over.pop("pair_reason", "both databases verified"),
        db_path=db_path,
        live_install_id=over.pop("live_install_id", "install-abc"),
        live_size_bytes=over.pop("live_size_bytes", 1000),
    )




def test_a_refused_cache_still_catches_a_corrupt_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _corrupt(db_path_for(state_dir))
    _rewrite_artifact(
        state_dir,
        status="ok",
        detail=None,
        finished_at=_stamp(30),
        install_id="some-other-install",
    )
    calls = _walk_counter(monkeypatch)

    result = ensure_db_migrated(state_dir, 4, APP_VERSION)

    assert calls, "the gate trusted a verdict taken on another install"
    assert result.status == STATUS_DEGRADED_DB_UNREADABLE
    assert "integrity_check" in (result.detail or "")


def test_a_skip_really_skips_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    before = read_verdict(state_dir)
    assert before is not None
    _corrupt(db_path_for(state_dir))
    _rewrite_artifact(state_dir, finished_at=_stamp(30))
    calls = _walk_counter(monkeypatch)

    result = ensure_db_migrated(state_dir, 4, APP_VERSION)

    assert calls == [], "the cached ok verdict was not used"
    assert result.status == STATUS_OK




def _assert_walked(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _walk_counter(monkeypatch)
    result = ensure_db_migrated(state_dir, 4, APP_VERSION)
    assert result.status == STATUS_OK, result.message
    assert calls, "the gate skipped the pragma when it had to run it"


def test_a_missing_artifact_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    os.replace(latest_path(state_dir), tmp_path / "moved-away.json")
    _assert_walked(state_dir, monkeypatch)


def test_a_truncated_artifact_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    text = latest_path(state_dir).read_text()
    latest_path(state_dir).write_text(text[: len(text) // 2])
    _assert_walked(state_dir, monkeypatch)


def test_a_malformed_artifact_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    latest_path(state_dir).write_text("[not, an, object")
    _assert_walked(state_dir, monkeypatch)


def test_an_unparseable_stamp_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, finished_at="the day before yesterday")
    _assert_walked(state_dir, monkeypatch)


def test_a_future_stamp_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, finished_at=_stamp(-3600))
    _assert_walked(state_dir, monkeypatch)


def test_a_stale_verdict_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, finished_at=_stamp(4 * 24 * 60 * 60))
    _assert_walked(state_dir, monkeypatch)


def test_a_recorded_failure_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(
        state_dir, status="failed", detail="page 3 is never used",
        finished_at=_stamp(30),
    )
    _assert_walked(state_dir, monkeypatch)


def test_a_cancelled_run_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, status="cancelled", finished_at=_stamp(30))
    _assert_walked(state_dir, monkeypatch)


def test_a_verdict_for_another_path_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, db_path="/somewhere/else/cloude.db")
    _assert_walked(state_dir, monkeypatch)


def test_a_verdict_without_an_install_id_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, install_id=None)
    _assert_walked(state_dir, monkeypatch)


def test_a_verdict_for_another_install_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, install_id="a-different-install")
    _assert_walked(state_dir, monkeypatch)


def test_a_database_that_shrank_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, db_size_bytes=10 * 1024 * 1024 * 1024)
    _assert_walked(state_dir, monkeypatch)


def test_a_disabled_checker_runs_the_pragma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _rewrite_artifact(state_dir, finished_at=_stamp(30))
    monkeypatch.setenv(ENABLE_ENV, "0")
    _assert_walked(state_dir, monkeypatch)




def test_exactly_one_rung_skips() -> None:
    assert gate.SKIP_CACHED_OK not in gate.RUN_RUNGS
    assert len(set(gate.RUN_RUNGS)) == len(gate.RUN_RUNGS) == 11


def test_the_sound_record_is_the_only_one_that_skips() -> None:
    decision = _decide(_sound_record(Path("/s/cloude.db")),
                       db_path=Path("/s/cloude.db"))
    assert decision.skip_pragma is True
    assert decision.rung == gate.SKIP_CACHED_OK


@pytest.mark.parametrize(
    ("changes", "expected_rung"),
    [
        ({"enabled": False}, gate.RUN_CHECKER_DISABLED),
        ({"status": "failed"}, gate.RUN_VERDICT_FAILED),
        ({"status": "cancelled"}, gate.RUN_VERDICT_CANNOT_DETERMINE),
        ({"status": "cannot_determine"}, gate.RUN_VERDICT_CANNOT_DETERMINE),
        ({"finished_at": "not a date"}, gate.RUN_FRESHNESS_CANNOT_DETERMINE),
        ({"db_path": "/elsewhere/cloude.db"}, gate.RUN_DB_PATH_MISMATCH),
        ({"install_id": None}, gate.RUN_INSTALL_ID_UNRECORDED),
        ({"install_id": ""}, gate.RUN_INSTALL_ID_UNRECORDED),
        ({"install_id": "other"}, gate.RUN_INSTALL_ID_MISMATCH),
        ({"live_install_id": None}, gate.RUN_INSTALL_ID_MISMATCH),
        ({"db_size_bytes": None}, gate.RUN_DB_SHRANK),
        ({"db_size_bytes": 5000}, gate.RUN_DB_SHRANK),
        ({"live_size_bytes": None}, gate.RUN_DB_SHRANK),
        ({"live_size_bytes": 999}, gate.RUN_DB_SHRANK),
    ],
)
def test_each_departure_from_sound_refuses(
    changes: Dict[str, Any], expected_rung: str,
) -> None:
    db_path = Path("/s/cloude.db")
    record = _sound_record(db_path)
    over: Dict[str, Any] = {"db_path": db_path}
    for key, value in changes.items():
        if key in {"enabled", "live_install_id", "live_size_bytes"}:
            over[key] = value
        else:
            record[key] = value
    decision = _decide(record, **over)
    assert decision.skip_pragma is False
    assert decision.rung == expected_rung
    assert decision.reason


def test_a_missing_record_refuses() -> None:
    decision = _decide(None)
    assert decision.skip_pragma is False
    assert decision.rung == gate.RUN_NEVER_RAN


def test_a_stale_record_refuses() -> None:
    db_path = Path("/s/cloude.db")
    record = _sound_record(db_path)
    record["finished_at"] = _stamp(4 * 24 * 60 * 60)
    decision = _decide(record, db_path=db_path)
    assert decision.skip_pragma is False
    assert decision.rung == gate.RUN_STALE


def test_the_freshness_window_is_two_check_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUDE_DB_INTEGRITY_CHECK_INTERVAL", "3600")
    db_path = Path("/s/cloude.db")
    record = _sound_record(db_path)
    record["finished_at"] = _stamp(3 * 3600)
    assert _decide(record, db_path=db_path).rung == gate.RUN_STALE
    record["finished_at"] = _stamp(1800)
    assert _decide(record, db_path=db_path).skip_pragma is True




def test_a_boot_run_check_publishes_its_verdict(
    tmp_path: Path, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    record = read_verdict(state_dir)

    assert record is not None
    assert record["status"] == "ok"
    assert record["source"] == "boot"
    assert record["install_id"]
    assert isinstance(record["db_size_bytes"], int)


def test_a_fresh_install_takes_two_boots_to_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    assert ensure_db_migrated(state_dir, 4, APP_VERSION).status == STATUS_OK
    first = read_verdict(state_dir)
    assert first is not None and first["install_id"] is None

    assert ensure_db_migrated(state_dir, 4, APP_VERSION).status == STATUS_OK
    second = read_verdict(state_dir)
    assert second is not None and second["install_id"]

    calls = _walk_counter(monkeypatch)
    assert ensure_db_migrated(state_dir, 4, APP_VERSION).status == STATUS_OK
    assert calls == [], "the third boot should have stood on the second's work"


def test_the_published_install_id_is_the_databases_own(
    tmp_path: Path, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    record = read_verdict(state_dir)
    assert record is not None
    with connect(db_path_for(state_dir), create=False) as conn:
        live = gate.live_install_id(conn)
    assert live and record["install_id"] == live




def _make_archive(state_dir: Path, *, damaged: bool) -> Path:
    archive = state_dir / "cloude-archive.db"
    seed = sqlite3.connect(str(archive))
    try:
        seed.execute("CREATE TABLE transcript_archives(id INTEGER PRIMARY KEY)")
        seed.commit()
    finally:
        seed.close()
    if damaged:
        _corrupt(archive)
    return archive


def test_the_pair_verdict_has_no_default() -> None:
    import inspect

    sig = inspect.signature(gate.resolve_boot_integrity)
    assert sig.parameters["pair_verdict"].default is inspect.Parameter.empty
    assert sig.parameters["pair_reason"].default is inspect.Parameter.empty


def test_a_record_that_does_not_cover_the_pair_refuses() -> None:
    decision = _decide(
        _sound_record(Path("/s/cloude.db")),
        db_path=Path("/s/cloude.db"),
        pair_verdict="cannot_determine",
        pair_reason="no verdict for the archive database",
    )
    assert decision.skip_pragma is False
    assert decision.rung == gate.RUN_PAIR_NOT_COVERED
    assert "archive" in decision.reason


def test_a_failed_archive_refuses_even_when_main_is_sound() -> None:
    decision = _decide(
        _sound_record(Path("/s/cloude.db")),
        db_path=Path("/s/cloude.db"),
        pair_verdict="failed",
        pair_reason="the archive database failed its integrity check",
    )
    assert decision.skip_pragma is False
    assert decision.rung == gate.RUN_PAIR_NOT_COVERED


def test_a_sound_pair_is_still_allowed_to_skip() -> None:
    decision = _decide(
        _sound_record(Path("/s/cloude.db")), db_path=Path("/s/cloude.db"),
    )
    assert decision.skip_pragma is True
    assert decision.rung == gate.SKIP_CACHED_OK


def test_a_stray_legacy_archive_file_is_neither_opened_nor_expected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker_on: None,
) -> None:
    state_dir = _built_state_dir(tmp_path)
    _make_archive(state_dir, damaged=True)
    _rewrite_artifact(state_dir, finished_at=_stamp(30))

    result = ensure_db_migrated(state_dir, 4, APP_VERSION)

    assert result.status == STATUS_OK, result.message
    record = read_verdict(state_dir)
    assert record is not None
    roles = {p.get("role"): p.get("status") for p in record.get("databases", [])}
    assert roles == {"state": "ok"}, roles
