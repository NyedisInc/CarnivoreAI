
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.browser_pages import open_pages, select
from src.cplugs.huddle import artifact_ticket
from src.cplugs.reviewboard import opener, ticket, viewer
from src.cplugs.reviewboard.mcp import TOOLS
from src.cplugs.sdk import sandboxed_html, signed_links
from src.security_headers import OWN_POLICY_HEADER
from tests.python.cplugs.reviewboard.boards import PAGE, SIDECAR, make_board
from tests.python.cplugs.reviewboard.harness import BASE, Env, make_env

SLUG = SIDECAR["board"]["slug"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))
    monkeypatch.setattr(select.resource_push, "notify", lambda topic: None)
    monkeypatch.setattr(open_pages.resource_push, "notify", lambda topic: None)
    open_pages.reset_for_test()
    select.reset_for_test()
    yield
    open_pages.reset_for_test()
    select.reset_for_test()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    made = make_env(tmp_path)
    make_board(made.root)
    return made


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


def viewer_url(client: TestClient, revision: str = "r1", view: str = "main") -> str:
    answer = client.post(f"{BASE}/boards/{SLUG}/revisions/{revision}/ticket", json={"view": view})
    assert answer.status_code == 200, answer.text
    return answer.json()["url"]



def test_the_viewer_serves_the_page_under_the_sdk_sandbox_with_the_bridge_first(client: TestClient):
    r = client.get(viewer_url(client))
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == sandboxed_html.VIEW_CSP
    assert "allow-same-origin" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-disposition"] == 'inline; filename="r001.html"'
    body = r.content
    assert body.startswith(b"<!doctype html><script>") and b"data-rb-anchor='send'" in body
    assert body.endswith(PAGE[len(b"<!doctype html>"):])
    assert b"fetch(" not in body and b"XMLHttpRequest" not in body


def test_the_ticket_is_minted_with_a_bearer_and_the_viewer_needs_none(client: TestClient, env: Env):
    url = viewer_url(client)
    assert url.startswith("/api/v1/cplugs/reviewboard/view/")
    env.app.dependency_overrides.clear()
    with TestClient(env.app) as anonymous:
        assert anonymous.get(url).status_code == 200
        assert anonymous.post(f"{BASE}/boards/{SLUG}/revisions/r1/ticket", json={}).status_code in (401, 403)
        assert anonymous.post(f"{BASE}/boards/{SLUG}/open", json={}).status_code in (401, 403)


def test_a_forged_ticket_gets_404(client: TestClient, env: Env):
    url = viewer_url(client)
    good = url.rsplit("/", 1)[1]
    slug, rev, view, expiry, sig = good.split(".")
    base = f"{BASE}/view"
    forged = [
        f"{slug}.{rev}.{view}.{expiry}.{'A' * len(sig)}",
        f"{slug}.{rev}.{view}.{int(expiry) + 99}.{sig}",
        f"{slug}.r2.{view}.{expiry}.{sig}",
        f"{slug}.{rev}.journeys.{expiry}.{sig}",
        f"20261013-other.{rev}.{view}.{expiry}.{sig}",
        "garbage", "a.b.c", f"{slug}.{rev}.{view}.{expiry}", "",
        ticket.mint(slug, rev, view, now=time.time() - ticket.TTL_S - 5),
        signed_links.mint("huddle-artifact-ticket-v1", [slug, rev, view], 3600),
        artifact_ticket.mint(1, "ab12cd34"),
    ]
    env.app.dependency_overrides.clear()
    with TestClient(env.app) as anonymous:
        for bad in forged:
            assert anonymous.get(f"{base}/{bad}").status_code == 404, bad
        assert anonymous.get(f"{base}/{good}").status_code == 200


def test_a_good_ticket_for_a_page_that_is_not_there_gets_404(client: TestClient):
    assert client.get(f"{BASE}/view/{ticket.mint(SLUG, 'r7', 'main')}").status_code == 404
    assert client.get(f"{BASE}/view/{ticket.mint(SLUG, 'r1', 'journeys')}").status_code == 404
    assert client.get(f"{BASE}/view/{ticket.mint('20261013-nope', 'r1', 'main')}").status_code == 404


def test_a_page_changed_on_disk_is_refused_not_served(client: TestClient, env: Env):
    url = viewer_url(client)
    (env.root / SLUG / "r001.html").write_bytes(PAGE + b"<!-- edited -->")
    r = client.get(url)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_page_changed"


def test_a_symlinked_page_is_not_served(client: TestClient, env: Env, tmp_path: Path):
    url = viewer_url(client)
    page = env.root / SLUG / "r001.html"
    outside = tmp_path / "outside.html"
    outside.write_bytes(PAGE)
    page.unlink()
    page.symlink_to(outside)
    assert client.get(url).status_code == 404


def test_the_mint_route_refuses_an_unknown_revision_page_or_board(client: TestClient):
    assert client.post(f"{BASE}/boards/{SLUG}/revisions/r9/ticket", json={}).status_code == 404
    assert client.post(f"{BASE}/boards/{SLUG}/revisions/r1/ticket", json={"view": "journeys"}).status_code == 404
    assert client.post(f"{BASE}/boards/20261013-nope/revisions/r1/ticket", json={}).status_code == 404
    assert client.post(f"{BASE}/boards/{SLUG}/revisions/r1/ticket", json={"view": "x", "extra": 1}).status_code == 422
    assert client.post(f"{BASE}/boards/{SLUG}/revisions/r1/ticket").status_code == 200


