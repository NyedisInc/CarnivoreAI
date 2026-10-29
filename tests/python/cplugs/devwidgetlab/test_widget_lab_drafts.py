
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.devwidgetlab import errors
from src.cplugs.devwidgetlab.drafts import brief, create, preview, session, ship, starter, store
from src.cplugs.sdk import signed_links
from tests.python.cplugs.devwidgetlab.test_widget_lab_routes import BASE, host_app  # noqa: F401
from tests.python.cplugs.devwidgetlab.draft_helpers import fake_repo, new_draft
from tests.python.cplugs.owner import turn_on


def _tree(root: Path) -> set[Path]:
    return set(root.rglob("*"))


def test_a_new_draft_is_a_folder_of_starter_files_and_writes_nothing_outside_the_labs_storage(tmp_path: Path) -> None:
    storage = tmp_path / "state" / "cplugs" / "devwidgetlab"
    storage.mkdir(parents=True)
    repo_before = _tree(store.REPO / "web" / "src")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    before = _tree(tmp_path)
    made = new_draft(storage)
    folder = storage / "drafts" / "pulse-board"
    assert made["slug"] == "pulse-board" and made["kind"] == "new" and made["widget"] == "core.pulse-board" and made["state"] == "starter"
    for name in ("draft.json", "BRIEF.md", "OVERRIDES.md", "widget.json", "contract.json", "captures"):
        assert (folder / name).exists(), name
    assert made["files"] == ["web/src/opscenter/cells/pulse-board/Cell.svelte", "web/src/opscenter/widgets/fixtures/core.pulse-board.ts"]
    widget = json.loads((folder / "widget.json").read_text())
    assert widget["id"] == "core.pulse-board" and widget["hosts"] == ["home", "terminal"] and widget["fits"]["sizes"] == ["small", "wide"]
    assert json.loads((folder / "contract.json").read_text())["fixture"] == "core.pulse-board"
    assert "shows a pulse" in (folder / "BRIEF.md").read_text()
    new_paths = _tree(tmp_path) - before
    assert new_paths and all(p.is_relative_to(storage) or storage.is_relative_to(p) for p in new_paths), new_paths
    assert not _tree(elsewhere) and _tree(store.REPO / "web" / "src") == repo_before


def test_a_revision_folder_holds_only_the_brief_until_a_file_changes(tmp_path: Path) -> None:
    storage = tmp_path / "s"
    made = create.create_revision(storage, "core.notes", "Notes denser", "the header wastes a row", {"theme": "carnivore"})
    folder = storage / "drafts" / "notes-denser"
    assert made["kind"] == "revision" and made["widget"] == "core.notes" and made["files"] == []
    assert sorted(p.name for p in folder.iterdir()) == ["BRIEF.md", "OVERRIDES.md", "captures", "draft.json", "files"]
    assert "the header wastes a row" in (folder / "BRIEF.md").read_text() and "theme: carnivore" in (folder / "BRIEF.md").read_text()
    changed = folder / "files" / "web/src/opscenter/cells/notes/Cell.svelte"
    changed.parent.mkdir(parents=True)
    changed.write_text("<p>changed</p>")
    store.write_overrides_note(folder, store.read_record(folder))
    assert store.summary(folder)["files"] == ["web/src/opscenter/cells/notes/Cell.svelte"]
    assert "overrides `web/src/opscenter/cells/notes/Cell.svelte`" in (folder / "OVERRIDES.md").read_text()
    assert create.create_revision(storage, "core.notes", "Notes denser", "again", {})["slug"] == "notes-denser-2"


def test_the_list_names_every_draft_newest_first_and_skips_set_aside_ones(tmp_path: Path) -> None:
    storage = tmp_path / "s"
    first = new_draft(storage, "Alpha board")
    second = create.create_revision(storage, "core.notes", "Beta", "x", {})
    (storage / "drafts" / "broken").mkdir()
    assert {d["slug"] for d in store.list_drafts(storage)} == {first["slug"], second["slug"]}
    store.discard(storage, first["slug"])
    assert [d["slug"] for d in store.list_drafts(storage)] == [second["slug"]]
    assert any((storage / "drafts" / ".discarded").iterdir())


