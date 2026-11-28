
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from src.api.auth import require_auth
from src.config.uploads import UploadsConfig
from src.plugins.host import runtime
from src.plugins.taskmanager import routes as huddle_routes, service, swarm_forms
from src.plugins.taskmanager.swarm_port import TaskManagerSwarmPort
from src.plugins.sdk import uploads as sdk_uploads
from tests.python.cplugs.owner import include_task_manager_routes, turn_on

BASE = "/api/v1/cplugs/huddle"
FORM = [
    {"id": "q1", "type": "single", "prompt": "how a session joins", "options": [
        {"id": "a", "label": "instantly", "recommended": True, "reason": "never interrupts"}, {"id": "b", "label": "restart now"}]},
    {"id": "q2", "type": "yes_no", "prompt": "allow studio now", "recommend": {"value": False}},
    {"id": "q3", "type": "long_text", "prompt": "looks", "required": False},
]


def test_a_staged_form_posts_on_the_card_and_one_submit_reaches_the_agent_as_ids_words_and_paths(tmp_path: Path, monkeypatch):
    caps = UploadsConfig()
    monkeypatch.setattr(sdk_uploads, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(uploads=caps)))
    monkeypatch.setattr(service, "project_names", lambda ctx: {})
    app = FastAPI()
    include_task_manager_routes(app, huddle_routes.router)
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    decided = []

    class Swarm:
        def thread_changed(self, list_key):
            pass

        async def card_decided(self, ref, decision, note, owner_message_ref, *, structured=None):
            decided.append(SimpleNamespace(ref=ref, decision=decision, note=note, structured=structured))

    monkeypatch.setattr(service, "swarm_of", lambda ctx: Swarm())
    port = TaskManagerSwarmPort(host.context("taskmanager"))
    storage = host.context("taskmanager").storage

    assert asyncio.run(port.check_form(FORM)).startswith("1. how a session joins")
    asyncio.run(port.stage_form(7, FORM))
    item = asyncio.run(port.post_card("all", "question", "a question for you", "Which way should sessions join?", "question:7"))
    assert swarm_forms.take(storage, 7) is None
    with TestClient(app) as client:
        asked = client.get(f"{BASE}/items/{item}").json()["thread"][0]
        assert asked["kind"] == "question" and [q["id"] for q in asked["form"]] == ["q1", "q2", "q3"]
        png = io.BytesIO()
        Image.new("RGB", (2, 2)).save(png, "PNG")
        up = client.post(f"{BASE}/items/{item}/files", files={"file": ("shot.png", png.getvalue(), "image/png")})
        assert up.status_code == 200, up.text
        fid = up.json()["id"]
        raw = client.post(f"{BASE}/questions/{asked['id']}/answer", json={"answers": {"q1": {"choice": "a", "files": ["/etc/hosts"]}}})
        assert raw.status_code == 400 and not decided
        done = client.post(f"{BASE}/questions/{asked['id']}/answer", json={"answers": {
            "q1": {"choice": "b", "note": "warn first", "file_ids": [fid]}, "q2": {"value": False}}})
        assert done.status_code == 200, done.text

    [call] = decided
    path = call.structured["q1"]["files"][0]
    assert Path(path).is_absolute() and Path(path).read_bytes().startswith(b"\x89PNG")
    assert call.ref == "question:7" and call.decision == "answer"
    assert call.note == f"answers to 3 questions:\n1. b, note: warn first, file: {path}\n2. no\n3. no answer"
    assert call.structured == {"q1": {"choice": "b", "note": "warn first", "files": [path]}, "q2": {"value": False}, "q3": {"skipped": True}}
    assert "how a session joins" not in call.note and "restart now" not in call.note


def test_a_form_staged_in_the_old_folder_before_the_rename_still_posts(tmp_path: Path) -> None:
    from src.plugins.sdk.storage import CplugStorage

    storage = CplugStorage(tmp_path / "cplugs" / "taskmanager", None)
    storage.previous_path = tmp_path / "cplugs" / "huddle"
    old = storage.previous_path / swarm_forms.FOLDER / "5.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"questions": []}', encoding="utf-8")
    assert swarm_forms.take(storage, 5) == '{"questions": []}'
    swarm_forms.stage(storage, 6, "new")
    assert swarm_forms.take(storage, 6) == "new" and not (storage.previous_path / swarm_forms.FOLDER / "6.json").exists()
    swarm_forms.drop(storage, 5)
    assert swarm_forms.take(storage, 5) is None and not old.exists()
