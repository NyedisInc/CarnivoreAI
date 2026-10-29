
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime
from src.cplugs.sdk import save_triggers, transcript_files, vault_sources
from tests.python.cplugs.save.vault_helpers import stop_follower
from tests.python.time_machine.helpers import CONV, FOLDER, WORKDIR, make_corpus

BASE = "/api/v1/cplugs/save"
POINTS = f"{BASE}/conversations/{CONV}/points"


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    corpus = make_corpus(tmp_path)
    config = state / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(transcript_files, "state_dir", lambda: state)
    monkeypatch.setattr(transcript_files, "config_file", lambda: config)
    monkeypatch.setattr(transcript_files, "projects_dir", lambda: corpus)
    monkeypatch.setattr(vault_sources, "claude_roots", lambda: (corpus,))
    monkeypatch.setattr(vault_sources, "codex_home", lambda: tmp_path / "codex")
    app = FastAPI()
    host = runtime.install(app, state)
    host.publish = lambda *_a, **_k: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        revision = client.get(BASE).json()["revision"]
        assert client.put(BASE, json={"revision": revision, "enabled": True}).status_code == 200
        stop_follower(client)
        yield client, state, corpus, tmp_path
    asyncio.run(host.stop())


def _kill() -> None:
    save_triggers.announce(save_triggers.LifecycleSave(
        event="kill", conversation_id=CONV, session_uuid="sess-uuid-1", family="claude",
        facts={"working_dir": WORKDIR, "project_name": "My Project", "wrapper": "claude"}))


def test_summary_counts_the_vault_and_health_reports_the_engine(rig):
    client, _state, _corpus, _tmp = rig
    _kill()
    summary = client.get(f"{BASE}/summary").json()
    assert summary["available"] is True and summary["conversations"] == 1 and summary["points"] == 1
    assert summary["used_bytes"] > 0 and summary["max_points_per_conversation"] >= 1
    health = client.get(f"{BASE}/health").json()
    assert set(health) >= {"known", "uncovered", "on_disk", "stale_hours", "unavailable", "over_cap", "damaged"}


def _set_location(client: TestClient, value: str):
    revision = client.get(BASE).json()["revision"]
    return client.put(BASE, json={"revision": revision, "settings": {"vaultLocation": value}})


def test_a_location_on_an_unmounted_volume_is_refused_and_the_old_one_stays(rig):
    client, state, _corpus, tmp = rig
    refused = _set_location(client, "/Volumes/NoSuchVolumeForTheTest/vault")
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "settings_refused"
    assert not Path("/Volumes/NoSuchVolumeForTheTest").exists()
    assert client.get(f"{BASE}/location").json()["location"] == ""
    chosen = tmp / "elsewhere"
    chosen.mkdir()
    moved = _set_location(client, str(chosen / "vault"))
    assert moved.status_code == 200 and (chosen / "vault").is_dir()
    assert client.get(f"{BASE}/location").json()["available"] is True
    assert _set_location(client, "").status_code == 200
    assert client.get(f"{BASE}/location").json()["root"] == str(state / "vault")


def test_a_location_in_a_synced_folder_is_refused(rig, monkeypatch):
    client, _state, _corpus, tmp = rig
    home = tmp / "home"
    (home / "Dropbox").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    refused = _set_location(client, str(home / "Dropbox" / "vault"))
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "destination_refused"
    assert not (home / "Dropbox" / "vault").exists()
    real = tmp / "real"
    real.mkdir()
    (tmp / "link").symlink_to(real)
    assert _set_location(client, str(tmp / "link" / "vault")).json()["detail"]["code"] == "destination_refused"


def test_the_location_view_warns_when_the_vault_shares_a_disk_with_the_transcripts(rig):
    client, _state, _corpus, tmp = rig
    chosen = tmp / "same-disk"
    chosen.mkdir()
    saved = _set_location(client, str(chosen / "vault"))
    assert saved.status_code == 200 and any("same disk" in w["message"] and "same disk as" in w["detail"] for w in saved.json().get("settings_warnings", []))
    view = client.get(f"{BASE}/location").json()
    assert view["available"] is True and view["refusals"] == [] and any("same disk" in w["detail"] for w in view["warnings"])


def test_the_last_point_and_a_pinned_point_cannot_be_deleted(rig):
    client, _state, _corpus, _tmp = rig
    _kill()
    only = client.get(POINTS).json()["points"][0]["id"]
    sole = client.delete(f"{POINTS}/{only}")
    assert sole.status_code == 409 and sole.json()["detail"]["code"] == "sole_copy"
    assert client.get(POINTS).json()["points"][0]["id"] == only


