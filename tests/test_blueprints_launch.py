
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.blueprints_helpers import (
    RecordingManager, db_for, git, make_repo, member, mount, patch_settings, spec,
)

# ruff: noqa: E402
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    build_skill, fixture_trust_root, item_for, keypairs, publish_index, serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)

API = "/api/v1/blueprints"
RUNNER = "alex/runner"
PLAIN = "alex/plain"
PLAIN_COMMIT = "c" * 40


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


def _publish(tmp_path: Path, served: Path):
    index_kp, publisher_kp, _ = keypairs(tmp_path / "keys")
    runner = build_skill(tmp_path, publisher="alex", name="runner", files={
        "SKILL.md": b"---\nname: runner\n---\n# runner\n", "scripts/run.sh": b"#!/bin/sh\necho hi\n"},
        exec_paths=("scripts/run.sh",))
    plain = build_skill(tmp_path, publisher="alex", name="plain", commit=PLAIN_COMMIT, label="p2",
                        files={"SKILL.md": b"---\nname: plain\n---\n# plain\n"})
    serve_archive(served, runner.tar_bytes)
    serve_archive(served, plain.tar_bytes, commit=PLAIN_COMMIT)
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp,
                  items=[item_for(runner, publisher="alex", name="runner", scripts=1),
                         item_for(plain, publisher="alex", name="plain", commit=PLAIN_COMMIT)],
                  serial=1)
    return fixture_trust_root(index_kp, publisher_kp), runner


