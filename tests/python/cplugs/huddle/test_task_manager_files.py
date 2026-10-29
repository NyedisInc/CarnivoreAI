
from __future__ import annotations

import asyncio
import json
import os
import stat
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from src.api.auth import require_auth
from src.config.uploads import UploadsConfig
from src.cplugs.host import runtime
from src.cplugs.sdk import uploads as sdk_uploads
from src.cplugs.huddle import files, routes as huddle_routes, service
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"


def png(size=(4, 4)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def caps(monkeypatch) -> UploadsConfig:
    cfg = UploadsConfig()
    monkeypatch.setattr(sdk_uploads, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(uploads=cfg)))
    return cfg


@pytest.fixture
def app(tmp_path: Path, monkeypatch, caps) -> FastAPI:
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    own = SimpleNamespace(tmux_session=None, label=None, session=SimpleNamespace(id="ses_1"), project_id=12, host_key="local")

    async def infos():
        return [own]

    app.state.session_manager = SimpleNamespace(app=app, gate_waited=True, list_session_infos=infos)
    return app


@pytest.fixture
def client(app: FastAPI):
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def item(client) -> int:
    return client.post(f"{BASE}/lists/all/items", json={"text": "look at this"}).json()["id"]


def upload(client, item_id: int, name: str, data: bytes):
    return client.post(f"{BASE}/items/{item_id}/files", files={"file": (name, data, "application/octet-stream")})


def folder(app: FastAPI) -> Path:
    return runtime.host_for(app).storage("huddle").path


def test_upload_stores_next_to_the_db_privately_and_answers_id_name_mime_size(client, app, item):
    r = upload(client, item, "shot.png", png())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "name", "mime", "size"} and body["name"] == "shot.png" and body["mime"] == "image/png"
    stored = folder(app) / "files" / str(item) / f"{body['id']}-shot.png"
    assert stored.read_bytes() == png() and body["size"] == len(png())
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert stat.S_IMODE(stored.parent.stat().st_mode) == 0o700 and stat.S_IMODE(stored.parent.parent.stat().st_mode) == 0o700


def test_the_app_caps_and_bad_types_are_refused(client, item, caps):
    assert (caps.max_size_mb, caps.max_file_size_mb) == (10, 50)
    caps.max_size_mb, caps.max_file_size_mb = 1, 2
    assert upload(client, item, "empty.txt", b"").status_code == 400
    assert upload(client, item, "fake.png", b"not a png at all").status_code == 400
    assert upload(client, item, "big.png", png((4, 4)) + b"\0" * (1024 * 1024 + 1)).status_code == 400
    assert upload(client, item, "big.bin", b"x" * (2 * 1024 * 1024 + 1)).status_code in (400, 413)
    assert upload(client, item, "ok.bin", b"x" * 1024).status_code == 200
    assert upload(client, 99999, "a.txt", b"hi").status_code == 404


def test_a_hostile_name_is_sanitized_to_a_safe_basename(client, app, item):
    body = upload(client, item, "../../etc/pass wd.txt", b"hi").json()
    assert body["name"] == "pass_wd.txt"
    assert not (folder(app) / "etc").exists()


def test_serve_needs_auth_and_picks_the_disposition(client, app, item):
    image = upload(client, item, "a.png", png()).json()
    doc = upload(client, item, "notes.html", b"<script>1</script>").json()
    got = client.get(f"{BASE}/items/{item}/files/{image['id']}")
    assert got.status_code == 200 and got.content == png() and got.headers["content-type"] == "image/png"
    assert got.headers["content-disposition"].startswith("inline")
    other = client.get(f"{BASE}/items/{item}/files/{doc['id']}")
    assert other.headers["content-disposition"].startswith("attachment") and other.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"{BASE}/items/{item}/files/zzzzzzzz").status_code == 404
    assert client.get(f"{BASE}/items/{item}/files/..%2F..%2Fx").status_code == 404
    app.dependency_overrides.clear()
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{BASE}/items/{item}/files/{image['id']}").status_code in (401, 403)
        assert anonymous.post(f"{BASE}/items/{item}/files", files={"file": ("a.txt", b"x")}).status_code in (401, 403)


