
from __future__ import annotations

import asyncio
from pathlib import Path


from src.cplugs.host import runtime
from src.cplugs.reviewboard import CPLUG
from src.cplugs.reviewboard.routes import router
from src.cplugs.reviewboard.public import availability
from src.cplugs.reviewboard.public.service import SERVICE
from tests.python.cplugs.reviewboard.harness import BASE, make_env
from tests.python.cplugs.reviewboard.public.carry_fixtures import make_old_folder
from tests.python.cplugs.reviewboard.public.test_public_links_switch_support import client_for, set_public

STATUS = f"{BASE}/public/status"


def test_the_manifest_carries_the_switch_off_by_default_and_the_moved_fields() -> None:
    manifest = CPLUG.manifest
    fields = manifest.settings_schema["fields"]
    assert fields["publicLinksEnabled"]["kind"] == "boolean" and fields["publicLinksEnabled"]["default"] is False
    assert {"port", "bindAddress", "hostnames", "trustedProxies"} <= set(fields) and fields["port"]["default"] == 8190
    assert "notify" in manifest.permissions and "visitors" in manifest.surfaces.topics
    assert manifest.legacy_ids == {"publicboard": "publicLinksEnabled"}
    assert runtime.find("publicboard") is None


def test_off_nothing_answers_and_no_listener_runs(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    client = client_for(env)
    assert client.get(STATUS).status_code == 404
    assert client.get(f"{BASE}/public/links").status_code == 404
    assert client.post(f"{BASE}/public/links", json={"board": "x", "ttl": "1h"}).status_code == 404
    assert client.get(f"{BASE}/boards").status_code == 200
    asyncio.run(CPLUG.on_start(env.host.context("reviewboard", background=True)))
    try:
        assert SERVICE.listener is None
    finally:
        asyncio.run(CPLUG.on_stop(env.host.context("reviewboard", background=True)))


def test_on_the_routes_answer(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    set_public(env, True)
    body = client_for(env).get(STATUS)
    assert body.status_code == 200 and body.json()["available"] is True


def test_on_with_a_refused_carry_the_plugin_still_starts_and_reports_unavailable(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    old = make_old_folder(env.host.state_dir / "cplugs" / "publicboard")
    (old / "links.db").write_bytes(b"corrupt" * 100)
    set_public(env, True, hostnames="a.example.test", trustedProxies="203.0.113.11")
    ctx = env.host.context("reviewboard", background=True)
    asyncio.run(CPLUG.on_start(ctx))
    try:
        assert SERVICE.listener is None
        shown = client_for(env).get(STATUS).json()
        assert shown["available"] is False and shown["unavailable_reason"] == "unreadable_source"
        assert client_for(env).get(f"{BASE}/boards").status_code == 200
    finally:
        asyncio.run(CPLUG.on_stop(ctx))
        availability.AVAILABILITY.clear()


API_PREFIX = "/api/v1"


def public_owner_routes() -> list:
    found = []
    for route in router.routes:
        path = getattr(route, "path", "")
        if "/public/" not in path:
            continue
        filled = path.replace("{link_id}", "x").replace("{number}", "1").replace("{response_id}", "1")
        found += [(method, API_PREFIX + filled) for method in sorted(route.methods)]
    assert len(found) >= 12, found
    return found


def sweep(client, env) -> dict:
    out = {}
    for method, url in public_owner_routes():
        got = client.request(method, url, params={"board": "20261013-bar", "revision": "r1"}, json={"board": "20261013-bar", "ttl": "1h", "all": True})
        detail = got.json().get("detail") if got.headers.get("content-type", "").startswith("application/json") else None
        out[(method, url)] = (got.status_code, detail.get("code", "") if isinstance(detail, dict) else "")
    return out


def test_the_sweep_can_see_an_answer_when_the_routes_are_on(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    set_public(env, True)
    assert "public_links_off" not in {code for _status, code in sweep(client_for(env), env).values()}


def test_off_every_one_of_the_owner_routes_answers_404(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    codes = sweep(client_for(env), env)
    assert set(codes.values()) == {(404, "public_links_off")}, codes


def test_while_the_carry_is_refused_every_route_but_status_answers_503_and_status_says_why(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    set_public(env, True)
    availability.AVAILABILITY.set("source_busy")
    try:
        client = client_for(env)
        codes = sweep(client, env)
        status = {key: got for key, got in codes.items() if key[1].endswith("/public/status")}
        assert status and {got[0] for got in status.values()} == {200}
        assert {got for key, got in codes.items() if key not in status} == {(503, "public_links_unavailable")}, codes
        shown = client.get(STATUS).json()
        assert shown["available"] is False and shown["unavailable_reason"] == "source_busy"
        body = client.post(f"{BASE}/public/links", json={"board": "20261013-bar", "ttl": "1h"}).json()
        assert body["detail"]["code"] == "public_links_unavailable"
        assert not (env.host.state_dir / "cplugs" / "reviewboard" / "links.db").exists(), "a refused mint must not create the store that the carry reads as in the way"
    finally:
        availability.AVAILABILITY.clear()