@pytest.mark.parametrize("bad", ["", "A", "a", "x" * 41, "has space", "../x", "a/b", "-lead", "trail-", "Upper"])
def test_a_bad_draft_name_is_refused(bad: str) -> None:
    with pytest.raises(errors.DraftInvalid):
        store.check_slug(bad)


@pytest.mark.parametrize("rel", ["../x", "/etc/passwd", "web/src/../../x", "client/js/app.js", "src/main.py", "web\\src\\x", ""])
def test_a_mirror_path_must_sit_under_web_src(rel: str) -> None:
    with pytest.raises(errors.DraftInvalid):
        store.mirror_target(rel)


def test_a_new_draft_refuses_a_taken_id_a_bad_list_and_an_unknown_widget(tmp_path: Path) -> None:
    storage = tmp_path / "s"
    with pytest.raises(errors.DraftExists):
        create.create_new(storage, "Notes", "x", ["home"], ["small"], "tools")
    with pytest.raises(errors.DraftInvalid):
        create.create_new(storage, "Fine name", "x", ["sidebar"], ["small"], "tools")
    with pytest.raises(errors.DraftInvalid):
        create.create_new(storage, "Fine name", "x", ["home"], ["huge"], "tools")
    with pytest.raises(errors.DraftInvalid):
        create.create_revision(storage, "core.nothing", "x", "y", {})
    assert not (storage / "drafts").exists() or not any((storage / "drafts").iterdir())


def test_a_new_draft_may_declare_every_host_the_lab_draws_the_drawer_and_the_popout_included(tmp_path: Path) -> None:
    storage = tmp_path / "state" / "cplugs" / "devwidgetlab"
    storage.mkdir(parents=True)
    made = create.create_new(storage, "Everywhere", "x", ["home", "terminal", "drawer", "popout"], ["small"], "tools")
    widget = json.loads((storage / "drafts" / made["slug"] / "widget.json").read_text())
    assert widget["hosts"] == ["home", "terminal", "drawer", "popout"]
    assert json.loads((storage / "drafts" / made["slug"] / "contract.json").read_text())["hosts"] == ["home", "terminal", "drawer", "popout"]
    assert set(starter.NEW_HOSTS) == {"home", "terminal", "drawer", "popout"}


def test_no_draft_work_runs_without_a_checkout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store, "SCRIPT", Path("/nonexistent/capture_one.py"))
    with pytest.raises(errors.NoCheckout):
        new_draft(tmp_path / "s")
    with pytest.raises(errors.NoCheckout):
        create.create_revision(tmp_path / "s", "core.notes", "x", "y", {})
    with pytest.raises(errors.NoCheckout):
        preview.start_build(tmp_path / "s", "x-y")
    with pytest.raises(errors.NoCheckout):
        preview.resolve_file(tmp_path / "s", "t", "index.html")


