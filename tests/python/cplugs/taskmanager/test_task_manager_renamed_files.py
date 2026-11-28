
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from structlog.testing import capture_logs

from src.core.boot import plugins as boot_plugins
from src.core.core_owned_files.registry import is_core_owned
from src.core.crate_import import task_files_in
from src.core.work import folders
from src.core.work.importer import ready
from src.core.work.storage import WorkStorage
from src.plugins.taskmanager import files as item_files
from src.plugins.host import purge_guard, renamed_files
from src.plugins.sdk.renamed_files import handed_over, marker_name

PAIRS = {"huddle": "taskmanager"}
FILE_ID = "ab12cd34"
NAME = f"{FILE_ID}-a.png"
REL = f"files/7/{NAME}"
DATA = b"\x89PNG not really, but bytes"


@pytest.fixture(autouse=True)
def temp_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CARNIVORE_STATE_DIR", str(tmp_path))
    old = tmp_path / "cplugs" / "huddle"
    (old / "files" / "7").mkdir(parents=True)
    (old / "files" / "7" / NAME).write_bytes(DATA)
    (old / "huddle.db").write_bytes(b"legacy db bytes")
    return tmp_path


def old_dir(state: Path) -> Path:
    return state / "cplugs" / "huddle"


def new_files(state: Path) -> Path:
    return state / "cplugs" / "taskmanager" / "files"


def new_storage(state: Path) -> WorkStorage:
    storage = WorkStorage(state / "cplugs" / "taskmanager", state)
    ready.ensure(storage.db_path, state / "no-legacy-here", None)
    storage.previous_path = old_dir(state)
    return storage


def move(state: Path, sink: Optional[List[Dict[str, Any]]] = None, free: int = 10**12) -> renamed_files.FilesOutcome:
    raised = sink if sink is not None else []
    return renamed_files.migrate(state, PAIRS, free_space=lambda _s: free, alert=lambda key, **kw: raised.append({"key": key, **kw}))


def parts() -> str:
    return json.dumps({"files": [{"id": FILE_ID, "name": "a.png", "mime": "image/png", "size": len(DATA), "path": REL}]})


def test_the_move_publishes_a_verified_copy_and_the_message_file_serves_from_the_new_folder(temp_state: Path) -> None:
    assert move(temp_state).state == {"huddle": "moved"}
    assert (new_files(temp_state) / "7" / NAME).read_bytes() == DATA
    storage = new_storage(temp_state)
    assert item_files.locate(storage, 7, FILE_ID) == new_files(temp_state) / "7" / NAME
    assert item_files.stored_file(storage, REL) == new_files(temp_state) / "7" / NAME
    item_files.require_present(storage, parts())
    marker = json.loads((old_dir(temp_state) / "files" / marker_name("taskmanager")).read_text())
    assert marker["files"] == {f"7/{NAME}": hashlib.sha256(DATA).hexdigest()}
    assert (old_dir(temp_state) / "files" / "7" / NAME).read_bytes() == DATA
    assert (old_dir(temp_state) / "huddle.db").read_bytes() == b"legacy db bytes"
    assert not (temp_state / "cplugs" / "taskmanager" / renamed_files.MOVING_NAME).exists()


def test_a_rerun_is_a_no_op(temp_state: Path) -> None:
    move(temp_state)
    before = sorted(p.as_posix() for p in new_files(temp_state).rglob("*"))
    assert move(temp_state).state == {"huddle": "done"}
    assert sorted(p.as_posix() for p in new_files(temp_state).rglob("*")) == before


