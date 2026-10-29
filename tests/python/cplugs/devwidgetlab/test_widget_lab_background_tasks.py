
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.cplugs.devwidgetlab import matrix
from src.cplugs.devwidgetlab.drafts import create, preview, service, store


def _draft(tmp_path: Path) -> tuple[Path, Path]:
    storage = tmp_path / "s"
    made = create.create_new(storage, "Pulse board", "shows a pulse", ["home"], ["small"], "tools")
    return storage, storage / "drafts" / made["slug"]


def test_starting_a_build_does_its_blocking_preparation_off_the_event_loop(tmp_path: Path, monkeypatch) -> None:
    storage, folder = _draft(tmp_path)
    seen: dict[str, Any] = {}
    real = preview.prepare_build

    def spy(*args: Any) -> Any:
        seen["prepare"] = threading.get_ident()
        return real(*args)

    monkeypatch.setattr(preview, "require_buildable", lambda s: store.REPO)
    monkeypatch.setattr(preview, "prepare_build", spy)
    monkeypatch.setattr(preview, "_run", lambda f, r: asyncio.sleep(0))

    async def scenario() -> None:
        seen["loop"] = threading.get_ident()
        assert (await service.build_draft(storage, folder.name))["state"] == "building"
        await preview._job["task"]

    asyncio.run(scenario())
    assert seen["prepare"] != seen["loop"]


@pytest.mark.parametrize("broken", ["spawn", "mkdir"])
def test_a_build_task_that_cannot_start_records_failed(tmp_path: Path, monkeypatch, broken: str) -> None:
    storage, folder = _draft(tmp_path)
    (folder / store.BUILD_FOLDER).mkdir(exist_ok=True)
    monkeypatch.setattr(preview, "build_argv", lambda repo: ["vite"])

    async def refuse(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("vite")

    if broken == "spawn":
        monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
        monkeypatch.setattr(store, "head_sha", lambda repo: "abc")
    else:
        monkeypatch.setattr(store, "head_sha", lambda repo: (_ for _ in ()).throw(OSError("no git")))
    asyncio.run(preview._run(folder, store.REPO))
    build = store.read_build(folder)
    assert build["state"] == "failed" and ("vite" in build["error"] or "no git" in build["error"])


def test_a_build_task_for_a_vanished_folder_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    gone = tmp_path / "drafts" / "gone"

    async def refuse(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("x")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
    monkeypatch.setattr(store, "head_sha", lambda repo: "")
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: (_ for _ in ()).throw(OSError("gone")))
    asyncio.run(preview._run(gone, store.REPO))
    assert not gone.exists()


def test_a_matrix_run_that_cannot_spawn_exits_two(monkeypatch) -> None:
    monkeypatch.setattr(matrix, "_job", {"task": None, "started": None, "exit": None, "reason": ""})

    async def refuse(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("python3")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
    asyncio.run(matrix._run(["python3"]))
    assert matrix._job["exit"] == 2
