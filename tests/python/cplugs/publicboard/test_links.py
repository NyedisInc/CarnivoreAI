
from __future__ import annotations

import asyncio
import copy
import dataclasses
import hashlib
import random
import sqlite3
import stat
import string
from pathlib import Path
from typing import Any, Iterator, List, get_args

import pytest
import structlog
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import runtime, system_lifecycle
from src.cplugs.publicboard import CPLUG, links, mcp as board_mcp, routes_owner
from src.cplugs.reviewboard import document, public_port
from src.cplugs.sdk import board_public
from tests.python.cplugs.owner import turn_on
from tests.python.cplugs.reviewboard.boards import PAGE, SIDECAR, make_board
from tests.python.cplugs.reviewboard.harness import PANE, Env, make_env

BASE = "/api/v1/cplugs/publicboard/links"
SLUG = SIDECAR["board"]["slug"]
FAKE_KEY = "ghp_" + "".join(random.Random(2696).choices(string.ascii_letters + string.digits, k=36))
NOW = 1_800_000_000


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    made = make_env(tmp_path)
    turn_on(made.host, "publicboard")
    made.app.include_router(routes_owner.router, prefix="/api/v1")
    public_port.register(made.host.context("reviewboard", background=True))
    make_board(made.root)
    yield made
    public_port.unregister()


@pytest.fixture
def client(env: Env) -> Iterator[TestClient]:
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


@pytest.fixture
def storage(env: Env) -> Any:
    return env.host.storage("publicboard")


def add_leaky_board(env: Env) -> str:
    page = PAGE + f"<!-- {FAKE_KEY} -->\n".encode()
    raw = copy.deepcopy(SIDECAR)
    raw["board"]["slug"] = "20261014-leaky"
    raw["task"] = None
    view = raw["revisions"][0]["views"][0]
    view["sha256"], view["bytes"] = hashlib.sha256(page).hexdigest(), len(page)
    raw["rounds"] = []
    folder = make_board(env.root, raw)
    (folder / "r001.html").write_bytes(page)
    return raw["board"]["slug"]


def mint(client: TestClient, **over: Any) -> Any:
    return client.post(BASE, json={"board": SLUG, "ttl": "1d", **over})