def test_a_failed_verify_publishes_nothing_and_the_next_boot_retries(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_copy = renamed_files.shutil.copy2

    def corrupt(src: Any, dst: Any, **kw: Any) -> None:
        real_copy(src, dst, **kw)
        Path(dst).write_bytes(b"corrupted")

    monkeypatch.setattr(renamed_files.shutil, "copy2", corrupt)
    with capture_logs() as logs:
        outcome = move(temp_state)
    assert outcome.state == {"huddle": "failed"} and outcome.failed
    assert any(e["event"] == "cplug_renamed_files_failed" and e["log_level"] == "error" for e in logs)
    assert not new_files(temp_state).exists()
    assert not (temp_state / "cplugs" / "taskmanager" / renamed_files.MOVING_NAME).exists()
    assert not (old_dir(temp_state) / "files" / marker_name("taskmanager")).exists()
    assert item_files.locate(new_storage(temp_state), 7, FILE_ID) == old_dir(temp_state) / "files" / "7" / NAME
    monkeypatch.setattr(renamed_files.shutil, "copy2", real_copy)
    assert move(temp_state).state == {"huddle": "moved"}


def test_an_existing_new_folder_is_merged_into_never_written_over(temp_state: Path) -> None:
    (new_files(temp_state) / "9").mkdir(parents=True)
    (new_files(temp_state) / "9" / "cd34ab12-other").write_bytes(b"x")
    clash = old_dir(temp_state) / "files" / "8" / "ef56ab78-c.txt"
    clash.parent.mkdir()
    clash.write_bytes(b"old bytes")
    (new_files(temp_state) / "8").mkdir()
    (new_files(temp_state) / "8" / clash.name).write_bytes(b"new bytes")
    with capture_logs() as logs:
        assert move(temp_state).state == {"huddle": "moved"}
    assert (new_files(temp_state) / "7" / NAME).read_bytes() == DATA
    assert (new_files(temp_state) / "9" / "cd34ab12-other").read_bytes() == b"x"
    assert (new_files(temp_state) / "8" / clash.name).read_bytes() == b"new bytes"
    assert any(e["event"] == "cplug_renamed_files_conflict" and e["files"] == 1 for e in logs)
    marker = json.loads((old_dir(temp_state) / "files" / marker_name("taskmanager")).read_text())
    assert set(marker["files"]) == {f"7/{NAME}"}


def test_no_space_then_an_upload_then_a_retry_ends_moved(temp_state: Path) -> None:
    assert move(temp_state, free=1024).state == {"huddle": "no_space"}
    upload = new_files(temp_state) / "8" / "ef56ab78-new.png"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"new")
    half = temp_state / "cplugs" / "taskmanager" / renamed_files.MOVING_NAME / "7"
    half.mkdir(parents=True)
    (half / NAME).write_bytes(b"half")
    assert move(temp_state).state == {"huddle": "moved"}
    assert (new_files(temp_state) / "7" / NAME).read_bytes() == DATA and upload.read_bytes() == b"new"
    assert not (temp_state / "cplugs" / "taskmanager" / renamed_files.MOVING_NAME).exists()
    assert move(temp_state).state == {"huddle": "done"}


def test_a_marker_whose_copy_went_missing_is_set_aside_and_the_move_runs_again(temp_state: Path) -> None:
    move(temp_state)
    renamed_files.shutil.rmtree(new_files(temp_state))
    upload = new_files(temp_state) / "8" / "ef56ab78-new.png"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"new")
    with capture_logs() as logs:
        assert move(temp_state).state == {"huddle": "moved"}
    assert any(e["event"] == "cplug_renamed_files_marker_stale" and e["log_level"] == "error" and e["lost"] == 1 for e in logs)
    stale = [p for p in (old_dir(temp_state) / "files").iterdir() if p.name.startswith(marker_name("taskmanager") + ".stale-")]
    assert len(stale) == 1 and (old_dir(temp_state) / "files" / marker_name("taskmanager")).is_file()
    assert item_files.locate(new_storage(temp_state), 7, FILE_ID) == new_files(temp_state) / "7" / NAME
    assert upload.read_bytes() == b"new"


