
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Set

import pytest
from fastapi.testclient import TestClient

from src import security_headers as sh
from src.api.auth import require_auth
from src.cplugs.devwidgetlab import errors
from src.cplugs.devwidgetlab.drafts import checkout, create, preview, service, ship, store
from src.cplugs.host import developer_mode
from src.cplugs.sdk import signed_links
from tests.python.cplugs.devwidgetlab.test_widget_lab_routes import BASE, host_app  # noqa: F401
from tests.python.cplugs.owner import turn_on

FAKE_VITE = """#!/bin/sh
printf '%s|%s' "$PWD" "$*" > "$LAB_DRAFT_DIR/build/vite-run.txt"
mkdir -p "$LAB_DRAFT_DIR/build/site"
echo '<html>draft</html>' > "$LAB_DRAFT_DIR/build/site/index.html"
"""


@pytest.fixture(autouse=True)
def no_auto_pick():
    checkout.forget_pick()
    checkout.bind_setting(None)
    yield
    checkout.forget_pick()
    checkout.bind_setting(None)


@pytest.fixture(autouse=True)
def _signing(monkeypatch):
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))


def _tree(root: Path) -> Set[Path]:
    return set(root.rglob("*"))


def _checkout(root: Path) -> Path:
    (root / "src" / "data").mkdir(parents=True)
    (root / "src" / "data" / "widgets.json").write_text(json.dumps({"schema": 1, "widgets": [{"id": "core.notes"}]}))
    (root / "src" / "data" / "widget-contracts.json").write_text(json.dumps({"schema": 1, "widgets": [{"id": "core.notes"}]}))
    (root / "scripts" / "widgets").mkdir(parents=True)
    (root / "scripts" / "widgets" / "capture_one.py").write_text("")
    web = root / "web"
    (web / "node_modules" / ".bin").mkdir(parents=True)
    (web / "package.json").write_text("{}")
    (web / "vite.widget-draft.config.ts").write_text("")
    vite = web / "node_modules" / ".bin" / "vite"
    vite.write_text(FAKE_VITE)
    vite.chmod(0o755)
    cell = web / "src" / "opscenter" / "cells" / "notes" / "Cell.svelte"
    cell.parent.mkdir(parents=True)
    cell.write_text("<p>old</p>")
    for args in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


@pytest.fixture
def installed(tmp_path: Path, monkeypatch):  # noqa: ANN201
    monkeypatch.setattr(store, "SCRIPT", tmp_path / "no-such" / "capture_one.py")
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(tmp_path / "nowhere"))
    checkout.bind_setting(None)
    storage_dir = tmp_path / "state" / "cplugs" / "devwidgetlab"
    storage_dir.mkdir(parents=True)
    repo = _checkout(tmp_path / "main-checkout")
    yield storage_dir, repo
    checkout.bind_setting(None)


def _worktree(main: Path, branch: str, where: Path) -> Path:
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", branch, str(where)], check=True, capture_output=True)
    return where


def test_with_nothing_found_the_drafts_are_greyed_out_and_point_to_settings(installed) -> None:
    storage, _ = installed
    gone = service.list_drafts(storage)
    assert gone["available"] is False and gone["reason"] == "no_checkout" and gone["source"] == {"root": "", "origin": "none", "setting": "", "problems": []}
    with pytest.raises(errors.NoCheckout, match="Settings"):
        create.create_new(storage, "Pulse board", "x", ["home"], ["small"], "tools")


def test_the_main_checkout_is_picked_by_itself_and_a_build_writes_only_into_the_plugins_storage(installed, monkeypatch) -> None:
    storage, repo = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(repo))
    assert checkout.status(storage) == {"root": str(repo), "origin": "auto", "setting": "", "problems": []}
    made = create.create_new(storage, "Pulse board", "x", ["home"], ["small"], "tools")
    assert str(repo.resolve()) in (storage / "drafts" / "pulse-board" / "BRIEF.md").read_text()
    assert service.list_drafts(storage)["available"] is True and made["base_sha"]
    before = _tree(repo)

    async def build() -> None:
        assert preview.start_build(storage, "pulse-board")["state"] == "building"
        await preview._job["task"]

    asyncio.run(build())
    folder = storage / "drafts" / "pulse-board"
    assert store.read_build(folder)["state"] == "built" and (folder / "build" / "site" / "index.html").is_file()
    cwd, args = (folder / "build" / "vite-run.txt").read_text().split("|")
    assert cwd == str((repo / "web").resolve()) and "--configLoader runner" in args
    assert _tree(repo) == before
    assert preview.resolve_file(storage, preview.mint_ticket("pulse-board")["path"].split("/")[-2], "index.html").is_file()


