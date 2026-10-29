
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.config.uploads import UploadsConfig
from src.cplugs.sdk import uploads as sdk_uploads
from src.cplugs.host import runtime
from src.cplugs.huddle.guide_rev import TASK_MANAGER_GUIDE_REV
from src.cplugs.sdk import sandboxed_html, signed_links
from src.cplugs.huddle import artifact_ticket, artifacts, routes as huddle_routes, routes_artifacts, service  # noqa: F401
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.security_headers import OWN_POLICY_HEADER, stamp_security_headers
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"
PAGE = "<!doctype html><title>x</title><h1>hello</h1><script>document.title='ok'</script>"


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))


@pytest.fixture(autouse=True)
def upload_caps(monkeypatch):
    monkeypatch.setattr(sdk_uploads, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(uploads=UploadsConfig())))


@pytest.fixture
def app(tmp_path: Path, monkeypatch) -> FastAPI:
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    return app


@pytest.fixture
def client(app: FastAPI):
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def item(client) -> int:
    return client.post(f"{BASE}/lists/all/items", json={"text": "show me"}).json()["id"]


def post(client, item_id, **over):
    body = {"title": "Layout A", "description": "two columns", "html": PAGE, **over}
    return client.post(f"{BASE}/items/{item_id}/artifacts", json=body)


def viewer_url(client, item_id) -> str:
    message = post(client, item_id).json()["message"]
    return client.post(f"{BASE}/items/{item_id}/artifacts/{message['artifact']['id']}/ticket").json()["url"]


def test_post_stores_the_page_with_the_item_and_the_card_on_the_wire(client, app, item):
    r = post(client, item)
    assert r.status_code == 200
    message = r.json()["message"]
    assert message["artifact"] == {"id": message["artifact"]["id"], "title": "Layout A", "description": "two columns", "size": len(PAGE.encode())}
    assert "files" not in message
    assert message["author"] == "claude" and message["kind"] == "info"
    stored = list((runtime.host_for(app).storage("huddle").path / "files" / str(item)).glob("*-artifact.html"))
    assert len(stored) == 1 and stored[0].read_text() == PAGE
    thread = client.get(f"{BASE}/lists/all").json()["items"][0]["thread"]
    assert thread[-1]["artifact"]["title"] == "Layout A"


def test_the_viewer_sends_its_own_sandbox_csp_and_nosniff(client, item):
    r = client.get(viewer_url(client, item))
    assert r.status_code == 200 and r.text == PAGE
    csp = r.headers["content-security-policy"]
    for directive in ("sandbox allow-scripts", "default-src 'none'", "connect-src 'none'", "frame-src 'none'", "form-action 'none'",
                      "base-uri 'none'", "frame-ancestors 'self'", "img-src data:"):
        assert directive in csp
    assert "allow-same-origin" not in csp and "allow-top-navigation" not in csp and "allow-popups" not in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["content-type"].startswith("text/html") and r.headers["cache-control"] == "private, no-store"


def test_the_viewer_needs_a_good_ticket_and_no_bearer(client, app, item):
    url = viewer_url(client, item)
    app.dependency_overrides.clear()
    with TestClient(app) as anonymous:
        assert anonymous.get(url).status_code == 200
        ticket = url.rsplit("/", 1)[1]
        item_id, file_id, expiry, sig = ticket.split(".")
        for bad in (f"{item_id}.{file_id}.{expiry}.{'A' * len(sig)}", f"{item_id}.{file_id}.{int(expiry) + 99}.{sig}", f"999.{file_id}.{expiry}.{sig}",
                    "garbage", "1.2.3", f"{item_id}.{file_id}.{expiry}"):
            assert anonymous.get(f"{BASE}/artifact-view/{bad}").status_code == 404, bad
        expired = artifact_ticket.mint(int(item_id), file_id, now=time.time() - artifact_ticket.TTL_S - 5)
        assert anonymous.get(f"{BASE}/artifact-view/{expired}").status_code == 404
        assert anonymous.post(f"{BASE}/items/{item_id}/artifacts/{file_id}/ticket").status_code in (401, 403)
        assert anonymous.post(f"{BASE}/items/{item_id}/artifacts", json={"title": "t", "html": PAGE}).status_code in (401, 403)