def _with_roots(folder: Path) -> Path:
    for sub in (".claude/skills", ".agents/skills"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    return folder


def _world(tmp_path: Path, monkeypatch, app, fail_labels=()) -> RecordingManager:
    config = tmp_path / "config.json"
    config.write_text('{"blueprints": {"worktree_root": "%s"}}' % (tmp_path / "wt"))
    patch_settings(monkeypatch, app.state, config)
    from src.core import session_change_notice

    monkeypatch.setattr(session_change_notice, "publish", lambda s, f: None)
    manager = RecordingManager(db_for(app.state), fail_labels)
    mount(app.client.app, manager)
    return manager


def _team(tmp_path: Path, name: str = "Team") -> dict:
    project = _with_roots(tmp_path / "proj")
    repo = make_repo(tmp_path / "app")
    _with_roots(repo)
    for sub in (".claude/skills", ".agents/skills"):
        (repo / sub / ".keep").write_text("")
    git("-C", str(repo), "add", ".")
    git("-c", "user.email=t@example.invalid", "-c", "user.name=t", "-C", str(repo),
        "commit", "-q", "-m", "skill roots")
    return spec(
        name,
        member("api", project, skills=[RUNNER], opening_prompt="use the runner skill on the tests"),
        {"label": "web", "family": "codex", "skills": [PLAIN], "folder": {
            "mode": "worktree", "repo_path": str(repo), "base_branch": "master", "branch": "feat/web"}},
    )


def test_preview_names_the_worktree_the_skills_and_the_consent_sheet(tmp_path, served, monkeypatch):
    trust, runner = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        manager = _world(tmp_path, monkeypatch, app)
        document = _team(tmp_path)
        document["sessions"].append(member("ghost", tmp_path, family="nosuchwrapper"))
        uid = app.client.post(API, json={"spec": document}).json()["blueprint_uuid"]
        response = app.client.post(f"{API}/{uid}/launch/preview", json={})
        staged_after = app.staging_entries()
    assert response.status_code == 200, response.text
    api, web, ghost = response.json()["members"]
    assert api["problems"] == [] and api["opening_prompt"] is True
    assert api["skills"][0]["state"] == "to_install" and api["skills"][0]["needs_consent"] is True
    assert api["skills"][0]["consent_sheet"]["digest"] == runner.digest
    assert web["folder"]["worktree"]["create"] is True and web["folder"]["worktree"]["branch"] == "feat/web"
    assert web["skills"][0] == {**web["skills"][0], "state": "to_install", "needs_consent": False}
    assert ghost["problems"][0]["code"] == "family_unknown"
    assert not (tmp_path / "wt").exists(), "a preview makes no worktree"
    assert manager.calls == [] and staged_after == []


def test_launch_refuses_a_script_skill_without_consent_and_installs_it_with(tmp_path, served,
                                                                            monkeypatch):
    trust, runner = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        manager = _world(tmp_path, monkeypatch, app)
        uid = app.client.post(API, json={"spec": _team(tmp_path)}).json()["blueprint_uuid"]
        first = app.client.post(f"{API}/{uid}/launch", json={}).json()
        installed_first = {r.item_id for r in ledger_rows(app)}
        sheet = app.client.post(f"{API}/{uid}/launch/preview", json={"members": [0]}).json()
        shown = sheet["members"][0]["skills"][0]["consent_sheet"]
        wrong = app.client.post(f"{API}/{uid}/launch", json={"members": [0], "consents": {
            RUNNER: {"digest": "0" * 64, "body_sha": shown["body_sha"], "scripts": True}}}).json()
        good = app.client.post(f"{API}/{uid}/launch", json={"members": [0], "consents": {
            RUNNER: {"digest": shown["digest"], "body_sha": shown["body_sha"], "scripts": True}}}).json()
        rows = {r.item_id: r for r in ledger_rows(app)}

    api, web = first["members"]
    assert api["state"] == "failed" and api["problem"]["step"] == "skills"
    assert api["skills"][0]["code"] == "consent_required"
    assert web["state"] == "launched" and web["skills"][0]["state"] == "installed"
    assert first["complete"] is False and first["layout"] is None
    assert installed_first == {PLAIN}
    worktree = Path(web["folder"]["path"])
    assert git("-C", str(worktree), "symbolic-ref", "--short", "HEAD") == "feat/web"
    assert (worktree / ".claude" / "skills" / "plain" / "SKILL.md").is_file()
    assert wrong["members"][0]["state"] == "failed"
    assert wrong["members"][0]["skills"][0]["code"] == "consent_required"
    assert good["members"][0]["state"] == "launched", good
    assert rows[RUNNER].consented_digest == runner.digest
    assert (tmp_path / "proj" / ".claude" / "skills" / "runner" / "scripts" / "run.sh").is_file()
    labels = [c["label"] for c in manager.calls]
    assert labels == ["web", "api"], "sequential, and a refused member never reached create"
    assert manager.calls[-1]["agent_extra_args"] == ["use the runner skill on the tests"]


def test_a_full_launch_saves_a_layout_named_after_the_blueprint(tmp_path, served, monkeypatch):
    trust, _runner = _publish(tmp_path, served)
    document = None
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        manager = _world(tmp_path, monkeypatch, app)
        document = _team(tmp_path)
        document["sessions"][0].pop("skills")
        uid = app.client.post(API, json={"spec": document}).json()["blueprint_uuid"]
        one = app.client.post(f"{API}/{uid}/launch", json={"cols": 120, "rows": 40}).json()
        two = app.client.post(f"{API}/{uid}/launch", json={"overwrite_layout": True}).json()
        layouts = app.client.get("/api/v1/layouts").json()["layouts"]
    assert one["complete"] is True and two["complete"] is True
    assert one["layout"]["name"] == "Team" and two["layout"]["name"] == "Team"
    assert two["layout_updated"] is True and [entry["name"] for entry in layouts] == ["Team"]
    assert len(one["layout"]["members"]) == 2
    assert two["members"][1]["skills"][0]["state"] == "already_present"
    assert two["members"][1]["folder"]["worktree"]["create"] is False
    assert manager.calls[0]["initial_cols"] == 120 and manager.calls[0]["initial_rows"] == 40


def test_a_member_whose_create_fails_is_an_outcome_and_the_rest_launch(tmp_path, served,
                                                                       monkeypatch):
    trust, _runner = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        _world(tmp_path, monkeypatch, app, fail_labels=("api",))
        project = _with_roots(tmp_path / "proj")
        document = spec("Crew", member("api", project), member("web", project),
                        member("ops", project))
        uid = app.client.post(API, json={"spec": document}).json()["blueprint_uuid"]
        response = app.client.post(f"{API}/{uid}/launch", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["state"] for m in body["members"]] == ["failed", "launched", "launched"]
    assert body["members"][0]["problem"] == {**body["members"][0]["problem"],
                                             "step": "session", "code": "create_502"}
    assert body["complete"] is False and body["layout"]["name"] == "Crew"


def test_launch_creates_missing_skill_roots_in_a_fresh_worktree(tmp_path, served, monkeypatch):
    trust, _runner = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        _world(tmp_path, monkeypatch, app)
        repo = make_repo(tmp_path / "app")
        document = spec("Team", {"label": "web", "family": "claude", "skills": [PLAIN],
                                 "folder": {"mode": "worktree", "repo_path": str(repo),
                                           "base_branch": "master", "branch": "feat/web"}})
        uid = app.client.post(API, json={"spec": document}).json()["blueprint_uuid"]
        preview = app.client.post(f"{API}/{uid}/launch/preview", json={}).json()
        result = app.client.post(f"{API}/{uid}/launch", json={}).json()
    planned = preview["members"][0]
    assert set(planned["skill_roots_to_create"]) == {
        str(repo / ".claude" / "skills"), str(repo / ".agents" / "skills")}
    assert planned["problems"] == []
    outcome = result["members"][0]
    assert outcome["state"] == "launched", outcome
    worktree = Path(outcome["folder"]["path"])
    assert (worktree / ".claude" / "skills").is_dir()
    assert (worktree / ".agents" / "skills").is_dir()
    assert (worktree / ".claude" / "skills" / "plain" / "SKILL.md").is_file()
    assert outcome["skills"][0]["state"] == "installed"


def test_a_member_with_no_skills_creates_no_root(tmp_path, served, monkeypatch):
    trust, _runner = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        _world(tmp_path, monkeypatch, app)
        project = tmp_path / "proj"
        project.mkdir()
        document = spec("Solo", member("api", project))
        uid = app.client.post(API, json={"spec": document}).json()["blueprint_uuid"]
        result = app.client.post(f"{API}/{uid}/launch", json={}).json()
    outcome = result["members"][0]
    assert outcome["state"] == "launched", outcome
    assert not (project / ".claude").exists()
    assert not (project / ".agents").exists()


def test_a_symlinked_claude_dir_is_refused_never_created_through(tmp_path, served, monkeypatch):
    trust, _runner = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        _world(tmp_path, monkeypatch, app)
        project = tmp_path / "proj"
        project.mkdir()
        outside = tmp_path / "outside-claude"
        outside.mkdir()
        (project / ".claude").symlink_to(outside)
        document = spec("Solo", member("api", project, skills=[PLAIN]))
        uid = app.client.post(API, json={"spec": document}).json()["blueprint_uuid"]
        result = app.client.post(f"{API}/{uid}/launch", json={}).json()
    outcome = result["members"][0]
    assert outcome["state"] == "failed"
    assert outcome["problem"]["step"] == "skills"
    assert outcome["problem"]["code"] == "skill_root_unsafe"
    assert list(outside.iterdir()) == [], "must never write through the escaping symlink"




def _live_row(world, label: str, folder: Path, uuid: str) -> int:
    from contextlib import closing

    from src.core.db import connect
    from tests.lifecycle_helpers import add_row

    with closing(connect(world.db, create=False)) as conn:
        row_id = add_row(conn, uuid=uuid, name=f"cloude_{uuid}", epoch=9000 + len(world.manager.live))
        conn.execute("UPDATE sessions SET working_dir = ?, title = ? WHERE id = ?",
                     (str(folder), label, row_id))
        conn.commit()
    world.manager.live.append(row_id)
    return row_id


def _launch(world, document: dict) -> dict:
    uid = world.client.post(API, json={"spec": document}).json()["blueprint_uuid"]
    response = world.client.post(f"{API}/{uid}/launch", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_member_matched_by_session_uuid_is_reused_not_created(tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder = tmp_path / "proj"
    folder.mkdir()
    row_id = _live_row(world, "api", folder, "live-uuid-1")
    body = _launch(world, spec("Crew", member("renamed", folder, session_uuid="live-uuid-1"),
                               member("web", folder)))
    assert [m["state"] for m in body["members"]] == ["reused", "launched"]
    assert body["members"][0]["session"]["session_row_id"] == row_id
    assert body["complete"] is True and len(body["layout"]["members"]) == 2
    assert [c["label"] for c in world.manager.calls] == ["web"]


def test_a_closed_member_is_pinned_to_its_theme_over_the_folder_default(tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / ".cc.theme").write_text("snes")
    body = _launch(world, spec("Crew", member("a", folder, theme="matrix"), member("b", folder)))
    names = [m["session"]["tmux_session"] for m in body["members"]]
    assert world.manager.themes.resolve_project_theme(folder, names[0]) == "matrix"
    assert world.manager.themes.get_pin(names[1]) is None
    assert (folder / ".cc.theme").read_text() == "snes"


def test_an_ambiguous_label_and_folder_match_creates_never_guesses(tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder, other = tmp_path / "proj", tmp_path / "other"
    folder.mkdir(), other.mkdir()
    _live_row(world, "api", folder, "dup-1")
    _live_row(world, "api", folder, "dup-2")
    _live_row(world, "web", other, "solo-1")
    body = _launch(world, spec("Crew", member("api", folder), member("web", other)))
    assert [m["state"] for m in body["members"]] == ["launched", "reused"]




def _asleep_row(world, label: str, folder: Path, uuid: str) -> int:
    from contextlib import closing

    from src.core.db import connect
    from tests.lifecycle_helpers import add_row

    with closing(connect(world.db, create=False)) as conn:
        row_id = add_row(conn, uuid=uuid, name=f"cloude_{uuid}", epoch=7000 + len(uuid),
                         lifecycle="stopped")
        conn.execute("UPDATE sessions SET working_dir = ?, title = ?, lifecycle_source = "
                     "'slept_by_user' WHERE id = ?", (str(folder), label, row_id))
        conn.commit()
    return row_id


def _wake_double(monkeypatch, refuse: bool = False) -> list:
    from types import SimpleNamespace

    from src.api import session_sleep_routes

    woken: list = []

    async def wake(request, session_uuid, body=None):
        woken.append(session_uuid)
        if refuse:
            return SimpleNamespace(status="refused", code="wrapper_needed", detail="pick a wrapper",
                                   session_id=None, tmux_session=None)
        return SimpleNamespace(status="started", code=None, detail="", session_id="ses_woken",
                               tmux_session="cloude_woken")

    monkeypatch.setattr(session_sleep_routes, "wake_session", wake)
    return woken


def test_an_asleep_member_matched_by_uuid_is_woken_not_created(tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder = tmp_path / "proj"
    folder.mkdir()
    row_id = _asleep_row(world, "api", folder, "sleepy-1")
    woken = _wake_double(monkeypatch)
    body = _launch(world, spec("Crew", member("web", folder), member("renamed", folder, session_uuid="sleepy-1")))
    assert woken == ["sleepy-1"]
    assert [m["state"] for m in body["members"]] == ["launched", "woken"]
    assert body["members"][1]["session"]["session_row_id"] == row_id
    assert [c["label"] for c in world.manager.calls] == ["web"]
    assert body["complete"] is True and len(body["layout"]["members"]) == 2


def test_an_old_member_with_only_an_asleep_label_and_folder_match_is_woken(tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder, other = tmp_path / "proj", tmp_path / "other"
    folder.mkdir(), other.mkdir()
    _asleep_row(world, "api", folder, "sleepy-2")
    _live_row(world, "web", other, "live-2")
    _asleep_row(world, "web", other, "sleepy-3")
    woken = _wake_double(monkeypatch)
    body = _launch(world, spec("Crew", member("api", folder), member("web", other)))
    assert woken == ["sleepy-2"] and world.manager.calls == []
    assert [m["state"] for m in body["members"]] == ["woken", "reused"]


def test_a_refused_wake_is_a_failed_member_not_a_duplicate(tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder = tmp_path / "proj"
    folder.mkdir()
    _asleep_row(world, "api", folder, "sleepy-4")
    _wake_double(monkeypatch, refuse=True)
    body = _launch(world, spec("Crew", member("api", folder), member("web", folder)))
    assert [m["state"] for m in body["members"]] == ["failed", "launched"]
    assert body["members"][0]["problem"]["code"] == "wrapper_needed" and body["complete"] is False


def test_an_existing_layout_refuses_the_launch_until_overwrite_and_is_then_updated_in_place(
        tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder = tmp_path / "proj"
    folder.mkdir()
    uid = world.client.post(API, json={"spec": spec("Crew", member("a", folder), member("b", folder))}).json()["blueprint_uuid"]
    first = world.client.post(f"{API}/{uid}/launch", json={}).json()
    calls_before = len(world.manager.calls)
    refused = world.client.post(f"{API}/{uid}/launch", json={})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "layout_exists" and detail["layout"]["layout_uuid"] == first["layout"]["layout_uuid"]
    assert len(world.manager.calls) == calls_before
    second = world.client.post(f"{API}/{uid}/launch", json={"overwrite_layout": True}).json()
    layouts = world.client.get("/api/v1/layouts").json()["layouts"]
    assert len(layouts) == 1 and second["layout_updated"] is True
    assert second["layout"]["layout_uuid"] == first["layout"]["layout_uuid"]
    assert second["layout"]["revision"] > first["layout"]["revision"]




def _config(world) -> dict:
    import json

    return json.loads(world.config.read_text())


def _muted(world, session_uuid: str) -> int:
    from contextlib import closing

    from src.core.db import connect

    with closing(connect(world.db, create=False)) as conn:
        return conn.execute("SELECT notifications_muted FROM sessions WHERE session_uuid = ?",
                            (session_uuid,)).fetchone()[0]


def test_a_created_member_gets_its_saved_keep_awake_mute_and_background(tmp_path, monkeypatch):
    from src.api import session_background_routes
    from tests.blueprints_helpers import client_for

    async def ships(_theme_id):
        return True

    monkeypatch.setattr(session_background_routes, "_theme_ships_an_image", ships)
    world = client_for(tmp_path, monkeypatch)
    folder = tmp_path / "proj"
    folder.mkdir()
    body = _launch(world, spec(
        "Crew",
        member("a", folder, keep_awake=True, notifications_muted=True,
               background={"theme_id": "matrix", "dim": 0.5, "disabled": False}),
        member("b", folder)))
    first, second = (m["session"] for m in body["members"])
    assert _config(world)["auto_sleep"]["keep_awake"] == [first["session_uuid"]]
    assert _muted(world, first["session_uuid"]) == 1
    assert not _muted(world, second["session_uuid"])
    store = world.client.app.state.session_background_store
    assert store.get(first["tmux_session"])["theme_id"] == "matrix"
    assert store.get(first["tmux_session"])["dim"] == 0.5
    assert store.get(second["tmux_session"]) is None


def test_a_reused_member_keeps_its_own_settings_untouched(tmp_path, monkeypatch):
    from tests.blueprints_helpers import client_for

    world = client_for(tmp_path, monkeypatch)
    folder = tmp_path / "proj"
    folder.mkdir()
    _live_row(world, "api", folder, "live-uuid-2")
    body = _launch(world, spec("Crew", member("api", folder, session_uuid="live-uuid-2",
                                              keep_awake=True, notifications_muted=True)))
    assert body["members"][0]["state"] == "reused"
    assert "auto_sleep" not in _config(world)
    assert not _muted(world, "live-uuid-2")


def test_save_from_layout_captures_the_live_sessions_settings(tmp_path, monkeypatch):
    from contextlib import closing

    from src.core.db import connect
    from tests.blueprints_helpers import client_for
    from tests.layouts_helpers import add_sessions, grid, row

    world = client_for(tmp_path, monkeypatch)
    (a, ua), (b, _) = add_sessions(world.db, 2)
    with closing(connect(world.db, create=False)) as conn:
        for rid in (a, b):
            conn.execute("UPDATE sessions SET title = ?, working_dir = ? WHERE id = ?",
                         (f"s{rid}", str(tmp_path), rid))
        conn.execute("UPDATE sessions SET notifications_muted = 1 WHERE id = ?", (a,))
        name = conn.execute("SELECT tmux_name FROM sessions WHERE id = ?", (a,)).fetchone()[0]
        conn.commit()
    world.config.write_text(json.dumps({"auto_sleep": {"keep_awake": [ua]}}))
    world.client.app.state.session_background_store.set(name, theme_id="matrix", dim=0.4, disabled=False)
    layout = world.client.post("/api/v1/layouts", json={"name": "pair", "shape": grid(row(a), row(b))})
    uid = layout.json()["layout"]["layout_uuid"]
    made = world.client.post(f"{API}/from-layout/{uid}", json={})
    assert made.status_code == 200, made.text
    one, two = made.json()["spec"]["sessions"]
    assert one["keep_awake"] is True and one["notifications_muted"] is True
    assert one["background"] == {"theme_id": "matrix", "dim": 0.4, "disabled": False}
    assert two["keep_awake"] is None and two["notifications_muted"] is None and two["background"] is None