def test_a_main_checkout_that_does_not_validate_falls_to_a_worktree_the_running_branch_first_then_the_labs_own(installed, monkeypatch, tmp_path: Path) -> None:
    storage, main = installed
    (main / "web" / "vite.widget-draft.config.ts").unlink()
    subprocess.run(["git", "-C", str(main), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "drop config"], check=True, capture_output=True)
    other = _worktree(main, "other-work", tmp_path / "wt-other")
    lab = _worktree(main, "widget-lab-drafts", tmp_path / "wt-lab")
    for tree in (other, lab):
        (tree / "web" / "vite.widget-draft.config.ts").write_text("")
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(main))
    assert checkout.problems(main) and checkout.auto_pick() == lab
    checkout.forget_pick()
    monkeypatch.setattr(checkout, "own_tree", lambda: other)
    assert checkout.auto_pick() == other


def test_a_staging_worktree_is_never_picked(installed, monkeypatch, tmp_path: Path) -> None:
    storage, main = installed
    (main / "web" / "vite.widget-draft.config.ts").unlink()
    subprocess.run(["git", "-C", str(main), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "drop config"], check=True, capture_output=True)
    staging = _worktree(main, "staging-branch", tmp_path / "joe-staging")
    (staging / "web" / "vite.widget-draft.config.ts").write_text("")
    assert not checkout.problems(staging)
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(main))
    assert checkout.auto_pick() is None and checkout.resolve(storage) is None
    monkeypatch.setattr(checkout, "own_tree", lambda: staging)
    checkout.forget_pick()
    assert checkout.resolve(storage) is None


def test_the_setting_overrides_the_pick_and_a_broken_one_is_reported_not_used(installed, monkeypatch, tmp_path: Path) -> None:
    storage, repo = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(tmp_path / "nowhere"))
    checkout.bind_setting(lambda: str(repo))
    assert checkout.status(storage)["origin"] == "setting" and checkout.resolve(storage) == repo
    (repo / ".git").rename(repo / ".git-gone")
    status = checkout.status(storage)
    assert status["root"] == "" and status["setting"] == str(repo) and status["problems"] == ["it is not a git repository"]
    checkout.bind_setting(lambda: "relative/path")
    assert checkout.status(storage)["problems"] == ["it is not an absolute path"]
    checkout.bind_setting(lambda: (_ for _ in ()).throw(RuntimeError("host gone")))
    assert checkout.setting_value() == ""


def test_developer_mode_off_is_503_no_checkout_as_before(installed, monkeypatch) -> None:
    storage, repo = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(repo))
    create.create_new(storage, "Pulse board", "x", ["home"], ["small"], "tools")
    monkeypatch.setattr(developer_mode, "is_on", lambda: False)
    checkout.forget_pick()
    assert service.list_drafts(storage)["available"] is False
    for call in (lambda: service.get_draft(storage, "pulse-board"), lambda: preview.start_build(storage, "pulse-board"),
                 lambda: service.ship_plan(storage, "pulse-board"), lambda: create.create_new(storage, "Other one", "x", ["home"], ["small"], "tools")):
        with pytest.raises(errors.NoCheckout):
            call()
    ticket = preview.mint_ticket("pulse-board")["path"].split("/")[-2]
    with pytest.raises(errors.NoCheckout):
        preview.resolve_file(storage, ticket, "index.html")


def test_the_server_tree_is_used_when_it_is_a_checkout_and_no_pick_is_found(installed, monkeypatch) -> None:
    storage, _ = installed
    monkeypatch.setattr(store, "SCRIPT", store.REPO / "scripts" / "widgets" / "capture_one.py")
    monkeypatch.setattr(checkout, "auto_pick", lambda: None)
    monkeypatch.setattr(checkout, "NEVER_PICKED", frozenset())
    assert checkout.status(storage)["origin"] == "own_tree" and checkout.resolve(storage) == store.REPO


def test_there_is_no_route_to_save_a_source_folder_it_is_a_setting(host_app, installed) -> None:  # noqa: F811
    storage, repo = installed
    app, host = host_app
    turn_on(host, "devwidgetlab")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        assert client.put(f"{BASE}/drafts/source", json={"path": str(repo)}).status_code in (404, 405)
        listed = client.get(f"{BASE}/drafts").json()
        assert set(listed["source"]) == {"root", "origin", "setting", "problems"}


