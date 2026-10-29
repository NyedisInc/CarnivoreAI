
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List

from src.cplugs.devwidgetlab import capture, matrix
from tests.python.cplugs.devwidgetlab.test_widget_lab_routes import REQUEST, FakeProc


def _tree(root: Path) -> set[Path]:
    return set(root.rglob("*"))


def test_a_capture_writes_only_under_the_labs_own_storage_folder(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    storage = state_dir / "cplugs" / "devwidgetlab"
    other = tmp_path / "elsewhere"
    other.mkdir()
    state_dir.mkdir(parents=True)
    seen: List[Any] = []

    async def spawn(*args: Any, **kwargs: Any):
        seen.append(args)
        return FakeProc(json.dumps({"ok": True, "failures": []}))

    monkeypatch.setattr(capture, "availability", lambda: {"available": True, "reason": ""})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    before = _tree(tmp_path)
    asyncio.run(capture.run_capture({**REQUEST, "scenario": '{"GET /x": 1}'}, storage))
    made = _tree(tmp_path) - before
    assert made, "the capture made no folder, so this proves nothing"
    assert all(path.is_relative_to(storage) or storage.is_relative_to(path) for path in made), made
    assert any(path.is_relative_to(storage / "captures") for path in made)
    assert not _tree(other)
    out = Path(seen[0][seen[0].index("--out") + 1])
    assert out.is_relative_to(storage / "captures")


def test_a_matrix_run_is_pointed_at_the_labs_own_storage_folder(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "state" / "cplugs" / "devwidgetlab"
    started: List[list[str]] = []

    async def noop(argv: list[str]) -> None:
        started.append(argv)

    monkeypatch.setattr(matrix, "availability", lambda: {"available": True, "reason": ""})
    monkeypatch.setattr(matrix, "_run", noop)

    async def go() -> None:
        matrix.start(storage)
        await asyncio.sleep(0)

    asyncio.run(go())
    out = Path(started[0][started[0].index("--out") + 1])
    assert out.is_relative_to(storage) and out == matrix.matrix_dir(storage)


def test_a_new_draft_is_written_only_under_the_labs_own_storage_folder(tmp_path: Path) -> None:
    from src.cplugs.devwidgetlab.drafts import create

    storage = tmp_path / "state" / "cplugs" / "devwidgetlab"
    other = tmp_path / "elsewhere"
    other.mkdir()
    before = _tree(tmp_path)
    made = create.create_new(storage, "Pulse board", "x", ["home"], ["small"], "tools")
    created = _tree(tmp_path) - before
    folder = storage / "drafts" / made["slug"]
    assert (folder / "draft.json").is_file(), "no draft record, so this proves nothing"
    assert all(path.is_relative_to(storage) or storage.is_relative_to(path) for path in created), created
    assert not _tree(other)
