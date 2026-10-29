
from __future__ import annotations

import ast
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

os.environ.setdefault(
    "DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_gatesd_wd_")
)
os.environ.setdefault(
    "LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_gatesd_logs_")
)
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import Settings
from src.config import state_paths
from src.core import db_integrity_gate as gate
from src.core.db_integrity import (
    ENABLE_ENV,
    SOURCE_SCHEDULED,
    latest_path,
    read_verdict,
    run_integrity_check_once,
)
from src.core.db_integrity_task import DatabaseIntegrityScheduler
from src.core.db_migration import ensure_db_migrated
from src.core.db_state import STATUS_OK
from src.core.db import db_path_for

APP_VERSION = "0.0.0-test"
CONFIG_VERSION = 4

SKIP_RUNG = gate.SKIP_CACHED_OK




def _settings_for(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    explicit: bool,
) -> Tuple[Settings, Path]:
    legacy_dir = tmp_path / "legacy_log_directory"
    legacy_dir.mkdir()
    monkeypatch.setenv(ENABLE_ENV, "1")

    kwargs: Dict[str, Any] = {
        "_env_file": None,
        "DEFAULT_WORKING_DIR": str(tmp_path / "wd"),
        "LOG_DIRECTORY": str(legacy_dir),
        "TOTP_SECRET": "testsecretnotreal",
        "JWT_SECRET": "testjwtnotreal",
    }
    if explicit:
        named = tmp_path / "named_state"
        named.mkdir()
        kwargs["CLOUDE_STATE_DIR"] = str(named)
    else:
        home = tmp_path / "home"
        (home / "Library" / "Application Support" / "Carnivore").mkdir(
            parents=True
        )
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.delenv("CLOUDE_STATE_DIR", raising=False)

    settings_obj = Settings(**kwargs)
    assert settings_obj.state_dir_is_explicit() is explicit
    return settings_obj, legacy_dir


def _run_the_daily_check(state_dir: Path) -> Dict[str, Any]:
    result = ensure_db_migrated(state_dir, CONFIG_VERSION, APP_VERSION)
    assert result.status == STATUS_OK, result.message

    record = run_integrity_check_once(state_dir)
    assert record["status"] == "ok", record
    assert record["source"] == SOURCE_SCHEDULED, (
        "this artifact was not written by the daily check"
    )
    assert record.get("install_id"), "the daily check published no install_id"

    on_disk = read_verdict(state_dir)
    assert on_disk == record, "the daily check's record is not what is on disk"
    return record


def _ask_the_gate(state_dir: Path) -> gate.BootIntegrityResult:
    conn = sqlite3.connect(str(db_path_for(state_dir)))
    try:
        return gate.boot_integrity_verdict(state_dir, conn)
    finally:
        conn.close()




@pytest.mark.parametrize("explicit", [True, False], ids=["explicit", "default"])
def test_the_gate_finds_the_artifact_the_daily_check_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    settings_obj, legacy_dir = _settings_for(
        tmp_path, monkeypatch, explicit=explicit
    )

    (legacy_dir / "db-integrity").mkdir()
    (legacy_dir / "db-integrity" / "latest.json").write_text("{}")

    writer_state_dir = settings_obj.get_state_dir()
    reader_state_dir = settings_obj.get_state_dir()

    assert writer_state_dir == reader_state_dir
    assert latest_path(writer_state_dir) == latest_path(reader_state_dir)
    assert legacy_dir not in latest_path(reader_state_dir).parents

    record = _run_the_daily_check(writer_state_dir)
    assert latest_path(writer_state_dir).exists()

    result = _ask_the_gate(reader_state_dir)

    assert result.skipped is True, (
        f"the gate did not stand on the cached verdict: rung={result.rung} "
        f"reason={result.reason}"
    )
    assert result.rung == SKIP_RUNG
    assert result.verdict == "ok"
    assert result.duration_seconds == 0.0
    assert read_verdict(reader_state_dir)["finished_at"] == record["finished_at"]