def test_a_ticket_is_only_minted_for_an_artifact_of_that_item(client, item):
    message = post(client, item).json()["message"]
    fid = message["artifact"]["id"]
    other = client.post(f"{BASE}/lists/all/items", json={"text": "other"}).json()["id"]
    assert client.post(f"{BASE}/items/{other}/artifacts/{fid}/ticket").status_code == 404
    plain = client.post(f"{BASE}/items/{item}/files", files={"file": ("n.html", b"<b>x</b>")}).json()
    assert client.post(f"{BASE}/items/{item}/artifacts/{plain['id']}/ticket").status_code == 404
    assert client.post(f"{BASE}/items/{item}/artifacts/nothing/ticket").status_code == 404


def test_the_two_megabyte_limit_and_field_checks(client, item):
    assert post(client, item, html="x" * artifacts.MAX_BYTES).status_code == 200
    assert post(client, item, html="x" * (artifacts.MAX_BYTES + 1)).status_code == 400
    assert post(client, item, html="   ").status_code == 400
    assert post(client, item, title=" ").status_code == 400
    assert post(client, item, title="t" * (artifacts.MAX_TITLE + 1)).status_code == 400
    assert post(client, item, description="a\nb").status_code == 400
    assert post(client, 99999).status_code == 404


def test_the_app_header_stamp_keeps_the_viewer_csp_and_stamps_every_other_response():
    own = Response("x", headers={**artifacts.VIEW_HEADERS, OWN_POLICY_HEADER: "1"})
    stamp_security_headers(own.headers)
    assert own.headers["content-security-policy"] == sandboxed_html.VIEW_CSP and OWN_POLICY_HEADER.lower() not in own.headers
    assert own.headers["x-content-type-options"] == "nosniff"
    plain = Response("x", headers={"Content-Security-Policy": "default-src *"})
    stamp_security_headers(plain.headers)
    assert "frame-ancestors 'none'" in plain.headers["content-security-policy"] and "'self'" in plain.headers["content-security-policy"]


def test_the_tool_posts_html_or_a_file_and_refuses_the_rest(manager, tmp_path):
    store = huddle_store(manager)
    item = store.add("all", "work", actor="joe")["id"]
    ok, out = call(manager, "task_manager_artifact_add", {"item": item, "title": "Mock", "description": "a mock", "html": PAGE})
    assert ok and out["title"] == "Mock" and out["size"] == len(PAGE.encode()) and out["guide_rev"] == TASK_MANAGER_GUIDE_REV
    page = tmp_path / "p.html"
    page.write_text(PAGE)
    ok, out = call(manager, "task_manager_artifact_add", {"item": item, "title": "From file", "file_path": str(page)})
    assert ok
    thread = store.item(item)["thread"]
    assert [m["artifact"]["title"] for m in thread if m.get("artifact")] == ["Mock", "From file"]
    assert thread[-1]["unread"] is True
    for args in ({"html": PAGE, "file_path": str(page)}, {}, {"html": "x" * (artifacts.MAX_BYTES + 1)}, {"file_path": "relative.html"},
                 {"file_path": str(tmp_path / "p.txt")}, {"file_path": str(tmp_path / "missing.html")}, {"html": PAGE, "bogus": 1}):
        ok, out = call(manager, "task_manager_artifact_add", {"item": item, "title": "T", **args})
        assert not ok, args
    link = tmp_path / "link.html"
    link.symlink_to(page)
    assert not call(manager, "task_manager_artifact_add", {"item": item, "title": "T", "file_path": str(link)})[0]


def test_an_agent_reads_the_card_not_the_page(manager):
    store = huddle_store(manager)
    item = store.add("all", "work", actor="joe")["id"]
    call(manager, "task_manager_artifact_add", {"item": item, "title": "Mock", "description": "d", "html": PAGE})
    ok, out = call(manager, "task_manager_tasks_list", {"item": item})
    seen = [m for m in out["item"]["thread"] if m.get("artifact")]
    assert ok and seen[0]["artifact"] == {"title": "Mock", "description": "d"} and PAGE not in json.dumps(out)
