
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from src.cplugs.devwidgetlab.drafts import checkout, create, preview, service, store
from src.cplugs.sdk import app_info
from tests.python.cplugs.devwidgetlab.test_widget_lab_source_checkout import _checkout, _signing, _worktree, installed, no_auto_pick  # noqa: F401


def _commit(root: Path, name: str) -> str:
    (root / name).write_text(name)
    subprocess.run(["git", "-C", str(root), "add", name], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", name], check=True, capture_output=True)
    return store.head_sha(root)


def _build(storage: Path, slug: str) -> None:

    async def run() -> None:
        preview.start_build(storage, slug)
        await preview._job["task"]

    asyncio.run(run())


def test_the_servers_own_checkout_outranks_the_auto_pick(installed, monkeypatch, tmp_path: Path) -> None:  # noqa: F811
    storage, main = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(main))
    own = _checkout(tmp_path / "running-checkout")
    monkeypatch.setattr(checkout, "own_tree", lambda: own)
    assert checkout.resolve(storage) == own
    assert checkout.status(storage)["origin"] == "own_tree"


def test_a_worktree_at_the_running_apps_commit_is_picked_before_the_main_checkout(installed, monkeypatch, tmp_path: Path) -> None:  # noqa: F811
    storage, main = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(main))
    built_from = _worktree(main, "try-line", tmp_path / "try-build")
    sha = _commit(built_from, "only-on-the-try-line.txt")
    monkeypatch.setattr(app_info, "app_version", lambda: f"1.16.2-try.joe-line.g{sha[:7]}")
    assert checkout.app_sha() == sha[:7]
    assert checkout.auto_pick() == built_from and checkout.resolve(storage) == built_from


def test_a_build_at_another_commit_is_stale_shown_beside_the_apps_and_rebuilt_when_the_lab_opens_it(installed, monkeypatch) -> None:  # noqa: F811
    storage, repo = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(repo))
    monkeypatch.setattr(app_info, "app_version", lambda: "1.16.2-try.joe-line.gdbea280")
    create.create_new(storage, "Pulse board", "x", ["home"], ["small"], "tools")
    _build(storage, "pulse-board")
    folder = storage / "drafts" / "pulse-board"
    first = store.summary(folder)
    assert first["build_stale"] is False and first["code"] == {"app": "dbea280", "build": store.head_sha(repo), "source": store.head_sha(repo)}
    assert store.read_build(folder)["root"] == str(repo)

    moved = _commit(repo, "the-app-moved-on.txt")
    stale = store.summary(folder)
    assert stale["build_stale"] is True and stale["code"]["build"] != moved and stale["code"]["source"] == moved

    async def open_it() -> dict:
        answer = await service.open_page(storage, "pulse-board")
        await preview._job["task"]
        return answer

    answer = asyncio.run(open_it())
    assert answer["rebuild"] is True and answer["path"].endswith("/index.html")
    rebuilt = store.summary(folder)
    assert rebuilt["build"]["state"] == "built" and rebuilt["code"]["build"] == moved and rebuilt["build_stale"] is False
    assert asyncio.run(service.open_page(storage, "pulse-board"))["rebuild"] is False