def test_the_scheduler_writes_where_the_gate_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_obj, _legacy = _settings_for(tmp_path, monkeypatch, explicit=True)
    scheduler = DatabaseIntegrityScheduler(settings_obj.get_state_dir())

    assert scheduler.state_dir == settings_obj.get_state_dir()
    assert latest_path(scheduler.state_dir) == latest_path(
        settings_obj.get_state_dir()
    )

    _run_the_daily_check(scheduler.state_dir)
    assert _ask_the_gate(settings_obj.get_state_dir()).skipped is True




def test_a_reader_pointed_elsewhere_does_not_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_obj, _legacy = _settings_for(tmp_path, monkeypatch, explicit=True)
    written_to = settings_obj.get_state_dir()
    _run_the_daily_check(written_to)

    elsewhere = tmp_path / "somewhere_else"
    elsewhere.mkdir()
    for _ in range(2):
        ensure_db_migrated(elsewhere, CONFIG_VERSION, APP_VERSION)
    (elsewhere / "db-integrity" / "latest.json").unlink()

    result = _ask_the_gate(elsewhere)

    assert result.skipped is False
    assert result.rung == gate.RUN_NEVER_RAN, (
        "a gate looking in the wrong directory must report that it found "
        f"nothing, not {result.rung}"
    )




def _first_arg_source(tree: ast.AST, callee: str) -> Optional[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = (
            func.attr if isinstance(func, ast.Attribute)
            else func.id if isinstance(func, ast.Name)
            else None
        )
        if name == callee:
            return ast.unparse(node.args[0])
    return None


def test_the_analyser_can_tell_two_derivations_apart() -> None:
    agreeing = ast.parse(
        "ensure_db_migrated(settings.get_state_dir(), 4, v)\n"
        "DatabaseIntegrityScheduler(settings.get_state_dir())\n"
    )
    assert _first_arg_source(agreeing, "ensure_db_migrated") == (
        _first_arg_source(agreeing, "DatabaseIntegrityScheduler")
    )

    drifted = ast.parse(
        "ensure_db_migrated(settings.get_state_dir(), 4, v)\n"
        "DatabaseIntegrityScheduler(Path(os.environ['CLOUDE_STATE_DIR']))\n"
    )
    assert _first_arg_source(drifted, "ensure_db_migrated") != (
        _first_arg_source(drifted, "DatabaseIntegrityScheduler")
    )
    assert _first_arg_source(drifted, "not_called_anywhere") is None


def test_main_derives_one_state_dir_for_both_sites() -> None:
    boot_dir = Path(__file__).resolve().parents[1] / "src" / "core" / "boot"

    reader = _first_arg_source(ast.parse((boot_dir / "config_chain.py").read_text()), "ensure_db_migrated")
    writer = _first_arg_source(ast.parse((boot_dir / "schedulers.py").read_text()), "DatabaseIntegrityScheduler")

    assert reader == "settings.get_state_dir()", (
        f"the boot gate's state dir is derived as {reader!r}"
    )
    assert writer == "settings.get_state_dir()", (
        f"the daily check's state dir is derived as {writer!r}"
    )
    assert reader == writer


def test_the_artifact_never_goes_through_the_name_keyed_pin(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    pins: Dict[tuple, Any] = {}
    state_dir = Path("/nonexistent/state")
    legacy = Path("/nonexistent/legacy")

    pinned_names: List[str] = [
        "refresh_tokens.db", "session_metadata.json",
        "pinned_themes.json", "unread_state.json",
    ]
    assert latest_path(state_dir).name not in pinned_names
    assert latest_path(state_dir).parent != state_dir

    for name in pinned_names:
        resolved, _location = state_paths.state_file_pin(
            name, pins=pins, resolved_state_dir=state_dir,
            state_dir_override=str(state_dir), log_directory=str(legacy),
            state_dir_explicit=False,
        )
        assert resolved.name == name
        assert resolved != latest_path(state_dir)
