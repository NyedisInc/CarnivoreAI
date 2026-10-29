
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.crate_import import hooks as hk
from src.core.crate_import.model import ImportRequest
from tests.python.crate_import.test_import_collisions import plan_of
from tests.python.crate_import.test_import_same_path import Faults, rows_of, run, seeded, world

ORPHAN = "orphan-conv-0001"


def orphan_files(root: Path) -> list:
    return sorted(root.rglob(f"{ORPHAN}.jsonl"))


def test_the_preview_counts_an_orphan_conversation_as_written(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"], plan["blockers"]
    by_id = {c["id"]: c for c in plan["conversations"]}
    assert by_id[ORPHAN]["class"] == "write" and "reason" not in by_id[ORPHAN]
    assert not any(n["what"].startswith("files:orphan_transcript") for n in plan["not_restored"])


def test_a_restore_places_the_orphan_transcript_and_makes_no_session_row(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    source = orphan_files(Path(crate.world.home))
    assert len(source) == 1
    receipt = run(crate, install)
    placed = orphan_files(install.claude)
    assert len(placed) == 1 and placed[0].read_bytes() == source[0].read_bytes()
    assert {c["id"]: c["class"] for c in receipt.conversations}[ORPHAN] == "write"
    assert rows_of(install, "SELECT 1 FROM sessions WHERE claude_session_uuid = ?", ORPHAN) == []
    again = run(crate, install)
    assert orphan_files(install.claude) == placed and {c["id"]: c["class"] for c in again.conversations}[ORPHAN] == "present"


@pytest.mark.parametrize("at", [hk.CP_AFTER_FILES, hk.CP_BEFORE_COMMIT])
def test_an_undo_removes_the_orphan_transcript_the_import_wrote(tmp_path: Path, at: str) -> None:
    crate, install = seeded(tmp_path)
    before = world(install)
    hooks = Faults(at, RuntimeError("injected"))
    with pytest.raises(RuntimeError, match="injected"):
        run(crate, install, hooks)
    assert any(ORPHAN in str(e) for e in hooks.log), "the orphan file was logged for undo"
    assert orphan_files(install.claude) == [] and world(install) == before