def test_reply_stores_files_in_parts_and_may_be_files_only(client, app, item):
    f = upload(client, item, "a.png", png()).json()
    r = client.post(f"{BASE}/items/{item}/messages", json={"files": [f["id"]]})
    assert r.status_code == 200
    message = r.json()["message"]
    assert message["text"] == "" and message["files"][0]["name"] == "a.png" and message["files"][0]["image"] is True
    thread = client.get(f"{BASE}/lists/all").json()["items"][0]["thread"]
    assert thread[-1]["files"][0]["id"] == f["id"]
    with runtime.host_for(app).storage("huddle").connect(False) as conn:
        parts = json.loads(conn.execute("SELECT parts FROM work_messages WHERE id = ?", (message["id"],)).fetchone()["parts"])
    assert parts["files"][0].keys() >= {"id", "name", "mime", "size", "path"}
    assert client.post(f"{BASE}/items/{item}/messages", json={}).status_code == 400
    assert client.post(f"{BASE}/items/{item}/messages", json={"files": ["deadbeef"]}).status_code == 404
    with_text = client.post(f"{BASE}/items/{item}/messages", json={"text": "see", "files": [f["id"]]}).json()["message"]
    assert with_text["text"] == "see"


def test_a_file_of_another_item_cannot_be_attached(client, item):
    f = upload(client, item, "a.txt", b"hi").json()
    other = client.post(f"{BASE}/lists/all/items", json={"text": "other"}).json()["id"]
    assert client.post(f"{BASE}/items/{other}/messages", json={"files": [f["id"]]}).status_code == 404


def test_claude_reads_the_thread_with_absolute_paths(client, app, item):
    f = upload(client, item, "a.png", png()).json()
    client.post(f"{BASE}/items/{item}/messages", json={"text": "here", "files": [f["id"]]})
    caller = AgentCaller("ses_1", "cloude_a", "ses_1")
    result = asyncio.run(tools.call_tool(app.state.session_manager, caller, "task_manager_tasks_list", {"list": "all", "fields": ["thread"]}))
    assert not result.get("isError")
    message = json.loads(result["content"][0]["text"])["items"][0]["thread"][-1]
    entry = message["files"][0]
    assert set(entry) == {"name", "mime", "size", "path"} and os.path.isabs(entry["path"])
    assert Path(entry["path"]).read_bytes() == png()
    descriptions = {d["name"]: d["description"] for d in tools.tool_definitions()}
    assert all("ABSOLUTE" in descriptions[n] for n in ("task_manager_tasks_list", "task_manager_changes", "task_manager_reply"))


def test_orphan_sweep_removes_only_old_unattached_files(client, app, item):
    kept = upload(client, item, "kept.txt", b"k").json()
    client.post(f"{BASE}/items/{item}/messages", json={"files": [kept["id"]]})
    old = upload(client, item, "old.txt", b"o").json()
    fresh = upload(client, item, "fresh.txt", b"f").json()
    storage = runtime.host_for(app).storage("huddle")
    for stored in (storage.path / "files" / str(item)).iterdir():
        if stored.name.split("-", 1)[0] in (kept["id"], old["id"]):
            os.utime(stored, (time.time() - 3 * 86400,) * 2)
    assert files.sweep_orphans(storage) == 1
    assert client.get(f"{BASE}/items/{item}/files/{old['id']}").status_code == 404
    assert client.get(f"{BASE}/items/{item}/files/{kept['id']}").status_code == 200
    assert client.get(f"{BASE}/items/{item}/files/{fresh['id']}").status_code == 200
    assert files.sweep_orphans(storage) == 0


def test_the_sweep_drops_an_emptied_item_folder_and_reads_no_db_that_was_never_written(tmp_path):
    storage = runtime.Host(tmp_path, FastAPI()).storage("huddle")
    assert files.sweep_orphans(storage) == 0
    saved = files.save(storage, 7, "x.txt", b"x")
    path = files.locate(storage, 7, saved["id"])
    os.utime(path, (time.time() - 2 * 86400,) * 2)
    assert files.sweep_orphans(storage) == 1 and not (storage.path / "files" / "7").exists()


def test_purging_the_plugin_removes_every_file(client, app):
    from src.cplugs.host import routes as host_routes

    item = client.post(f"{BASE}/lists/all/items", json={"text": "x"}).json()["id"]
    upload(client, item, "a.txt", b"hi")
    host = runtime.host_for(app)
    assert not (host.folder("huddle") / "carnivore.db").exists()
    for leftover in ("huddle.db", "IMPORTED.json"):
        (host.folder("huddle") / leftover).write_bytes(b"x")
    price = host_routes._price(host, "huddle")
    assert price["files"] >= 1 and price["kept"] == 2
    assert (host.folder("huddle") / "files" / str(item)).is_dir()


def test_a_set_aside_copy_a_message_still_names_is_not_swept(client, app, item):
    f = upload(client, item, "kept.txt", b"k").json()
    client.post(f"{BASE}/items/{item}/messages", json={"files": [f["id"]]})
    storage = runtime.host_for(app).storage("huddle")
    stored = files.locate(storage, item, f["id"])
    aside = files.aside_name(stored)
    os.rename(stored, aside)
    os.utime(aside, (time.time() - 2 * files.ASIDE_GRACE_S,) * 2)
    assert files.sweep_orphans(storage) == 0 and aside.exists()
