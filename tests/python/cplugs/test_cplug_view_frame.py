
from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace

import pytest

from src.cplugs.host import identity, runtime, sidecar_registry
from tests.python.api_keys.conftest import bearer, client, owner_jwt  # noqa: F401

NAME, ITEM = "pet", "acme/pet"
VIEWS = [{"name": "walk", "surfaces": ["overlay", "panel"], "files": ["index.html", "pet.js", "pet.css", "art/pet.png", "art/logo.svg", "f.woff2"]}]
CPLUG = {"schema": 1, "id": NAME, "name": "Pet", "description": "A pet.", "version": "1.0.0", "entry": "main.py",
         "permissions": {"app": []}, "tools": [], "routes": ["feed"], "views": VIEWS}
APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; img-src 'self' data: blob:; "
           "font-src 'self' data:; frame-ancestors 'none';")


@pytest.fixture
def world(tmp_path, monkeypatch):
    from src.cplugs.sdk import signed_links
    from src.main import app

    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))
    state = tmp_path / "state"
    root = state / "cplug-code" / NAME
    (root / "views" / "walk" / "art").mkdir(parents=True)
    (root / "cplug.json").write_text(json.dumps(CPLUG))
    (root / "main.py").write_text("x = 1\n")
    v = root / "views" / "walk"
    (v / "index.html").write_text('<script src="pet.js"></script>')
    (v / "pet.js").write_text("window.x = 1")
    (v / "pet.css").write_text("body{}")
    (v / "art" / "pet.png").write_bytes(b"\x89PNG")
    (v / "art" / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (v / "f.woff2").write_bytes(b"wOF2")
    (v / "secret.js").write_text("not declared")
    record = identity.register_install(state, NAME, ITEM, {d.id for d in runtime.definitions()})
    (state / "cplugs" / record.uuid).mkdir(parents=True, exist_ok=True)
    (state / "cplugs" / record.uuid / "views.js").write_text("the data dir")
    rows = [SimpleNamespace(item_id=ITEM, kind="cplug", source_index_url="https://index.example/v1")]
    before = sidecar_registry.current()
    sidecar_registry.install(sidecar_registry.SidecarRegistry(state, lambda: rows))
    assert sidecar_registry.current().reload() == 1 and sidecar_registry.find(NAME).manifest.views[0]["name"] == "walk"
    flag = {"on": True, "state": "running", "safe": {"off": False}}
    app.state.cplugs_host = runtime.Host(state, app)
    app.state.sidecar_runtime = SimpleNamespace(safe_mode=lambda: flag["safe"], supervisor=SimpleNamespace(state=lambda name: flag["state"]))
    monkeypatch.setattr(runtime.Host, "enabled", lambda self, cid: flag["on"] if cid == NAME else False)
    yield SimpleNamespace(root=root, state=state, flag=flag, key=record.uuid)
    del app.state.cplugs_host
    del app.state.sidecar_runtime
    sidecar_registry.install(before)


def ticket(client, jwt, name="walk"):  # noqa: F811
    r = client.post(f"/api/v1/cplugs/{NAME}/view/{name}/ticket", headers=bearer(jwt))
    assert r.status_code == 200, r.text
    return r.json()["path"].rsplit("/", 1)[0] + "/", r.json()["path"]


def test_a_declared_file_is_served_with_the_exact_view_policy_and_a_fixed_type(client, owner_jwt, world):  # noqa: F811
    base, index = ticket(client, owner_jwt)
    r = client.get(index)
    assert r.status_code == 200 and r.content == b'<script src="pet.js"></script>'
    own = f"http://testserver{base}"
    assert r.headers["content-security-policy"] == (
        f"default-src 'none'; script-src {own}; style-src {own} 'unsafe-inline'; connect-src 'none'; img-src 'self' data: blob:; "
        f"font-src {own}; frame-ancestors 'self'; sandbox allow-scripts;")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert "x-carnivore-own-policy" not in r.headers and r.headers["content-type"] == "text/html; charset=utf-8"
    kinds = {"pet.js": "text/javascript; charset=utf-8", "pet.css": "text/css; charset=utf-8", "art/pet.png": "image/png",
             "art/logo.svg": "image/svg+xml", "f.woff2": "font/woff2"}
    for rel, kind in kinds.items():
        got = client.get(base + rel, headers={"sec-fetch-dest": "image" if rel.endswith("svg") else "script"})
        assert got.status_code == 200 and got.headers["content-type"] == kind, rel
    assert client.get(base + "art/logo.svg", headers={"sec-fetch-dest": "iframe"}).status_code == 404


def test_the_apps_own_csp_is_byte_identical_and_the_view_route_does_not_leak_its_policy(client, owner_jwt, world):  # noqa: F811
    assert client.get("/api/v1/cplugs", headers=bearer(owner_jwt)).headers["content-security-policy"] == APP_CSP
    assert client.get("/api/v1/cplugs").headers["content-security-policy"] == APP_CSP
    assert client.post(f"/api/v1/cplugs/{NAME}/view/walk/ticket", headers=bearer(owner_jwt)).headers["content-security-policy"] == APP_CSP


def test_only_declared_files_of_the_view_in_the_code_root_are_served(client, owner_jwt, world):  # noqa: F811
    base, _ = ticket(client, owner_jwt)
    assert client.get(base + "secret.js").status_code == 404
    assert client.get(base + "cplug.json").status_code == 404 and client.get(base + "../../cplug.json").status_code == 404
    assert client.get(base + "..%2F..%2Fcplug.json").status_code == 404 and client.get(base + "%2e%2e/main.py").status_code == 404
    assert client.get(base + "views.js").status_code == 404
    (world.root / "views" / "walk" / "pet.js").unlink()
    (world.root / "views" / "walk" / "pet.js").symlink_to(world.root / "main.py")
    assert client.get(base + "pet.js").status_code == 404
    (world.root / "views" / "walk" / "art").rename(world.root / "views" / "walk" / "art-real")
    (world.root / "views" / "walk" / "art").symlink_to(world.root / "views" / "walk" / "art-real")
    assert client.get(base + "art/pet.png").status_code == 404
    assert client.get(base + "index.html").status_code == 200


def test_a_bad_ticket_a_ticket_for_another_view_or_install_and_a_view_not_declared_are_404(client, owner_jwt, world):  # noqa: F811
    base, _ = ticket(client, owner_jwt)
    good = base.rstrip("/").rsplit("/", 1)[1]
    other = f"/api/v1/cplugs/{NAME}/view/other/{good}/index.html"
    assert client.get(other).status_code == 404
    assert client.get(f"/api/v1/cplugs/{NAME}/view/walk/{good}x/index.html").status_code == 404
    assert client.get(f"/api/v1/cplugs/{NAME}/view/walk/nope/index.html").status_code == 404
    assert client.get(f"/api/v1/cplugs/huddle/view/walk/{good}/index.html").status_code == 404
    assert client.post(f"/api/v1/cplugs/{NAME}/view/other/ticket", headers=bearer(owner_jwt)).status_code == 404
    assert client.post(f"/api/v1/cplugs/{NAME}/view/walk/ticket").status_code in (401, 403)
    identity.release_install(world.state, NAME)
    new = identity.register_install(world.state, NAME, ITEM, {d.id for d in runtime.definitions()})
    assert new.uuid != world.key and client.get(base + "index.html").status_code == 404


def test_a_plugin_that_is_off_or_held_answers_409_for_the_file_and_the_ticket(client, owner_jwt, world):  # noqa: F811
    base, _ = ticket(client, owner_jwt)
    world.flag["on"] = False
    for r in (client.get(base + "index.html"), client.post(f"/api/v1/cplugs/{NAME}/view/walk/ticket", headers=bearer(owner_jwt))):
        assert r.status_code == 409 and r.json()["detail"]["code"] == "cplug_disabled"
    world.flag["on"] = True
    for state in ("revoked", "crash_loop", "disabled"):
        world.flag["state"] = state
        assert client.get(base + "index.html").status_code == 409, state
    world.flag["state"] = "running"
    world.flag["safe"] = {"owner": True}
    assert client.get(base + "index.html").status_code == 409
    world.flag["safe"] = {"off": False}
    assert client.get(base + "index.html").status_code == 200


def test_the_manifest_refuses_a_view_that_could_reach_outside_its_folder():
    from src.cplugs.host.sidecar_manifest import SidecarManifestError, parse_sidecar_manifest

    def parse(views):
        return parse_sidecar_manifest({**CPLUG, "views": views}, NAME, "d")

    assert parse(VIEWS).views[0]["files"][0] == "index.html"
    for bad in ([{"name": "w", "surfaces": ["panel"], "files": ["../x.js", "index.html"]}], [{"name": "w", "surfaces": ["panel"], "files": ["/etc/passwd.js", "index.html"]}],
                [{"name": "w", "surfaces": ["panel"], "files": ["index.html", "a.exe"]}], [{"name": "w", "surfaces": ["panel"], "files": ["pet.js"]}],
                [{"name": "w", "surfaces": ["page"], "files": ["index.html"]}], [{"name": "W", "surfaces": ["panel"], "files": ["index.html"]}],
                [{"name": "w", "surfaces": ["panel"], "files": ["index.html"], "extra": 1}], [{"name": "w", "surfaces": ["panel"], "files": ["index.html", "html"]}]):
        with pytest.raises(SidecarManifestError):
            parse(bad)


def test_a_fifo_at_a_declared_path_is_refused_without_blocking(world):  # noqa: F811
    from src.cplugs.host import sidecar_view

    fifo = world.root / "views" / "walk" / "fifo.js"
    os.mkfifo(fifo)
    out: list = []
    worker = threading.Thread(target=lambda: out.append(sidecar_view._file(world.root, "walk", {"files": ["fifo.js"]}, "fifo.js")), daemon=True)
    worker.start()
    worker.join(3)
    blocked = worker.is_alive()
    if blocked:
        fd = os.open(fifo, os.O_WRONLY)
        os.close(fd)
        worker.join(3)
    assert not blocked, "opening a fifo blocked the read"
    assert out == [None]


def test_the_view_policy_names_its_residual_network_channels():
    from src.security_headers import build_view_csp

    doc = build_view_csp.__doc__ or ""
    assert "WebRTC" in doc and "self-navigation" in doc and "will-frame-navigate" in doc