def test_the_viewer_answers_409_while_the_plugin_is_off(env: Env, client: TestClient):
    url = viewer_url(client)
    from dataclasses import replace  # noqa: PLC0415
    from src.cplugs.host import runtime, state as owner_state  # noqa: PLC0415
    owner_state.update(env.host.state_dir, runtime.find("reviewboard").manifest, None, lambda st: replace(st, enabled=False))
    off = client.get(url)
    assert off.status_code == 409 and off.json()["detail"]["code"] == "cplug_disabled"



def test_inject_goes_first_in_head_and_has_a_fallback_for_every_page_shape():
    s = b"<script>S</script>"
    assert viewer.inject(b"<html><head></head></html>", s) == b"<html><head><script>S</script></head></html>"
    assert viewer.inject(b"<HEAD lang='x'><title>t</title>", s) == b"<HEAD lang='x'><script>S</script><title>t</title>"
    assert viewer.inject(b"<html lang='en'><body>b</body></html>", s) == b"<html lang='en'><head><script>S</script></head><body>b</body></html>"
    assert viewer.inject(b"<!DOCTYPE html><p>fragment</p>", s) == b"<!DOCTYPE html><script>S</script><p>fragment</p>"
    assert viewer.inject(b"<p>bare</p>", s) == b"<script>S</script><p>bare</p>"
    assert viewer.inject(b"<header>not a head</header>", s).startswith(b"<script>S</script>")


def test_the_bridge_only_points_and_checks_its_sender_and_its_values():
    text = viewer.BRIDGE_PATH.read_text(encoding="utf-8")
    assert "</script" not in text.lower()
    for needle in ("event.source !== window.parent", "data.rb !== VERSION", "setProperty", "MAX_BYTES"):
        assert needle in text
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "localStorage", "document.cookie", "eval(", "new Function"):
        assert forbidden not in text



def test_the_open_route_opens_a_page_row_for_the_pop_out_tab_and_selects_it(client: TestClient):
    r = client.post(f"{BASE}/boards/{SLUG}/open", json={"revision": "r1"})
    assert r.status_code == 200, r.text
    page = r.json()["page"]
    parts = urlsplit(page["src"])
    assert parts.path == "/static/popout.html" and page["frame"] == "app" and page["title"] == "bottom bar"
    assert parse_qs(parts.query) == {"tab": ["reviewboard"], "board": [SLUG], "rev": ["r1"]}
    assert r.json()["select"]["kind"] == "page" and r.json()["select"]["page_id"] == page["id"]
    assert [p.id for p in open_pages.listing()] == [page["id"]]
    again = client.post(f"{BASE}/boards/{SLUG}/open", json={"revision": "r1"}).json()["page"]
    assert again["id"] == page["id"]


def test_the_open_route_follows_the_newest_when_no_revision_is_named(client: TestClient):
    page = client.post(f"{BASE}/boards/{SLUG}/open").json()["page"]
    assert "rev" not in parse_qs(urlsplit(page["src"]).query)


def test_the_open_route_refuses_a_missing_board_or_revision(client: TestClient):
    assert client.post(f"{BASE}/boards/20261013-nope/open", json={}).status_code == 404
    assert client.post(f"{BASE}/boards/{SLUG}/open", json={"revision": "r9"}).status_code == 404
    assert client.post(f"{BASE}/boards/{SLUG}/open", json={"revision": "latest"}).status_code == 422
    assert open_pages.listing() == []


def test_the_page_path_encodes_what_it_is_given():
    assert opener.page_path(SLUG, "r2") == f"/static/popout.html?tab=reviewboard&board={SLUG}&rev=r2"


def test_the_app_header_stamp_keeps_the_viewer_policy_on_the_route_response(client: TestClient):
    from fastapi.responses import Response  # noqa: PLC0415
    from src.security_headers import stamp_security_headers  # noqa: PLC0415
    served = client.get(viewer_url(client))
    assert OWN_POLICY_HEADER.lower() in served.headers
    own = Response("x", headers={**sandboxed_html.view_headers("r001.html"), OWN_POLICY_HEADER: "1"})
    stamp_security_headers(own.headers)
    assert own.headers["content-security-policy"] == sandboxed_html.VIEW_CSP and OWN_POLICY_HEADER.lower() not in own.headers



def test_task_manager_board_focus_opens_the_board_and_is_in_the_family(env: Env):
    assert "task_manager_board_focus" in TOOLS and TOOLS["task_manager_board_focus"].gate == "agent"
    ok, out = env.call("task_manager_board_focus", {"board": SLUG, "revision": "r1"})
    assert ok, out
    assert out["page"]["title"] == "bottom bar" and out["select"]["kind"] == "page"
    assert parse_qs(urlsplit(out["page"]["src"]).query)["rev"] == ["r1"]
    ok, out = env.call("task_manager_board_focus", {"board": SLUG, "revision": "r9"})
    assert not ok and "no revision" in out
    ok, out = env.call("task_manager_board_focus", {"board": SLUG, "revision": "banana"})
    assert not ok and "revision id" in out
    ok, out = env.call("task_manager_board_focus", {})
    assert not ok and "board is required" in out
