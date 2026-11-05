
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import string
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
import structlog

from src.cplugs.publicboard import links, minting
from src.cplugs.publicboard.read import READER
from src.cplugs.publicboard.resolve import Resolver
from src.cplugs.sdk import CplugSchemaError, signed_links
from src.cplugs.sdk.sandboxed_html import VIEW_CSP
from tests.python.cplugs.publicboard.read_harness import add_revision, edge, get, mint_token, rewrite
from tests.python.cplugs.reviewboard.boards import PAGE

SLUG = "20261013-bottom-bar"
FAKE_KEY = "ghp_" + "".join(random.Random(2696).choices(string.ascii_letters + string.digits, k=36))


def shape(answer: Any) -> tuple:
    return (answer.status, tuple(sorted(k for k in answer.headers if k != "date")), tuple(sorted(answer.json())))


def test_the_shell_and_assets_are_served_with_the_strict_headers(read_env) -> None:
    for path, kind in (("/", "text/html"), ("/app.js", "text/javascript"), ("/app.css", "text/css")):
        got = get(edge(), path)
        assert got.status == 200 and got.headers["content-type"].startswith(kind), path
        assert got.headers["cache-control"] == "no-store" and "default-src 'self'" in got.headers["content-security-policy"]
        assert got.headers["x-content-type-options"] == "nosniff" and "set-cookie" not in got.headers
    assert b"script-src" not in get(edge(), "/").body and b"<script>" not in get(edge(), "/").body


def test_the_board_answer_is_json_no_store_and_locked(read_env, store) -> None:
    got = get(edge(), "/api/board", mint_token(store))
    assert got.headers["content-type"] == "application/json" and got.headers["cache-control"] == "no-store"
    assert got.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert not [h for h in got.headers if h.startswith("access-control")]


def test_a_capability_in_a_query_or_a_path_is_refused(read_env, store) -> None:
    token = mint_token(store)
    assert get(edge(), "/api/board", query=f"t={token}".encode()).status == 400
    assert get(edge(), "/api/board", token, query=b"x=1").status == 400
    for path in (f"/api/board/{token}", f"/f/{token}", f"/{token}"):
        assert get(edge(), path).status == 404


def test_the_app_jwt_and_other_credentials_are_not_a_capability(read_env, store) -> None:
    token = mint_token(store)
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2UifQ.c2lnbmF0dXJlLW5vdC1yZWFs"
    refused = get(edge(), "/api/board", jwt)
    assert refused.status == 404 and refused.json() == {"state": "invalid"}
    bearer = get(edge(), "/api/board", None, extra=(("Authorization", f"Bearer {token}"), ("Cookie", f"carnivore_token={token}")))
    assert bearer.status == 404 and bearer.json() == {"state": "invalid"}
    assert get(edge(), "/api/board", f"Bearer {token}").json() == {"state": "invalid"}


def test_two_copies_of_the_header_are_no_capability(read_env, store) -> None:
    token = mint_token(store)
    got = get(edge(), "/api/board", token, extra=(("Carnivore-Board-Link", token),))
    assert got.json() == {"state": "invalid"}


def test_invalid_unknown_wrong_secret_and_ended_share_one_shape(read_env, store) -> None:
    token = mint_token(store)
    link_id, secret = token.removeprefix("pbl_").split(".")
    wrong = f"pbl_{link_id}." + ("A" * 43)
    unknown = "pbl_" + ("B" * 22) + "." + secret
    app = edge()
    seen = [get(app, "/api/board", t) for t in (None, "garbage", wrong, unknown)]
    assert len({shape(a) for a in seen}) == 1 and {a.json()["state"] for a in seen} == {"invalid"}
    links.revoke_link(store, link_id)
    ended = get(app, "/api/board", token)
    assert ended.json() == {"state": "ended"} and shape(ended) == shape(seen[0])
    assert get(app, "/api/board", wrong).json() == {"state": "invalid"}


def test_every_refusal_path_runs_the_constant_time_check(read_env, store, monkeypatch) -> None:
    calls: List[str] = []
    real = links.check
    monkeypatch.setattr(links, "check", lambda storage, token, now=None: calls.append(token) or real(storage, token, now))
    for header in (None, "garbage", "pbl_" + "B" * 22 + "." + "C" * 43):
        get(edge(), "/api/board", header)
    assert len(calls) == 3


def test_an_expired_link_is_ended(read_env, store) -> None:
    token = mint_token(store, ttl="1h")
    link_id = token.removeprefix("pbl_").split(".")[0]
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE links SET expires_at = 1 WHERE id = ?", (link_id,))
    assert get(edge(), "/api/board", token).json() == {"state": "ended"}


