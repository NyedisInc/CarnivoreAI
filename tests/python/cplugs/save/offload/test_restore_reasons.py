
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator

import pytest

from src.plugins.save.offload import constants as C
from src.plugins.save.offload import list_view, offload_routes, restore_routes
from src.plugins.save.offload.move import holding_root
from tests.python.cplugs.save.offload.fleet import ledger_of
from tests.python.cplugs.save.offload.test_restore_target_folder import CONV, LONG, SHORT, files_under, long_spelling, wire  # noqa: F401
from tests.python.cplugs.save.vault_helpers import World

LOCKED = "-Users-x-locked"


@pytest.fixture
def locked_folder(long_spelling: World) -> Iterator[Path]:
    bad = long_spelling.projects / LOCKED
    bad.mkdir()
    os.chmod(bad, 0)
    try:
        yield bad
    finally:
        os.chmod(bad, 0o700)


def held_files(world: World) -> list:
    return sorted(p.name for p in (holding_root(world.state) / CONV).rglob("*") if p.is_file())


def test_an_unreadable_project_folder_fails_a_remapped_restore_and_names_it(long_spelling: World, locked_folder: Path) -> None:
    shutil.rmtree(long_spelling.projects / LONG)
    [one] = restore_routes.run_restore(None, CONV, False).conversations
    assert (one.status, one.written, one.path) == ("failed", 0, str(locked_folder))
    assert str(locked_folder) in one.detail and "no transcript" not in one.detail
    assert files_under(long_spelling, SHORT) == {} and files_under(long_spelling, LONG) == {}


def test_a_projects_root_that_cannot_be_listed_fails_the_restore_and_names_it(long_spelling: World) -> None:
    shutil.rmtree(long_spelling.projects / LONG)
    os.chmod(long_spelling.projects, 0o300)
    try:
        [one] = restore_routes.run_restore(None, CONV, False).conversations
    finally:
        os.chmod(long_spelling.projects, 0o700)
    assert (one.status, one.written, one.path) == ("failed", 0, str(long_spelling.projects))
    assert files_under(long_spelling, SHORT) == {} and files_under(long_spelling, LONG) == {}


def test_an_offloaded_conversation_with_a_copy_elsewhere_keeps_its_row_with_the_reason(long_spelling: World) -> None:
    assert {c.status for c in offload_routes._run("S1", False).conversations} == {"offloaded"}
    stray = long_spelling.projects / "-Users-x-stray"
    stray.mkdir()
    (stray / f"{CONV}.jsonl").write_bytes(b'{"x":1}\n')
    [one] = restore_routes.run_restore("S1", None, False).conversations
    assert (one.status, one.path) == ("present_elsewhere", str(stray / f"{CONV}.jsonl"))
    entry = ledger_of(long_spelling).get(CONV)
    assert entry is not None and entry.state == C.STATE_CONFLICT
    assert (entry.error_code, entry.error_path) == ("present_elsewhere", one.path) and entry.error
    [row], _ = list_view.group_rows(ledger_of(long_spelling).read().values(), {}, {})
    assert (row.state, row.error_code, row.error_path) == (C.STATE_CONFLICT, "present_elsewhere", one.path)
    assert held_files(long_spelling) and files_under(long_spelling, SHORT) == {}


def test_an_offloaded_conversation_behind_an_unreadable_folder_keeps_its_row_as_failed(long_spelling: World, locked_folder: Path) -> None:
    offload_routes._run("S1", False)
    [one] = restore_routes.run_restore("S1", None, False).conversations
    assert one.status == "failed"
    entry = ledger_of(long_spelling).get(CONV)
    assert entry is not None and (entry.state, entry.error_path) == (C.STATE_FAILED, str(locked_folder)) and str(locked_folder) in entry.error
    assert held_files(long_spelling) and files_under(long_spelling, SHORT) == {}


def test_a_restore_that_keeps_the_recorded_folder_also_looks_elsewhere(long_spelling: World, monkeypatch: pytest.MonkeyPatch) -> None:
    wire(long_spelling, monkeypatch, None)
    shutil.move(str(long_spelling.projects / LONG), str(long_spelling.projects / SHORT))
    before = files_under(long_spelling, SHORT)
    [one] = restore_routes.run_restore(None, CONV, False).conversations
    assert (one.status, one.written) == ("present_elsewhere", 0)
    assert one.path == str(long_spelling.projects / SHORT / f"{CONV}.jsonl")
    assert files_under(long_spelling, LONG) == {} and files_under(long_spelling, SHORT) == before
