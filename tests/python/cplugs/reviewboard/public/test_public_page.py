
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from src.cplugs.reviewboard.public import assets, routes
from tests.python.cplugs.reviewboard.public.read_harness import edge, get

REPO = Path(__file__).resolve().parents[5]
OWNER_ROUTES = ("/api/v1/cplugs/reviewboard/public/links", "/api/v1/cplugs/reviewboard/public/status", "/api/v1/cplugs/reviewboard/boards",
                "/api/v1/auth/login", "/login", "/static/dist/app.js", "/static/popout.html")


def test_the_shell_loads_exactly_the_two_built_files_and_nothing_inline(read_env) -> None:
    html = get(edge(), "/").body.decode()
    assert re.findall(r'<script[^>]*>', html) == ['<script src="/publicboard.js">']
    assert re.findall(r'<link[^>]*>', html) == ['<link rel="stylesheet" href="/publicboard.css">']
    assert '<div id="board">' in html or 'id="board"' in html
    assert "style=" not in html and "onload" not in html and "http://" not in html and "https://" not in html


def test_the_page_and_its_files_wear_the_strict_csp_and_no_store(read_env) -> None:
    csp = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self'; "
           "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
    for path in ("/", "/publicboard.js", "/publicboard.css"):
        got = get(edge(), path)
        assert got.status == 200, path
        assert got.headers["content-security-policy"] == csp, path
        assert got.headers["cache-control"] == "no-store" and got.headers["x-content-type-options"] == "nosniff", path
        assert got.headers["referrer-policy"] == "no-referrer" and "set-cookie" not in got.headers, path
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "http" not in csp


def test_the_files_come_from_client_dist_and_a_missing_one_is_the_fixed_503(read_env, monkeypatch, tmp_path) -> None:
    assert assets.DIST_DIR != REPO / "client" / "dist"
    assert get(edge(), "/publicboard.js").body == b"/* stand-in visitor script */\n"
    monkeypatch.setattr(assets, "DIST_DIR", tmp_path / "empty")
    got = get(edge(), "/publicboard.js")
    assert got.status == 503 and got.json() == {"state": "unavailable"}


def test_the_real_dist_dir_is_the_apps_client_dist() -> None:
    from src.core.static_asset_keys import DEFAULT_CLIENT_DIR

    assert assets.DIST_DIR == DEFAULT_CLIENT_DIR / "dist"


def test_the_old_shell_files_are_gone_and_name_no_route(read_env) -> None:
    assert not (Path(assets.__file__).with_name("page") / "app.js").exists()
    assert not (Path(assets.__file__).with_name("page") / "app.css").exists()
    for path in ("/app.js", "/app.css"):
        assert get(edge(), path).status == 404


def test_the_page_cannot_reach_an_owner_route_through_its_own_listener(read_env, store) -> None:
    from tests.python.cplugs.reviewboard.public.read_harness import mint_token

    token = mint_token(store)
    for path in OWNER_ROUTES:
        for presented in (None, token):
            assert get(edge(), path, presented).status == 404, path
    served = {path for _, path in routes.ROUTES}
    assert not [p for p in served if p.startswith("/api/v1")]


def test_the_file_names_the_table_serves_are_the_two_the_build_emits() -> None:
    assert {name for where, name, _ in assets.FILES.values() if where == "dist"} == {"reviewboard-public.js", "reviewboard-public.css"}
    scripts = json.loads((REPO / "web" / "package.json").read_text())["scripts"]
    assert "build-plugin-bundles.mjs" in scripts["build"] and (REPO / "web" / "src" / "cplugs" / "reviewboard" / "vite.bundle.config.ts").is_file()


def test_the_board_answer_names_no_newer_revision_and_says_how_long_the_frames_last(read_env, store) -> None:
    from tests.python.cplugs.reviewboard.public.read_harness import add_revision, mint_token

    pinned, follow = mint_token(store), mint_token(store, mode="follow")
    add_revision(read_env.root / "20261013-bottom-bar", b"<html><body>second</body></html>")
    for token in (pinned, follow):
        body = get(edge(), "/api/board", token).json()
        assert "latest" not in body and "follows" not in body
        assert "r2" not in json.dumps(body) or body["revision"] == "r2"
        assert body["frame_ttl"] == 300


def test_the_frame_lifetime_in_the_answer_is_the_one_the_tickets_are_minted_with(read_env, store, monkeypatch) -> None:
    from types import SimpleNamespace

    from src.cplugs.reviewboard.public import wiring
    from src.cplugs.reviewboard.public.read import READER
    from tests.python.cplugs.reviewboard.public.read_harness import mint_token

    monkeypatch.setattr(wiring, "TICKET_TTL_S", 7)
    READER.bind(wiring.build(SimpleNamespace(storage=store)))
    body = get(edge(), "/api/board", mint_token(store)).json()
    assert body["frame_ttl"] == 7
    ticket = body["views"][0]["frame"].removeprefix("/f/")
    assert int(ticket.split(".")[3]) - int(time.time()) <= 7


def test_an_edited_client_file_is_served_at_once_without_a_restart(read_env, tmp_path, monkeypatch) -> None:
    dist = assets.DIST_DIR
    assert get(edge(), "/publicboard.js").body == b"/* stand-in visitor script */\n"
    (dist / "reviewboard-public.js").write_bytes(b"/* a newer visitor script, longer */\n")
    assert get(edge(), "/publicboard.js").body == b"/* a newer visitor script, longer */\n"
    (dist / "reviewboard-public.js").write_bytes(b"/* another one, same size.. */\n".ljust(36, b" ")[:36])
    assert get(edge(), "/publicboard.js").body.startswith(b"/* another one")


def test_the_shell_says_something_useful_when_the_script_never_loads() -> None:
    html = (Path(assets.__file__).with_name("page") / "index.html").read_text()
    assert re.search(r'<div id="board">\s*<p class="pb-note">[^<]*loading[^<]*tell the person who sent you the link', html)
    assert re.search(r"<noscript>.*javascript", html, re.S)
    assert len(re.findall(r"<script", html)) == 1 and "<style" not in html


def test_the_eval_pattern_the_bundle_check_uses_is_the_repos_own() -> None:
    from tests.test_no_remote_assets import _EVAL_SHAPED

    source = (REPO / "web" / "src" / "cplugs" / "reviewboard" / "public" / "visitor-page" / "owner-routes.test.ts").read_text()
    assert f"const EVAL_SHAPED = /{_EVAL_SHAPED.pattern}/;" in source
