
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from scripts.crate import flows
from src.core.blobcodec.place import sha256_file
from tests.python.cplugs.crate.api_world import stop_runner
from tests.python.crate_headless.test_headless_cli import HOSTS, run
from tests.python.crate_headless.world import TwoInstalls

PROJECT_FILES = {"src/app.py": b"print('one')\n", "README.md": b"# proj one\n", "docs/notes/a.txt": b"alpha\n" * 50}


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def world_with_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tuple[TwoInstalls, Path]:
    w = TwoInstalls(tmp_path, monkeypatch)
    for rel, data in PROJECT_FILES.items():
        path = Path(w.a.world.root1) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return w, w.install.projects / "Proj One"


def cycle(w: TwoInstalls, root: Path, *flags: str) -> Tuple[int, Dict[str, Any], str]:
    code, out, err = run(w, "cycle", *HOSTS, "project", w.a.world.root1, "--relocate", str(root), "--json", *flags)
    return code, json.loads(out), err


def restore_without_flags(w: TwoInstalls, tmp_path: Path, root: Path, *flags: str) -> Tuple[int, Dict[str, Any]]:
    exported = flows.export_crate(w.client_a, flows.export_body("project", w.a.world.root1, include_project_files=True))
    sent = flows.send_crate(w.client_a, w.client_b, exported["bundle_id"], workdir=tmp_path)
    code, out, _ = run(w, "restore", "--url", "http://b.invalid", sent["name"], "--relocate", str(root), "--json", *flags)
    return code, json.loads(out)


def carries(answer: Dict[str, Any]) -> List[str]:
    return sorted(h["carry"] for h in answer["verify"]["held_back"])


def memory_files(w: TwoInstalls) -> List[Path]:
    return sorted(w.install.claude.rglob("memory/MEMORY.md"))


def test_project_files_flag_restores_every_file_with_the_sources_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    code, answer, err = cycle(w, root, "--include-project-files")
    assert code == 0, err
    assert carries(answer) == ["instructions"] and answer["verify"]["ok"]
    for rel in PROJECT_FILES:
        source, placed = Path(w.a.world.root1) / rel, root / rel
        assert placed.is_file(), f"{rel} not restored under {root}"
        assert sha256_file(placed) == sha256_file(source), rel


def test_without_the_flag_the_files_are_held_back_reported_and_exit_is_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    code, restored = restore_without_flags(w, tmp_path, root)
    assert code == 0
    code, out, _ = run(w, "verify", "--url", "http://b.invalid", restored["import_id"], "--json")
    assert code == 0
    held = json.loads(out)["held_back"]
    assert sorted(h["carry"] for h in held) == ["instructions", "project_files"]
    assert {h["why"] for h in held} == {"instructions_held_back", "project_files_not_ticked"}
    assert not (root / "src" / "app.py").exists()


def test_held_back_is_a_line_in_the_text_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    code, restored = restore_without_flags(w, tmp_path, root)
    assert code == 0
    code, out, _ = run(w, "verify", "--url", "http://b.invalid", restored["import_id"])
    assert code == 0 and "held back" in out and "project_files_not_ticked" in out


def test_asking_for_a_carry_that_still_did_not_land_exits_7(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    code, restored = restore_without_flags(w, tmp_path, root)
    assert code == 0
    import_id = restored["import_id"]
    assert run(w, "verify", "--url", "http://b.invalid", import_id)[0] == 0
    code, out, _ = run(w, "verify", "--url", "http://b.invalid", import_id, "--include-project-files", "--json")
    assert code == 7
    assert "asked for project_files" in json.loads(out)["error"]["message"]


def test_a_forced_drop_of_the_opt_in_fails_the_cycle_with_exit_7(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    real = flows.import_body
    monkeypatch.setattr(flows, "import_body", lambda name, **kw: real(name, **{**kw, "options": flows.ImportOptions()}))
    code, answer, _ = cycle(w, root, "--include-project-files")
    assert code == 7 and answer["error"]["class"] == "VerifyError"
    assert "project_files_not_ticked" in answer["error"]["message"]


def test_memory_lands_under_memory_with_include_instructions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    code, answer, err = cycle(w, root, "--include-instructions")
    assert code == 0, err
    assert carries(answer) == []
    placed = memory_files(w)
    assert len(placed) == 1 and placed[0].read_text() == "# notes\n"


def test_memory_without_the_flag_is_held_back_and_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    code, answer, err = cycle(w, root)
    assert code == 0, err
    assert "instructions" in carries(answer)
    assert memory_files(w) == []


def test_relocate_is_refused_loudly_when_the_project_already_exists_on_the_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, root = world_with_files(tmp_path, monkeypatch)
    code, first, err = cycle(w, root, "--include-project-files")
    assert code == 0, err
    before = w.b_counts()
    elsewhere = w.install.projects / "Elsewhere"
    code, answer, _ = cycle(w, elsewhere, "--include-project-files")
    assert code == 5 and answer["error"]["class"] == "BlockedError"
    message = answer["error"]["message"]
    assert "relocate did not apply" in message and str(root) in message and "Nothing was written" in message
    assert not elsewhere.exists() and w.b_counts() == before
    assert first["restore"]["receipt"]["project"]["root"] == str(root)
