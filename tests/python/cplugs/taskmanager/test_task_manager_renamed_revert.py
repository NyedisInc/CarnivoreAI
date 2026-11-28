
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from src.plugins.host import renamed_files, renamed_files_revert as rv
from src.plugins.sdk.renamed_files import marker_name
from tests.python.cplugs.taskmanager.test_task_manager_renamed_files import (DATA, NAME, PAIRS, move, new_files, old_dir,  # noqa: F401
                                                                         temp_state)


def revert(state: Path, running: bool = False) -> renamed_files.FilesOutcome:
    return rv.revert(state, PAIRS, app_running=lambda: running)


def test_revert_removes_an_unchanged_copy_and_the_next_boot_moves_again(temp_state: Path) -> None:
    move(temp_state)
    assert revert(temp_state).state == {"huddle": "reverted"}
    assert not new_files(temp_state).exists()
    assert not (old_dir(temp_state) / "files" / marker_name("taskmanager")).exists()
    assert (old_dir(temp_state) / "files" / "7" / NAME).read_bytes() == DATA
    assert move(temp_state).state == {"huddle": "moved"}


@pytest.mark.parametrize("change", ["added", "changed"])
def test_revert_refuses_when_the_copy_holds_something_new(temp_state: Path, change: str) -> None:
    move(temp_state)
    if change == "added":
        (new_files(temp_state) / "8").mkdir()
        (new_files(temp_state) / "8" / "ef56ab78-new.png").write_bytes(b"new")
    else:
        (new_files(temp_state) / "7" / NAME).write_bytes(b"rewritten")
    with capture_logs() as logs:
        outcome = revert(temp_state)
    assert outcome.state == {"huddle": "kept"} and outcome.failed
    assert any(e["event"] == "cplug_renamed_files_revert_kept" for e in logs)
    assert (new_files(temp_state) / "7" / NAME).is_file()
    assert (old_dir(temp_state) / "files" / marker_name("taskmanager")).is_file()


def test_revert_refuses_while_the_app_is_running(temp_state: Path) -> None:
    move(temp_state)
    outcome = revert(temp_state, running=True)
    assert outcome.state == {"huddle": "app_running"} and outcome.failed
    assert (new_files(temp_state) / "7" / NAME).read_bytes() == DATA
    assert (old_dir(temp_state) / "files" / marker_name("taskmanager")).is_file()


def test_a_file_that_lands_after_the_first_look_is_never_deleted(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    move(temp_state)
    real_listing = renamed_files.listing
    late = new_files(temp_state) / "9" / "ef56ab78-late.png"

    def listing_then_upload(root: Path) -> Any:
        out = real_listing(root)
        if root == new_files(temp_state) and not late.exists():
            late.parent.mkdir()
            late.write_bytes(b"late")
        return out

    monkeypatch.setattr(renamed_files, "listing", listing_then_upload)
    outcome = revert(temp_state)
    assert outcome.state == {"huddle": "kept"} and outcome.failed
    assert late.read_bytes() == b"late" and (new_files(temp_state) / "7" / NAME).read_bytes() == DATA
    assert (old_dir(temp_state) / "files" / marker_name("taskmanager")).is_file()
    assert not (temp_state / "cplugs" / "taskmanager" / rv.REVERTING_NAME).exists()


def test_a_copy_that_only_lost_files_is_reverted_and_the_count_reported(temp_state: Path) -> None:
    second = old_dir(temp_state) / "files" / "7" / "cd34ab12-b.txt"
    second.write_bytes(b"b")
    move(temp_state)
    (new_files(temp_state) / "7" / second.name).unlink()
    outcome = revert(temp_state)
    assert outcome.state == {"huddle": "reverted"} and not outcome.failed
    assert outcome.removed == {"huddle": 1}
    assert not new_files(temp_state).exists()


def test_a_reverting_folder_left_by_a_crash_is_never_deleted(temp_state: Path) -> None:
    move(temp_state)
    left = temp_state / "cplugs" / "taskmanager" / rv.REVERTING_NAME
    left.mkdir()
    (left / "x").write_bytes(b"x")
    assert revert(temp_state).state == {"huddle": "failed"}
    assert (left / "x").read_bytes() == b"x" and (new_files(temp_state) / "7" / NAME).is_file()


def test_the_revert_command_uses_the_given_state_dir(temp_state: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    move(temp_state)
    monkeypatch.setattr(rv, "app_answers", lambda port: False)
    assert rv.main(["--state-dir", str(temp_state), "--pair", "huddle=taskmanager"]) == 0
    assert "huddle: reverted" in capsys.readouterr().out


def test_the_revert_command_refuses_while_the_port_answers(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    move(temp_state)
    monkeypatch.setattr(rv, "app_answers", lambda port: True)
    assert rv.main(["--state-dir", str(temp_state), "--pair", "huddle=taskmanager"]) == 1
    assert (new_files(temp_state) / "7" / NAME).is_file()