def test_restoring_over_a_different_transcript_is_refused_and_writes_nothing(rig):
    client, _state, corpus, _tmp = rig
    _kill()
    point = client.get(POINTS).json()["points"][0]["id"]
    transcript = corpus / FOLDER / f"{CONV}.jsonl"
    transcript.write_bytes(transcript.read_bytes() + b'{"type":"user","message":"typed after the backup"}\n')
    after = transcript.read_bytes()
    refused = client.post(f"{POINTS}/{point}/restore", json={})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "transcript_exists"
    assert transcript.read_bytes() == after


def test_moving_the_vault_says_so_when_the_old_one_holds_a_conversations_only_copy(rig):
    client, state, corpus, tmp = rig
    _kill()
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    quiet = _set_location(client, str(elsewhere / "vault")).json()
    assert not any("only copy" in w for w in quiet.get("warnings", []))
    assert _set_location(client, "").status_code == 200
    (corpus / FOLDER / f"{CONV}.jsonl").unlink()
    warned = _set_location(client, str(elsewhere / "second")).json()
    assert any("only copy of 1 conversation" in w["detail"] and str(state / "vault") in w["detail"] for w in warned["settings_warnings"])
    assert (state / "vault" / "manifests").is_dir()


def test_changing_the_cap_reassesses_over_cap_at_once(rig):
    client, _state, _corpus, tmp = rig
    from src.cplugs.save.service import RUNTIME

    _kill()
    boards = tmp / "boards"
    boards.mkdir()
    for i in range(3):
        (boards / "board.json").write_text('{"round": %d, "pad": "%s"}' % (i, os.urandom(2048).hex()))
        assert RUNTIME.vault().capture_folder("reviewboard.boards", boards).status == "written"
    assert client.put(f"{BASE}/settings", json={"cap_gb": 1e-7}).json()["over_cap"] is True
    assert client.put(f"{BASE}/settings", json={"cap_gb": 5}).json()["over_cap"] is False


def test_the_folder_routes_list_a_unit_and_restore_it_into_a_new_folder(rig):
    from src.cplugs.save.service import RUNTIME

    client, _state, _corpus, tmp = rig
    boards = tmp / "boards"
    (boards / "b1").mkdir(parents=True)
    (boards / "b1" / "board.json").write_text('{"round": 1}')
    assert RUNTIME.vault().capture_folder("reviewboard.boards", boards).status == "written"
    (boards / "b1" / "board.json").write_text('{"round": 2}')
    listed = {f["unit"]: f for f in client.get(f"{BASE}/folders").json()["folders"]}
    assert listed["reviewboard.boards"]["points"] == 1 and listed["reviewboard.boards"]["root"] == str(boards)
    done = client.post(f"{BASE}/folders/reviewboard.boards/restore", json={})
    assert done.status_code == 200, done.text
    target = Path(done.json()["target"])
    assert target.parent == tmp and target != boards and (target / "b1" / "board.json").read_text() == '{"round": 1}'
    assert (boards / "b1" / "board.json").read_text() == '{"round": 2}'
    assert client.post(f"{BASE}/folders/nosuch.unit/restore", json={}).status_code == 404


def test_the_folder_listing_names_the_plugin_and_the_points_route_lists_the_restore_choices(rig):
    from src.cplugs.save.service import RUNTIME

    client, _state, _corpus, tmp = rig
    boards = tmp / "boards"
    (boards / "b1").mkdir(parents=True)
    (boards / "b1" / "board.json").write_text('{"round": 1}')
    assert RUNTIME.vault().capture_folder("reviewboard.boards", boards).status == "written"
    (boards / "b1" / "board.json").write_text('{"round": 2, "more": "bytes"}')
    assert RUNTIME.vault().capture_folder("reviewboard.boards", boards).status == "written"
    row = {f["unit"]: f for f in client.get(f"{BASE}/folders").json()["folders"]}["reviewboard.boards"]
    assert (row["plugin"], row["data_id"], row["plugin_name_key"]) == ("reviewboard", "boards", "cplug.reviewboard.name")
    assert row["points"] == 2 and row["last_point_at"] and row["bytes"] > 0
    listed = client.get(f"{BASE}/folders/reviewboard.boards/points").json()
    ids = [p["point_id"] for p in listed["points"]]
    assert len(ids) == 2 and ids == sorted(ids, reverse=True) and listed["points"][0]["bytes"] > listed["points"][1]["bytes"]
    older = client.post(f"{BASE}/folders/reviewboard.boards/restore", json={"point_id": ids[1]}).json()
    assert older["point_id"] == ids[1] and (Path(older["target"]) / "b1" / "board.json").read_text() == '{"round": 1}'
    assert client.get(f"{BASE}/folders/nosuch.unit/points").status_code == 404
    assert client.get(f"{BASE}/folders/{CONV}/points").status_code == 404