def rows(storage: Any) -> List[sqlite3.Row]:
    conn = sqlite3.connect(storage.db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM links"))
    finally:
        conn.close()


def test_mint_returns_the_secret_once_and_the_store_holds_only_its_hash(client, storage) -> None:
    r = mint(client)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    link_id, secret = token.removeprefix("pbl_").split(".")
    (row,) = rows(storage)
    assert row["id"] == link_id and row["secret_hash"] == hashlib.sha256(secret.encode()).hexdigest()
    assert token not in str(dict(row)) and secret not in str(dict(row))
    assert not [p for p in storage.path.rglob("*") if p.is_file() and secret.encode() in p.read_bytes()]
    listed = client.get(BASE).json()["links"]
    assert [x["id"] for x in listed] == [link_id] and secret not in client.get(BASE).text and "secret_hash" not in client.get(BASE).text


def test_the_file_and_folder_are_closed_to_other_users(client, storage) -> None:
    mint(client)
    assert stat.S_IMODE(storage.db_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(storage.path.stat().st_mode) == 0o700


def test_check_tells_invalid_from_ended_only_for_a_proven_secret(client, storage) -> None:
    token = mint(client, ttl="1h").json()["token"]
    link_id, secret = token.removeprefix("pbl_").split(".")
    now = __import__("time").time()
    assert links.check(storage, token, now).state == "ok"
    wrong = f"pbl_{link_id}.{'A' * 43}"
    unknown = f"pbl_{'B' * 22}.{secret}"
    assert links.check(storage, wrong, now).state == "invalid"
    assert links.check(storage, unknown, now).state == "invalid"
    assert links.check(storage, "not a token", now).state == "invalid" and links.check(storage, "", now).state == "invalid"
    assert links.check(storage, token, now + 3601).state == "ended"
    assert links.check(storage, wrong, now + 3601).state == "invalid"
    links.revoke_link(storage, link_id)
    assert links.check(storage, token, now).state == "ended"
    assert links.check(storage, wrong, now).state == "invalid"


def test_every_check_compares_in_constant_time(client, storage, monkeypatch) -> None:
    token = mint(client).json()["token"]
    calls: List[int] = []
    real = links.hmac.compare_digest
    monkeypatch.setattr(links.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    link_id = token.removeprefix("pbl_").split(".")[0]
    for presented in (token, f"pbl_{link_id}.{'A' * 43}", f"pbl_{'B' * 22}.{'A' * 43}", "garbage"):
        links.check(storage, presented)
    assert len(calls) == 4


@pytest.mark.parametrize("ttl", ["2d", "30d", "60m", "", "7D", 3600])
def test_a_ttl_outside_the_three_is_refused_not_clamped(client, storage, ttl) -> None:
    assert mint(client, ttl=ttl).status_code == 422
    assert client.get(BASE).json() == {"links": []}


@pytest.mark.parametrize("ttl,seconds", [("1h", 3600), ("1d", 86400), ("7d", 604800)])
def test_the_three_ttls_set_the_expiry(client, ttl, seconds) -> None:
    link = mint(client, ttl=ttl).json()["link"]
    assert link["expires_at"] - link["created_at"] == seconds


def test_mode_is_stored_on_the_row_and_defaults_to_pinned(client, storage) -> None:
    assert mint(client).json()["link"]["mode"] == "pinned"
    assert mint(client, mode="follow").json()["link"]["mode"] == "follow"
    assert mint(client, mode="latest").status_code == 422
    assert sorted(r["mode"] for r in rows(storage)) == ["follow", "pinned"]
    assert {r["revision"] for r in rows(storage)} == {"r1"} and {r["board"] for r in rows(storage)} == {SLUG}


def test_a_revision_holding_a_vendor_key_refuses_the_mint_and_logs_no_value(env, client, storage) -> None:
    slug = add_leaky_board(env)
    with structlog.testing.capture_logs() as logged:
        r = mint(client, board=slug)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "publicboard_has_secret" and detail["detectors"] == {"github_token": 1}
    assert FAKE_KEY not in r.text and FAKE_KEY not in str(logged)
    assert not storage.db_path.exists() or rows(storage) == []


def test_a_secret_in_a_prompt_or_the_title_also_refuses(env, client) -> None:
    raw = copy.deepcopy(SIDECAR)
    raw["board"].update(slug="20261014-title", title=f"look {FAKE_KEY}")
    raw["task"], raw["rounds"] = None, []
    make_board(env.root, raw)
    assert mint(client, board="20261014-title").json()["detail"]["code"] == "publicboard_has_secret"


def test_an_unknown_board_or_revision_is_404_and_a_missing_review_board_is_409(env, client) -> None:
    assert mint(client, board="nope").status_code == 404
    assert mint(client, revision="r9").status_code == 404
    public_port.unregister()
    r = mint(client)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "publicboard_no_reviewboard"


def test_the_port_name_is_the_one_the_board_registers() -> None:
    assert public_port.NAME == board_public.PORT == "reviewboard.public"


def test_revoke_per_link_per_board_and_all(client, storage) -> None:
    first, second, third = (mint(client).json()["link"]["id"] for _ in range(3))
    assert client.delete(f"{BASE}/{first}").json() == {"revoked": 1}
    assert client.delete(f"{BASE}/{first}").status_code == 404
    assert client.delete(f"{BASE}/nope").status_code == 404
    assert client.delete(f"{BASE}?board=other").json() == {"revoked": 0}
    assert client.delete(f"{BASE}?board={SLUG}").json() == {"revoked": 2}
    fourth = mint(client).json()["link"]["id"]
    assert client.delete(f"{BASE}?all=true").json() == {"revoked": 1}
    assert {x["id"]: x["status"] for x in client.get(BASE).json()["links"]} == {first: "revoked", second: "revoked", third: "revoked", fourth: "revoked"}
    for bad in (BASE, f"{BASE}?all=true&board={SLUG}", f"{BASE}?all=false"):
        assert client.delete(bad).status_code == 422, bad


def test_the_list_filters_by_board_and_never_shows_a_secret(client, env) -> None:
    mint(client)
    assert client.get(f"{BASE}?board=other").json() == {"links": []}
    (one,) = client.get(f"{BASE}?board={SLUG}").json()["links"]
    assert set(one) == {"id", "board", "revision", "mode", "created_at", "expires_at", "revoked_at", "status"} and one["status"] == "active"


def test_the_links_prefix_is_fenced_against_api_keys() -> None:
    from src.core.api_keys import fence

    for path in (BASE, f"{BASE}/abc"):
        assert fence.fenced_family(path) == "public review links"
    assert fence.fenced_family("/api/v1/cplugs/publicboard/other") is None


def test_claude_can_revoke_and_there_is_no_mint_tool(env, client, storage) -> None:
    assert set(CPLUG.tools) == {"publicboard_links_remove"} and "mint" not in str(sorted(CPLUG.tools))
    first, second = (mint(client).json()["link"]["id"] for _ in range(2))
    assert asyncio.run(board_mcp.publicboard_links_remove(env.host.context("publicboard"), PANE, {"link_id": first})) is not None
    assert {x["id"]: x["status"] for x in client.get(BASE).json()["links"]}[first] == "revoked"
    for bad in ({}, {"link_id": "x", "all": True}, {"all": False}, {"board": ""}, {"mint": True}, {"all": "yes"}):
        with pytest.raises(Exception):
            asyncio.run(board_mcp.publicboard_links_remove(env.host.context("publicboard"), PANE, bad))
    ok, answer = env.call("publicboard_links_remove", {"board": SLUG})
    assert ok and answer == {"revoked": 1}


def test_a_purge_revokes_every_link_first(env, client, storage) -> None:
    for _ in range(3):
        mint(client)
    tokens = [mint(client).json()["token"]]
    asyncio.run(system_lifecycle.before_purge(env.app, "publicboard"))
    assert {x["status"] for x in client.get(BASE).json()["links"]} == {"revoked"}
    assert links.check(storage, tokens[0]).state == "ended"


def test_a_purge_with_no_links_file_creates_nothing(env, storage) -> None:
    asyncio.run(system_lifecycle.before_purge(env.app, "publicboard"))
    assert not storage.db_path.exists()


def test_the_link_id_is_16_random_bytes(client) -> None:
    link_id = mint(client).json()["link"]["id"]
    assert len(link_id) == 22


def test_a_direct_mint_with_a_bad_ttl_or_mode_raises(storage) -> None:
    for ttl, mode in (("2d", "pinned"), ("", "pinned"), ("1d", "latest")):
        with pytest.raises(ValueError):
            links.mint(storage, SLUG, "r1", ttl, mode, "0" * 64)
    assert not storage.db_path.exists()


def test_the_literals_are_the_single_source_of_the_lists() -> None:
    assert set(get_args(links.Ttl)) == set(links.TTL_SECONDS) and tuple(links.MODES) == get_args(links.Mode)


def test_a_plugin_hook_that_raises_or_hangs_stops_the_purge_with_a_clean_refusal(env, monkeypatch) -> None:
    async def boom(ctx: Any) -> None:
        raise RuntimeError("a plugin bug with a secret-looking detail")

    async def hang(ctx: Any) -> None:
        await asyncio.sleep(30)

    for hook in (boom, hang):
        monkeypatch.setattr(runtime, "find", lambda cplug_id, hook=hook: dataclasses.replace(CPLUG, before_purge=hook))
        monkeypatch.setattr(runtime, "HOOK_TIMEOUT_S", 0.2)
        with structlog.testing.capture_logs() as logged:
            with pytest.raises(system_lifecycle.PurgeHookFailed):
                asyncio.run(system_lifecycle.before_purge(env.app, "publicboard"))
        assert any(e["event"] == "cplug_purge_hook_failed" and e["cplug"] == "publicboard" for e in logged), hook.__name__


def test_the_route_types_come_from_the_store_lists() -> None:
    schema = routes_owner.MintBody.model_json_schema()["properties"]
    assert schema["ttl"]["enum"] == list(links.TTL_SECONDS) and schema["mode"]["enum"] == list(links.MODES)


def test_a_link_is_tied_to_the_scanned_content(env, client, storage) -> None:
    token = mint(client).json()["token"]
    link = links.check(storage, token).link
    port = board_public.port()
    assert link.content_sha256 and links.content_matches(link, port.revision_texts(SLUG, link.revision).texts)
    folder = env.board(SLUG)
    page = PAGE + b"<p>edited after the scan</p>\n"
    (folder / "r001.html").write_bytes(page)
    raw = copy.deepcopy(SIDECAR)
    view = raw["revisions"][0]["views"][0]
    view["sha256"], view["bytes"] = hashlib.sha256(page).hexdigest(), len(page)
    (folder / document.SIDECAR_FILE).write_text(document.canonical_text(document.parse_sidecar(raw)), encoding="utf-8")
    changed = port.revision_texts(SLUG, link.revision)
    assert not links.content_matches(link, changed.texts)
    assert links.content_hash(["a", "b"]) != links.content_hash(["ab"])


def test_a_newer_links_file_stops_a_purge_with_a_clean_refusal(env, storage) -> None:
    storage.path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(storage.db_path)
    conn.execute(f"PRAGMA user_version = {len(links.MIGRATIONS) + 5}")
    conn.commit()
    conn.close()
    with pytest.raises(system_lifecycle.PurgeHookFailed):
        asyncio.run(system_lifecycle.before_purge(env.app, "publicboard"))


def test_core_reaches_the_purge_through_the_definition_not_an_import() -> None:
    assert CPLUG.before_purge is not None and "publicboard" not in system_lifecycle.PURGE_HOOKS
    assert "publicboard" not in __import__("inspect").getsource(system_lifecycle).replace("publicboard-", "")


def test_the_secret_never_reaches_a_log(client) -> None:
    with structlog.testing.capture_logs() as logged:
        token = mint(client).json()["token"]
        link_id, secret = token.removeprefix("pbl_").split(".")
        client.delete(f"{BASE}/{link_id}")
    assert logged and secret not in str(logged) and token not in str(logged)