def test_the_no_space_alert_is_resolved_once_the_files_move(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core import db
    from src.core.app_alerts import service

    db.db_path_for(temp_state).touch()
    resolved: List[str] = []
    monkeypatch.setattr(service, "resolve", lambda key, **_kw: resolved.append(key) or [])
    move(temp_state, free=1024)
    assert resolved == []
    move(temp_state)
    move(temp_state)
    assert resolved == ["plugin_files.no_space.taskmanager"] * 2


def test_a_started_line_names_the_bytes_before_the_copy(temp_state: Path) -> None:
    with capture_logs() as logs:
        move(temp_state)
    started = [e for e in logs if e["event"] == "cplug_renamed_files_started"]
    assert len(started) == 1 and started[0]["bytes"] == len(DATA) and started[0]["files"] == 1


def test_a_handed_over_name_matches_whatever_its_unicode_form(temp_state: Path) -> None:
    import unicodedata

    nfc, nfd = unicodedata.normalize("NFC", "ab12cd34-caf\u00e9.png"), unicodedata.normalize("NFD", "ab12cd34-caf\u00e9.png")
    new_files(temp_state).mkdir(parents=True)
    marker = old_dir(temp_state) / "files" / marker_name("taskmanager")
    marker.write_text(json.dumps({"format": 1, "files": {f"7/{nfd}": "0" * 64}}))
    assert handed_over(old_dir(temp_state) / "files", new_files(temp_state), old_dir(temp_state) / "files" / "7" / nfc)


def test_an_exact_copy_without_a_marker_is_adopted(temp_state: Path) -> None:
    (new_files(temp_state) / "7").mkdir(parents=True)
    (new_files(temp_state) / "7" / NAME).write_bytes(DATA)
    assert move(temp_state).state == {"huddle": "adopted"}
    assert (old_dir(temp_state) / "files" / marker_name("taskmanager")).is_file()


def test_too_little_room_skips_with_an_error_alert_and_does_not_fail(temp_state: Path) -> None:
    raised: List[Dict[str, Any]] = []
    with capture_logs() as logs:
        outcome = move(temp_state, raised, free=1024)
    assert outcome.state == {"huddle": "no_space"}
    assert not new_files(temp_state).exists() and not (temp_state / "cplugs" / "taskmanager").exists()
    assert len(raised) == 1 and raised[0]["severity"] == "error" and raised[0]["title_key"] == renamed_files.ALERT_TITLE
    assert any(e["event"] == "cplug_renamed_files_no_space" and e["log_level"] == "error" for e in logs)


def test_a_handed_over_file_removed_from_the_new_folder_is_not_served_from_the_old_copy(temp_state: Path) -> None:
    move(temp_state)
    (new_files(temp_state) / "7" / NAME).unlink()
    storage = new_storage(temp_state)
    with pytest.raises(Exception, match="no such file"):
        item_files.locate(storage, 7, FILE_ID)
    assert handed_over(old_dir(temp_state) / "files", new_files(temp_state), old_dir(temp_state) / "files" / "7" / NAME)
    later = old_dir(temp_state) / "files" / "7" / "cd34ab12-b.txt"
    later.write_bytes(b"b")
    assert item_files.locate(storage, 7, "cd34ab12") == later


def test_the_shipped_manifest_moves_the_old_folder(temp_state: Path) -> None:
    assert renamed_files.migrate(temp_state).state == {"huddle": "moved"}
    assert (temp_state / "cplugs" / "taskmanager").is_dir()
    assert renamed_files.migrate(temp_state).state == {"huddle": "done"}


def test_the_boot_step_runs_after_the_entry_carry() -> None:
    source = inspect.getsource(boot_plugins._run_one_time_migrations)
    assert source.index("migrate_renamed_entries(state_dir)") < source.index("migrate_renamed_files(state_dir)") < source.index("migrate_split_plugins(")


def test_every_other_reader_names_both_folders(temp_state: Path) -> None:
    from scripts.backup import targets

    assert targets.STATE_TREES == ("cplugs/taskmanager/files", "cplugs/huddle/files")
    for prefix in ("cplugs/huddle/files", "cplugs/taskmanager/files"):
        assert task_files_in._REL.match(f"{prefix}/7/{NAME}").groups() == ("7", NAME)
    assert task_files_in._REL.match(f"cplugs/task_manager/files/7/{NAME}") is None
    assert folders.archive_rel(f"cplugs/taskmanager/files/7/{NAME}") == f"cplugs/huddle/files/7/{NAME}"
    assert folders.archive_rel("cplugs/state.json") == "cplugs/state.json"
    assert is_core_owned("taskmanager", "huddle.db") and is_core_owned("huddle", "huddle.db")
    move(temp_state)
    previous = purge_guard.previous(temp_state / "cplugs" / "taskmanager", "huddle")
    plan = purge_guard.plan(previous, "huddle")
    assert old_dir(temp_state) / "huddle.db" in plan.kept and old_dir(temp_state) / "files" / "7" / NAME in plan.delete
