
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from scripts.crate import flows
from scripts.crate.errors import BlockedError
from tests.python.cplugs.crate.api_world import stop_runner
from tests.python.crate_headless.test_headless_cycle import exported_and_sent, logged_files, relocated
from tests.python.crate_headless.world import TwoInstalls


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def tree(root: Path) -> List[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.exists() else []


def test_same_paths_on_a_foreign_crate_is_refused_with_the_fix_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    sent = exported_and_sent(w, tmp_path)
    before = (tree(w.install.projects), tree(w.install.claude), tree(w.install.codex))

    with pytest.raises(BlockedError) as refused:
        flows.restore_crate(w.client_b, sent["name"])
    assert refused.value.exit_code == 5
    assert [b["code"] for b in refused.value.blockers] == ["relocate_required"]
    text = str(refused.value)
    assert "nothing was written" in text and "--relocate ROOT" in text and str(w.install.projects / "Proj One") in text

    assert w.b_counts() == {"sessions": 0, "projects": 0}
    assert w.client_b.imports() == {"imports": []}
    assert not (w.b.env.work / "imports").exists() or list((w.b.env.work / "imports").iterdir()) == []
    assert (tree(w.install.projects), tree(w.install.claude), tree(w.install.codex)) == before


def test_a_differing_local_file_blocks_as_a_conflict_and_skip_conflicts_keeps_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    sent = exported_and_sent(w, tmp_path)
    first = flows.restore_crate(w.client_b, sent["name"], relocate=relocated(w))
    placed = [Path(e["path"]) for e in logged_files(w, first["import_id"])]
    flows.undo_import(w.client_b, first["import_id"])
    assert w.b_counts() == {"sessions": 0, "projects": 0}
    local = b"local bytes that are not the crate's\n"
    for path in placed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(local)

    with pytest.raises(BlockedError) as refused:
        flows.restore_crate(w.client_b, sent["name"], relocate=relocated(w))
    assert {b["code"] for b in refused.value.blockers} == {"conflict"}
    assert "--skip-conflicts" in str(refused.value)
    assert w.b_counts() == {"sessions": 0, "projects": 0}
    assert all(p.read_bytes() == local for p in placed)

    kept = flows.restore_crate(w.client_b, sent["name"], relocate=relocated(w), skip_conflicts=True)
    assert kept["receipt"]["state"] in ("done", "done_with_warnings")
    assert all(p.read_bytes() == local for p in placed)


def test_blockers_text_tells_the_project_choice_fix() -> None:
    plan = {"blockers": [{"code": "project_choice_needed", "detail": ""}, {"code": "wrong_key", "detail": "no"}]}
    lines = flows.blockers_text(plan).splitlines()
    assert lines[0].startswith("project_choice_needed:") and "--target-project ID" in lines[0]
    assert lines[1] == "wrong_key: no"
