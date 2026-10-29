
from __future__ import annotations

import json
from contextlib import closing

from tests.blueprints_helpers import client_for, member, spec
from tests.layouts_helpers import add_sessions, grid, row

# ruff: noqa: E402
from src.core.db import connect

API = "/api/v1/blueprints"


def _create(env, document):
    return env.client.post(API, json={"spec": document})


def test_create_list_get_replace_delete_round_trip(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    made = _create(env, spec("Team", member("api", tmp_path)))
    assert made.status_code == 200, made.text
    uid = made.json()["blueprint_uuid"]
    assert [b["name"] for b in env.client.get(API).json()["blueprints"]] == ["Team"]
    assert env.client.get(f"{API}/{uid}").json()["spec"]["sessions"][0]["label"] == "api"
    renamed = env.client.put(f"{API}/{uid}", json={"spec": spec("Crew", member("api", tmp_path))})
    assert renamed.json()["name"] == "Crew"
    assert env.client.delete(f"{API}/{uid}").json() == {"deleted": True}
    assert env.client.get(f"{API}/{uid}").json()["detail"]["code"] == "blueprint_not_found"
    assert [f["reason"] for f in env.frames] == ["blueprints"] * 3


def test_a_name_is_unique_ignoring_case(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    _create(env, spec("Team", member("a", tmp_path)))
    again = _create(env, spec("TEAM", member("a", tmp_path)))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "blueprint_name_taken"


def test_unknown_fields_are_a_422_not_ignored(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    document = spec("t", member("a", tmp_path))
    document["sessions"][0]["env"] = {"ANTHROPIC_API_KEY": "x"}
    assert _create(env, document).status_code == 422


def test_a_secret_is_refused_by_detector_name(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    key = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    response = _create(env, spec("t", member("a", tmp_path, opening_prompt=f"token {key} ok")))
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "blueprint_secret" and key not in response.text
    assert env.client.get(API).json()["blueprints"] == []


def test_export_then_import_round_trips_through_the_fixed_path(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    env = client_for(tmp_path, monkeypatch, projects=(project,))
    document = spec("Team", member("api", project, opening_prompt="read the README first"))
    uid = _create(env, document).json()["blueprint_uuid"]
    out = env.client.post(f"{API}/{uid}/export", json={"project_path": str(project)})
    assert out.status_code == 200, out.text
    written = project / ".carnivore" / "swarm.json"
    assert out.json()["path"] == str(written)
    assert json.loads(written.read_text())["sessions"][0]["opening_prompt"] == "read the README first"
    back = env.client.post(f"{API}/import", json={"project_path": str(project), "name": "Team 2"})
    assert back.status_code == 200, back.text
    assert back.json()["spec"]["sessions"] == env.client.get(f"{API}/{uid}").json()["spec"]["sessions"]


def test_export_and_import_only_reach_a_known_project(tmp_path, monkeypatch):
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    env = client_for(tmp_path, monkeypatch)
    uid = _create(env, spec("t", member("a", tmp_path))).json()["blueprint_uuid"]
    for call in (lambda: env.client.post(f"{API}/{uid}/export", json={"project_path": str(stranger)}),
                 lambda: env.client.post(f"{API}/import", json={"project_path": str(stranger)})):
        response = call()
        assert response.status_code == 409 and response.json()["detail"]["code"] == "project_path_invalid"
    assert not (stranger / ".carnivore").exists()


def test_a_malformed_swarm_file_is_refused_with_what_and_where(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".carnivore").mkdir(parents=True)
    env = client_for(tmp_path, monkeypatch, projects=(project,))
    swarm = project / ".carnivore" / "swarm.json"
    cases = {
        '{"name": "t", "sessions": [': "not valid JSON (line 1",
        '{"name": "t", "sessions": [], "extra": 1}': "extra",
        json.dumps(spec("t", member("a", "/x", model="bad model; rm"))): "sessions.0.model",
    }
    for text, expected in cases.items():
        swarm.write_text(text)
        response = env.client.post(f"{API}/import", json={"project_path": str(project)})
        assert response.status_code == 409, response.text
        body = response.json()["detail"]
        assert body["code"] == "swarm_file_invalid" and expected in body["detail"]
    assert env.client.get(API).json()["blueprints"] == []
    swarm.unlink()
    missing = env.client.post(f"{API}/import", json={"project_path": str(project)})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "swarm_file_missing"


def test_a_symlinked_swarm_file_or_directory_is_never_followed(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "swarm.json").write_text(json.dumps(spec("x", member("a", "/x"))))
    (project / ".carnivore").symlink_to(outside)
    env = client_for(tmp_path, monkeypatch, projects=(project,))
    uid = _create(env, spec("t", member("a", tmp_path))).json()["blueprint_uuid"]
    read = env.client.post(f"{API}/import", json={"project_path": str(project)})
    wrote = env.client.post(f"{API}/{uid}/export", json={"project_path": str(project)})
    assert read.json()["detail"]["code"] == wrote.json()["detail"]["code"] == "swarm_path_unsafe"
    assert json.loads((outside / "swarm.json").read_text())["name"] == "x"


def test_from_layout_keeps_members_and_turns_the_shape_into_a_template(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    (a, _), (b, _) = add_sessions(env.db, 2)
    with closing(connect(env.db, create=False)) as conn:
        for rid, title in ((a, "api"), (b, "web")):
            conn.execute("UPDATE sessions SET title = ?, working_dir = ?, agent_type = 'codex' "
                         "WHERE id = ?", (title, str(tmp_path), rid))
        conn.commit()
    layout = env.client.post("/api/v1/layouts", json={"name": "pair", "shape": grid(row(a), row(b))})
    uuid = layout.json()["layout"]["layout_uuid"]
    made = env.client.post(f"{API}/from-layout/{uuid}", json={})
    assert made.status_code == 200, made.text
    body = made.json()["spec"]
    assert body["name"] == "pair"
    assert [(s["label"], s["family"], s["folder"]["path"]) for s in body["sessions"]] == [
        ("api", "codex", str(tmp_path)), ("web", "codex", str(tmp_path))]
    assert "terminal:row:" not in json.dumps(body["shape_template"])
    unknown = env.client.post(f"{API}/from-layout/nope", json={})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "layout_not_found"


def test_settings_store_the_worktree_root_and_refuse_a_system_one(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    assert env.client.get(f"{API}/settings").json() == {"worktree_root": "~/dev-worktrees"}
    put = env.client.put(f"{API}/settings", json={"worktree_root": str(tmp_path / "trees")})
    assert put.status_code == 200
    assert json.loads(env.config.read_text())["blueprints"]["worktree_root"] == str(tmp_path / "trees")
    bad = env.client.put(f"{API}/settings", json={"worktree_root": "/"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "worktree_root_invalid"


def test_a_home_or_state_folder_member_fails_at_the_folder_step(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    document = spec("t", member("home", "~"), member("state", env.state))
    uid = _create(env, document).json()["blueprint_uuid"]
    body = env.client.post(f"{API}/{uid}/launch", json={}).json()
    assert [m["problem"]["code"] for m in body["members"]] == ["folder_invalid", "folder_invalid"]
    assert env.manager.calls == []