def test_hand_to_claude_refuses_without_a_checkout_and_starts_the_session_in_the_folder(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "s"
    made = new_draft(storage)
    calls: List[Any] = []

    async def start_in_folder(working_dir: str, label: str, prompt: str) -> str:
        calls.append((working_dir, label, prompt))
        return "ses_abc12345"

    ctx = SimpleNamespace(sessions=SimpleNamespace(start_in_folder=start_in_folder))
    assert asyncio.run(session.hand_to_claude(ctx, storage, made["slug"]))["session"] == "ses_abc12345"
    assert calls[0][0] == str(storage / "drafts" / "pulse-board") and calls[0][2] == session.OPENING_PROMPT and not session.OPENING_PROMPT.startswith("-")
    assert store.read_record(storage / "drafts" / "pulse-board")["state"] == "working"
    monkeypatch.setattr(store, "SCRIPT", Path("/nonexistent/capture_one.py"))
    calls.clear()
    with pytest.raises(errors.NoCheckout):
        asyncio.run(session.hand_to_claude(ctx, storage, made["slug"]))
    assert calls == []


def test_hand_to_claude_names_a_missing_grant(tmp_path: Path) -> None:
    storage = tmp_path / "s"
    made = new_draft(storage)
    with pytest.raises(errors.SessionUnavailable):
        asyncio.run(session.hand_to_claude(SimpleNamespace(sessions=SimpleNamespace()), storage, made["slug"]))


class _Held:

    def __init__(self, site: Path, code: int = 0) -> None:
        self.site, self.returncode, self.gate = site, code, asyncio.Event()

    async def wait(self) -> int:
        await self.gate.wait()
        if self.returncode == 0:
            self.site.mkdir(parents=True, exist_ok=True)
            (self.site / "index.html").write_text("<html>draft</html>")
        return self.returncode

    def kill(self) -> None:
        self.gate.set()


def test_one_build_runs_at_a_time_and_a_failed_build_is_never_recorded_as_built(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "s"
    first, other = new_draft(storage, "First one"), new_draft(storage, "Other one")
    procs: List[_Held] = []

    async def spawn(*args: Any, **kwargs: Any):
        assert args[0].endswith("vite") and args[1:3] == ("build", "--config") and kwargs["env"]["LAB_DRAFT_DIR"].endswith("first-one")
        proc = _Held(storage / "drafts" / "first-one" / "build" / "site", code=len(procs))
        procs.append(proc)
        return proc

    monkeypatch.setattr(preview, "require_buildable", lambda storage: store.REPO)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def spawned(count: int) -> None:
        while len(procs) < count:
            await asyncio.sleep(0.01)

    async def scenario() -> None:
        assert preview.start_build(storage, first["slug"])["state"] == "building"
        with pytest.raises(errors.BuildBusy):
            preview.start_build(storage, other["slug"])
        await spawned(1)
        procs[0].gate.set()
        await preview._job["task"]
        assert store.read_build(storage / "drafts" / "first-one")["state"] == "built"
        assert store.read_record(storage / "drafts" / "first-one")["state"] == "built"
        preview.start_build(storage, first["slug"])
        await spawned(2)
        procs[1].gate.set()
        await preview._job["task"]
        failed = store.read_build(storage / "drafts" / "first-one")
        assert failed["state"] == "failed" and failed["error"]

    asyncio.run(scenario())


def test_a_frame_link_needs_a_good_ticket_and_cannot_leave_the_build(tmp_path: Path) -> None:
    storage = tmp_path / "s"
    made = new_draft(storage)
    site = storage / "drafts" / made["slug"] / "build" / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<html></html>")
    (storage / "drafts" / made["slug"] / "draft.json.secret").write_text("no")
    link = preview.mint_ticket(made["slug"])
    assert link["path"].startswith(preview.SERVE_PREFIX + "/") and link["path"].endswith("/index.html")
    ticket = link["path"].split("/")[-2]
    assert preview.resolve_file(storage, ticket, "index.html") == (site / "index.html").resolve()
    for bad_ticket in ("", "x", ticket[:-2] + "zz", "pulse-board.1.abc"):
        with pytest.raises(errors.DraftNotFound):
            preview.resolve_file(storage, bad_ticket, "index.html")
    for rel in ("../draft.json", "../../BRIEF.md", "nothing.js"):
        with pytest.raises(errors.DraftNotFound):
            preview.resolve_file(storage, ticket, rel)
    expired = signed_links.mint(preview.TICKET_LABEL, [made["slug"]], 3600, now=0)
    with pytest.raises(errors.DraftNotFound):
        preview.resolve_file(storage, expired, "index.html")


def test_the_draft_routes_end_to_end(host_app, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    app, host = host_app
    turn_on(host, "devwidgetlab")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        empty = client.get(f"{BASE}/drafts").json()
        assert empty["available"] is True and empty["drafts"] == []
        made = client.post(f"{BASE}/drafts", json={"kind": "new", "name": "Pulse board", "what": "x"})
        assert made.status_code == 200 and made.json()["slug"] == "pulse-board"
        rev = client.post(f"{BASE}/drafts", json={"kind": "revision", "widget": "core.notes", "name": "Notes denser", "what": "tighter", "context": {"theme": "carnivore"}})
        assert rev.status_code == 200 and rev.json()["kind"] == "revision"
        assert {d["slug"] for d in client.get(f"{BASE}/drafts").json()["drafts"]} == {"pulse-board", "notes-denser"}
        assert client.post(f"{BASE}/drafts", json={"kind": "new", "name": "Pulse board"}).status_code == 409
        assert client.post(f"{BASE}/drafts", json={"kind": "new", "name": "x", "hosts": ["sidebar"]}).status_code == 422
        assert client.post(f"{BASE}/drafts", json={"kind": "revision", "widget": "core.nothing", "name": "n"}).json()["detail"]["code"] == "draft_invalid"
        assert client.get(f"{BASE}/drafts/pulse-board").json()["widget"] == "core.pulse-board"
        assert client.get(f"{BASE}/drafts/nope-nope").status_code == 404
        assert client.post(f"{BASE}/drafts/pulse-board/ticket").json()["detail"]["code"] == "draft_not_found"
        plan = client.get(f"{BASE}/drafts/pulse-board/ship-plan").json()
        assert plan["kind"] == "new" and plan["problems"] == [] and len(plan["appends"]) == 2
        assert client.delete(f"{BASE}/drafts/notes-denser").status_code == 200
        assert [d["slug"] for d in client.get(f"{BASE}/drafts").json()["drafts"]] == ["pulse-board"]
        filed = client.post(f"{BASE}/drafts", json={"kind": "new", "name": "Load board", "category": "monitoring"})
        assert filed.status_code == 200 and filed.json()["manifest"]["category"] == "monitoring"
        assert client.post(f"{BASE}/drafts", json={"kind": "new", "name": "Odd board", "category": "bogus"}).status_code == 422
        monkeypatch.setattr(store, "SCRIPT", Path("/nonexistent/capture_one.py"))
        gone = client.get(f"{BASE}/drafts").json()
        assert gone["available"] is False and gone["reason"] == "no_checkout" and gone["drafts"] == [] and gone["source"]["origin"] == "none"
        for call in (client.post(f"{BASE}/drafts", json={"kind": "new", "name": "Other one"}), client.post(f"{BASE}/drafts/pulse-board/build"),
                     client.post(f"{BASE}/drafts/pulse-board/hand-to-claude"), client.get(f"{BASE}/drafts/pulse-board/ship-plan")):
            assert call.status_code == 503 and call.json()["detail"]["code"] == "no_checkout"


def test_the_draft_routes_need_a_token_and_the_frame_route_needs_a_ticket(host_app) -> None:  # noqa: F811
    app, host = host_app
    turn_on(host, "devwidgetlab")
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{BASE}/drafts").status_code == 401
        assert anonymous.post(f"{BASE}/drafts", json={"kind": "new", "name": "x"}).status_code == 401
        assert anonymous.post(f"{BASE}/drafts/x-y/hand-to-claude").status_code == 401
        assert anonymous.get(f"{BASE}/draft-harness/not-a-ticket/index.html").status_code == 404


def _git_repo(root: Path) -> Path:
    for args in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def test_the_ship_dry_run_writes_nothing_and_apply_moves_the_files_then_the_folder(tmp_path: Path) -> None:
    storage = tmp_path / "s"
    made = new_draft(storage)
    folder = storage / "drafts" / made["slug"]
    repo = fake_repo(tmp_path / "repo")
    before_repo = _tree(repo)
    dry = ship.plan(folder, repo)
    assert dry["problems"] == [] and [c["action"] for c in dry["copy"]] == ["adds", "adds"] and len(dry["wiring"]) == len(ship.WIRING)
    assert _tree(repo) == before_repo and folder.exists()
    done = ship.apply(folder, repo, tmp_path / "trash")
    assert (repo / "web/src/opscenter/cells/pulse-board/Cell.svelte").is_file()
    ids = [r["id"] for r in json.loads((repo / "src/data/widgets.json").read_text())["widgets"]]
    assert ids == ["core.notes", "core.pulse-board"] and not folder.exists() and Path(done["trashed"]).is_dir()
    assert json.loads((repo / "src/data/widget-contracts.json").read_text())["widgets"][-1]["fixture"] == "core.pulse-board"


def test_shipping_a_draft_with_problems_writes_nothing(tmp_path: Path) -> None:
    storage = tmp_path / "s"
    repo = fake_repo(tmp_path / "repo")
    empty_revision = create.create_revision(storage, "core.notes", "Nothing yet", "x", {})
    folder = storage / "drafts" / empty_revision["slug"]
    assert ship.plan(folder, repo)["problems"]
    before = _tree(repo)
    with pytest.raises(errors.DraftInvalid):
        ship.apply(folder, repo, tmp_path / "trash")
    assert _tree(repo) == before and folder.exists() and not (tmp_path / "trash").exists()
    (folder / "files" / "web/src/opscenter/cells/notes").mkdir(parents=True)
    (folder / "files" / "web/src/opscenter/cells/notes/Cell.svelte").write_text("<p>new</p>")
    plan = ship.plan(folder, repo)
    assert plan["problems"] == [] and plan["copy"][0]["action"] == "overrides"
    ship.apply(folder, repo, tmp_path / "trash", keep=True)
    assert (repo / "web/src/opscenter/cells/notes/Cell.svelte").read_text() == "<p>new</p>" and folder.exists()


def test_the_ship_script_is_a_dry_run_unless_told_to_apply(tmp_path: Path, capsys) -> None:
    from src.cplugs.devwidgetlab.drafts import ship_cli as ship_draft

    storage = tmp_path / "s"
    made = new_draft(storage)
    folder = storage / "drafts" / made["slug"]
    repo = _git_repo(fake_repo(tmp_path / "repo"))
    before = _tree(repo)
    assert ship_draft.main(["--draft", str(folder), "--repo", str(repo)]) == 0
    assert _tree(repo) == before and folder.exists()
    assert ship_draft.main(["--draft", str(tmp_path / "missing"), "--repo", str(repo)]) == 2
    trees = tmp_path / "trees"
    assert ship_draft.main(["--draft", str(folder), "--repo", str(repo), "--apply", "--trash", str(tmp_path / "t"), "--worktrees", str(trees)]) == 0
    assert not folder.exists() and (trees / "widget-draft-pulse-board" / "web/src/opscenter/widgets/fixtures/core.pulse-board.ts").is_file()
    shutil.rmtree(tmp_path / "t")


def test_the_starter_cell_and_fixtures_name_what_the_build_imports() -> None:
    record = starter.widget_record("pulse-board", "Pulse board", ["home"], ["small"], "tools")
    assert record["paths"]["cell"].endswith("pulse-board/Cell.svelte") and record["fixtures_export"] == "pulseBoardFixtures"
    assert f"export const {record['fixtures_export']}" in starter.FIXTURES_STUB.format(title="t", wid="core.x", export_name=record["fixtures_export"])


def test_a_new_drafts_widget_json_lists_every_option_a_built_in_has() -> None:
    record = starter.widget_record("pulse-board", "Pulse board", ["home"], ["small"], "tools")
    for option in ("settings", "scope", "looks", "keepAlive", "views"):
        assert option in record and record[option] is None, option


def test_every_brief_carries_the_menu_checklist_and_a_menu_map_to_fill(tmp_path: Path) -> None:
    new = brief.compose_new(tmp_path, "pulse-board", "Pulse board", "shows a pulse", ["home"], ["small"], "tools")
    revision = brief.compose_revision(tmp_path, "notes-denser", "core.notes", "Notes denser", "denser", {})
    for text in (new, revision):
        assert "## Chrome and menus (`docs/widget-spec.md` section 11" in text
        assert "NO KEBAB" in text and "declareWidgetActions" in text and "icon at the top left of its title strip" in text and "Rows get NO menu of their own" in text and "`LETTERS`" in text
        assert "## Menu map" in text and "| action | menu id | header control | widget menu | letter |" in text and "row menu" not in text.lower()
        assert "docs/widget-system.md` section 25" in text
        assert "section 13, \"The widget shell\"" in text and "section 12, \"Statefulness\"" in text and "SHELL_CONFORMANCE_ROOT" in text
    assert new.index("## Menu map") < new.index("## Rules")


def test_the_starter_cell_is_the_menu_standard_not_a_bare_box() -> None:
    cell = starter.CELL_STUB.format(title="Pulse", what="shows a pulse", slug="pulse-board", title_attr="Pulse")
    module = cell[: cell.index("</script>")]
    assert '<script lang="ts" module>' in module and "defineWidget({" in module and "id: 'core.pulse-board'" in module
    assert "state: { 'show-path': { home: 'device', default: false" in module
    assert "useWidget(DRAFT_WIDGET, () => props" in cell[len(module):] and "<WidgetShell {widget} {controls}>" in cell
    assert "frameHeader" not in cell and "declareWidgetActions(" not in cell
    assert "rowMenu" not in cell and "RowMenu" not in cell and "top left of its title strip" in cell
    assert "aria-haspopup" not in cell and "CascadeMenu" not in cell and "kebab" not in cell.lower().replace("no kebab", "")
    assert "id: 'show-path'" in cell