def test_a_page_edited_behind_the_link_ends_it_even_with_the_sidecar_rewritten(read_env, store, folder: Path) -> None:
    token = mint_token(store)
    assert get(edge(), "/api/board", token).status == 200
    page = PAGE + b"<p>changed after the scan</p>"
    (folder / "r001.html").write_bytes(page)

    def fix(raw: Any) -> None:
        view = raw["revisions"][0]["views"][0]
        view["sha256"], view["bytes"] = hashlib.sha256(page).hexdigest(), len(page)

    rewrite(folder, fix)
    assert get(edge(), "/api/board", token).json() == {"state": "ended"}


def test_a_page_that_no_longer_matches_the_sidecar_ends_it(read_env, store, folder: Path) -> None:
    token = mint_token(store)
    (folder / "r001.html").write_bytes(PAGE + b"x")
    assert get(edge(), "/api/board", token).json() == {"state": "ended"}


def test_a_renamed_board_ends_a_pinned_link(read_env, store, folder: Path) -> None:
    token = mint_token(store)
    rewrite(folder, lambda raw: raw["board"].update(title="a different title"))
    assert get(edge(), "/api/board", token).json() == {"state": "ended"}


def test_a_deleted_board_ends_the_link(read_env, store, folder: Path) -> None:
    token = mint_token(store)
    for child in folder.iterdir():
        child.unlink()
    folder.rmdir()
    assert get(edge(), "/api/board", token).json() == {"state": "ended"}


def test_the_frame_serves_the_scanned_page_under_the_view_csp_and_a_revoke_kills_it(read_env, store) -> None:
    token = mint_token(store)
    app = edge()
    url = get(app, "/api/board", token).json()["views"][0]["frame"]
    page = get(app, url)
    assert page.status == 200 and page.headers["content-security-policy"] == VIEW_CSP and page.headers["cache-control"] == "no-store"
    assert page.headers["content-type"].startswith("text/html") and b"data-rb-anchor" in page.body and b"<script>" in page.body
    links.revoke_link(store, token.removeprefix("pbl_").split(".")[0])
    dead = get(app, url)
    assert dead.status == 404 and dead.json() == {"state": "ended"}


def test_a_tampered_or_foreign_or_expired_ticket_serves_nothing(read_env, store, monkeypatch) -> None:
    token = mint_token(store)
    app = edge()
    url = get(app, "/api/board", token).json()["views"][0]["frame"]
    flipped = url[:-1] + ("A" if url[-1] != "A" else "B")
    link_id = token.removeprefix("pbl_").split(".")[0]
    foreign = "/f/" + signed_links.mint("some-other-label", [link_id, "r1", "main"], 300)
    old = "/f/" + signed_links.mint("publicboard-frame-v1", [link_id, "r1", "main"], 300, now=1)
    for path in (flipped, foreign, old):
        assert get(app, path).status == 404, path


def test_a_frame_needs_no_header_but_the_ticket_alone_never_opens_a_wrong_view(read_env, store) -> None:
    token = mint_token(store)
    link_id = token.removeprefix("pbl_").split(".")[0]
    other_view = "/f/" + signed_links.mint("publicboard-frame-v1", [link_id, "r1", "nope"], 300)
    assert get(edge(), other_view).status == 404


def test_a_pinned_link_never_moves_but_a_follow_link_does_after_a_clean_scan(read_env, store, folder: Path) -> None:
    pinned, follow = mint_token(store), mint_token(store, mode="follow")
    assert add_revision(folder, PAGE + b"<p>second</p>") == "r2"
    app = edge()
    assert get(app, "/api/board", pinned).json()["revision"] == "r1"
    moved = get(app, "/api/board", follow).json()
    assert moved["revision"] == "r2" and moved["summary"] == "second pass"
    (row,) = [r for r in links.list_links(store) if r.mode == "follow"]
    assert row.revision == "r2"
    assert get(app, moved["views"][0]["frame"]).status == 200
    assert b"second" in get(app, moved["views"][0]["frame"]).body


def test_a_follow_link_refuses_a_newer_revision_that_holds_a_secret_and_scans_it_once(read_env, store, folder: Path, monkeypatch) -> None:
    follow = mint_token(store, mode="follow")
    add_revision(folder, PAGE + f"<!-- {FAKE_KEY} -->".encode())
    scans: List[int] = []
    real = minting.scan_texts
    monkeypatch.setattr(minting, "scan_texts", lambda texts: scans.append(1) or real(texts))
    app = edge()
    for _ in range(3):
        got = get(app, "/api/board", follow)
        assert got.status == 200 and got.json()["revision"] == "r1"
        assert FAKE_KEY not in got.body.decode()
    assert len(scans) == 1, "the refused revision is remembered, not rescanned on every request"
    (row,) = links.list_links(store)
    assert row.revision == "r1"