def test_the_plugin_declares_the_widget_lab_source_folder_setting_in_plain_words() -> None:
    import json  # noqa: PLC0415

    field = json.loads(Path("src/cplugs/devwidgetlab/cplug.json").read_text())["settings_schema"]["fields"][checkout.SETTING]
    assert field["kind"] == "string" and field["default"] == ""
    catalog = Path("web/src/cplugs/devwidgetlab/catalog.en.js").read_text()
    assert "'" + field["labelKey"] + "': 'widget lab source folder'" in catalog
    assert "'" + field["hintKey"] + "': 'the copy of the Carnivore code that drafts are built from'" in catalog



FRAME = f"{sh.DRAFT_HARNESS_PREFIX}some-ticket/index.html"


def _ancestors(path: str) -> str:
    return next(part.split(" ", 1)[1] for part in sh.csp_for_path(path).rstrip(";").split("; ") if part.startswith("frame-ancestors"))


def test_the_frame_header_is_self_only_while_developer_mode_and_the_plugin_are_on(host_app, monkeypatch) -> None:  # noqa: F811
    app, host = host_app
    assert _ancestors(FRAME) == "'none'"
    turn_on(host, "devwidgetlab")
    assert _ancestors(FRAME) == "'self'" and _ancestors(f"{sh.DRAFT_HARNESS_PREFIX}t/draft.js") == "'self'"
    monkeypatch.setattr(developer_mode, "is_on", lambda: False)
    assert _ancestors(FRAME) == "'none'"
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    for other in ("/api/v1/cplugs/devwidgetlab/drafts", "/api/v1/cplugs/devwidgetlab/draft-harness", "/api/v1/cplugs/devwidgetlab/draft-harnessx/t/i.html", "/static/index.html"):
        assert _ancestors(other) == "'none'", other


def test_the_frame_check_fails_closed_when_the_state_cannot_be_read(monkeypatch) -> None:
    def broken() -> bool:
        raise OSError("config unreadable")
    monkeypatch.setattr(developer_mode, "is_on", broken)
    assert sh.draft_framing_allowed() is False



def test_a_ship_lands_on_its_own_worktree_and_branch_and_never_touches_the_checkouts_branch_or_tree(installed, monkeypatch, tmp_path: Path) -> None:
    storage, repo = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(repo))
    create.create_revision(storage, "core.notes", "Notes denser", "tighter", {})
    folder = storage / "drafts" / "notes-denser"
    changed = folder / "files" / "web/src/opscenter/cells/notes/Cell.svelte"
    changed.parent.mkdir(parents=True)
    changed.write_text("<p>new</p>")
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    before = _tree(repo)
    plan = service.ship_plan(storage, "notes-denser")
    assert plan["repo"] == str(repo.resolve()) and "--apply" in plan["apply_command"] and plan["problems"] == []
    done = ship.apply_isolated(folder, repo.resolve(), tmp_path / "trash", tmp_path / "trees")
    assert done["branch"] == "widget-draft/notes-denser" and done["committed"] is True and done["sha"] != head
    assert (Path(done["worktree"]) / "web/src/opscenter/cells/notes/Cell.svelte").read_text() == "<p>new</p>"
    assert (repo / "web/src/opscenter/cells/notes/Cell.svelte").read_text() == "<p>old</p>"
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip() == head
    assert subprocess.run(["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True, check=True).stdout.strip() == "main"
    assert not subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip().replace("?? .git", "")
    assert not (folder.exists()) and Path(done["trashed"]).is_dir()
    assert {p for p in _tree(repo) if ".git" not in p.parts} == {p for p in before if ".git" not in p.parts}


def test_a_ship_refuses_a_worktree_inside_the_checkout_and_writes_nothing(installed, monkeypatch) -> None:
    storage, repo = installed
    monkeypatch.setattr(checkout, "MAIN_CHECKOUT", str(repo))
    create.create_revision(storage, "core.notes", "Notes denser", "tighter", {})
    folder = storage / "drafts" / "notes-denser"
    changed = folder / "files" / "web/src/opscenter/cells/notes/Cell.svelte"
    changed.parent.mkdir(parents=True)
    changed.write_text("<p>new</p>")
    before = _tree(repo)
    with pytest.raises(errors.DraftInvalid):
        ship.apply_isolated(folder, repo.resolve(), storage / "trash", repo / "inside")
    assert _tree(repo) == before and folder.exists()