def test_a_follow_link_whose_newer_scan_cannot_finish_keeps_the_cleared_revision(read_env, store, folder: Path, monkeypatch) -> None:
    from src.cplugs.sdk.file_secrets import ScanTimeout

    follow = mint_token(store, mode="follow")
    add_revision(folder, PAGE + b"<p>new</p>")

    def boom(texts: Any) -> Any:
        raise ScanTimeout()

    monkeypatch.setattr(minting, "scan_texts", boom)
    assert get(edge(), "/api/board", follow).json()["revision"] == "r1"


@pytest.mark.parametrize("error", [sqlite3.OperationalError("disk I/O error at /secret/path"), CplugSchemaError("newer than this build /secret/path")])
def test_a_store_failure_is_the_fixed_503_with_nothing_of_the_error(read_env, store, monkeypatch, error: Exception) -> None:
    token = mint_token(store)

    def broken(*args: Any, **kw: Any) -> Any:
        raise error

    monkeypatch.setattr(links, "check", broken)
    got = get(edge(), "/api/board", token)
    assert got.status == 503 and got.json() == {"state": "unavailable"} and b"secret/path" not in got.body and b"Traceback" not in got.body


def test_a_store_failure_on_a_frame_and_a_missing_signing_key_are_503(read_env, store, monkeypatch) -> None:
    token = mint_token(store)
    app = edge()
    url = get(app, "/api/board", token).json()["views"][0]["frame"]
    monkeypatch.setattr(links, "active", lambda *a, **k: (_ for _ in ()).throw(sqlite3.DatabaseError("x")))
    assert get(app, url).status == 503
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="")))
    assert get(app, "/api/board", token).status == 503


def test_an_unbound_reader_and_a_board_that_is_off_answer_503(read_env, store) -> None:
    from src.cplugs.reviewboard import public_port

    token = mint_token(store)
    public_port.unregister()
    assert get(edge(), "/api/board", token).json() == {"state": "unavailable"}
    READER.unbind()
    assert get(edge(), "/api/board", token).json() == {"state": "unavailable"}
    assert get(edge(), "/f/" + "A" * 22 + ".r1.main." + "1" * 10 + "." + "B" * 43).json() == {"state": "unavailable"}


def test_the_client_limit_is_per_right_most_forwarded_address(read_env, store) -> None:
    token = mint_token(store)
    app = edge()
    mine = (("X-Forwarded-For", "198.51.100.7"),)
    answers = [get(app, "/api/board", token, extra=mine).status for _ in range(61)]
    assert answers[:60] == [200] * 60 and answers[60] == 429
    limited = get(app, "/api/board", token, extra=mine)
    assert limited.json() == {"state": "limited"} and limited.headers["retry-after"]
    forged_left = (("X-Forwarded-For", "9.9.9.9, 198.51.100.7"),)
    assert get(app, "/api/board", token, extra=forged_left).status == 429, "a forged left-hand entry buys no fresh budget"
    assert get(app, "/api/board", token, extra=(("X-Forwarded-For", "198.51.100.8"),)).status == 200


def test_garbage_is_charged_to_the_client_and_never_to_a_links_budget(read_env, store) -> None:
    token = mint_token(store)
    link_id, _ = token.removeprefix("pbl_").split(".")
    READER.resolver = Resolver(READER.resolver.deps, per_client=1000, per_link=3)
    app = edge()
    for _ in range(10):
        assert get(app, "/api/board", f"pbl_{link_id}." + "A" * 43).json() == {"state": "invalid"}
    assert [get(app, "/api/board", token).status for _ in range(4)] == [200, 200, 200, 429]


def test_the_peer_must_be_the_trusted_proxy_and_the_header_names_nobody(read_env, store) -> None:
    assert get(edge(), "/api/board", mint_token(store), peer="198.51.100.200").status == 403


def test_no_log_line_carries_the_token_the_secret_or_the_hash(read_env, store, folder: Path) -> None:
    token = mint_token(store)
    link_id, secret = token.removeprefix("pbl_").split(".")
    with structlog.testing.capture_logs() as logs:
        app = edge()
        get(app, "/api/board", token)
        get(app, "/api/board", f"pbl_{link_id}." + "A" * 43)
        links.revoke_link(store, link_id)
        get(app, "/api/board", token)
        (folder / "r001.html").write_bytes(b"x")
    blob = json.dumps(logs, default=str)
    assert secret not in blob and token not in blob and hashlib.sha256(secret.encode()).hexdigest() not in blob
