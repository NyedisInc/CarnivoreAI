
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import structlog  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import auth as auth_module, pack_removed_logins_routes, peer_auth  # noqa: E402
from src.api.auth import create_access_token  # noqa: E402
from src.core.api_keys import store as api_key_store  # noqa: E402
from src.core.argent import pair_sync  # noqa: E402
from src.core.argent.delegate import Delegates  # noqa: E402
from src.core.computers import mesh_removal  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.federation import fed_key, grants, peer_hosts, peer_token  # noqa: E402
from src.core.pack.machines import capabilities  # noqa: E402
from src.core.pack.relay import member_reach  # noqa: E402
from src.main import app  # noqa: E402
from tests.argent.test_argent_refresh import T0  # noqa: E402
from tests.python.pack.test_mesh_removal import A, B, C, X, _argent_world, _tmp_db  # noqa: E402

URL = "/api/v1/pack/removed-logins"
Y, Z = "install-y1", "install-z1"
REMOVED_AT = T0 - 60
E1 = int((T0 + 7200) * 1000)
DLG2_EXPIRY = int((T0 + 3600) * 1000)
SECRETS = ("DELEGATE-token-fixture", "refresh", "relay", "ten_1", "idn_1", "Owner", "dlg-", "access-token-fixture")


@pytest.fixture(autouse=True)
def _fresh_member_cache(monkeypatch):
    monkeypatch.setattr(member_reach, "_LAST_GOOD", None)


class Tagged:

    def __init__(self, inner, state) -> None:
        self.inner, self.state = inner, state

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket") and self.state.tag:
            scope = dict(scope, mesh_peer=self.state.tag)
        if scope["type"] in ("http", "websocket") and self.state.via_peer_link:
            scope = dict(scope, via_peer_link=True)
        await self.inner(scope, receive, send)


class World:

    def __init__(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
        self.open_db = _tmp_db(tmp_path / "db")
        self.path = db_path_for(tmp_path / "db" / "state")
        self.tag = None
        self.via_peer_link = False
        self.now = T0
        monkeypatch.setattr(peer_auth, "open_db", lambda: self.open_db())
        monkeypatch.setattr(pack_removed_logins_routes, "time", SimpleNamespace(time=lambda: self.now))
        with closing(self.open_db()) as conn:
            mesh_removal._ensure(conn)
            for iid, state, at in ((X, "removed", REMOVED_AT), (Y, "listed", None), (Z, "removed", REMOVED_AT)):
                conn.execute("INSERT INTO pack_mesh_removal (install_id, state, generation, removed_at) VALUES (?, ?, 2, ?)", (iid, state, at))
            peer_hosts.upsert(conn, install_id=Z, label="star", grant_id="gz", fid="fz", initiator=True)
            rows = [("claude-acct", X, "0123456789ab-claude-acct-relay", E1, 1.0, "pushed"),
                    ("codex-acct", X, "0123456789ab-codex-acct-relay-codex", None, 2.0, "off"),
                    ("never-acct", X, "0123456789ab-never-acct-relay-refresh-access-token-fixture", E1, None, "on"),
                    ("claude-acct", Y, "0123456789ab-claude-acct-relay", E1, 3.0, "pushed"),
                    ("claude-acct", Z, "0123456789ab-claude-acct-relay", E1, 3.0, "pushed")]
            for row in rows:
                conn.execute("INSERT INTO pack_relay_targets (account_key, target_install_id, target_profile, last_expiry_pushed, last_push_at, state) "
                             "VALUES (?, ?, ?, ?, ?, ?)", row)
            conn.commit()
        self.sync, self.rig, self.deletes = _argent_world(monkeypatch, tmp_path / "ag", live=("dlg-1", "dlg-2", "dlg-c"))

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE" and request.url.path.endswith("/dlg-2"):
                self.deletes.append(request.url.path)
                return httpx.Response(500, json={"error": {"code": "x"}})
            if request.method == "DELETE":
                self.deletes.append(request.url.path)
            return await self.rig.argent.handle(request)

        rig = self.rig
        self.sync.credentials._delegates = Delegates(rig.store, rig.tokens, read_settings=lambda: rig.cfg, transport=httpx.MockTransport(handler),
                                                     clock=lambda: rig.now[0])
        rig.store.delegate_put(X, {"id": "dlg-1", "expires_at": int((T0 + 86400) * 1000), "remint_at": 0, "stale": [{"id": "dlg-2", "expires_at": DLG2_EXPIRY}]})
        monkeypatch.setattr(pair_sync, "PAIR", self.sync)
        self.client = TestClient(Tagged(app, self))
        self.head = {"Authorization": "Bearer " + create_access_token()[0]}

    def get(self, headers=None):
        return self.client.get(URL, headers=self.head if headers is None else headers)


@pytest.fixture()
def world(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path)
    asyncio.run(w.sync.revoke_removed(X))
    return w


def _seeded(w) -> str:
    with closing(w.open_db()) as conn:
        dump = repr([tuple(r) for r in conn.execute("SELECT * FROM pack_relay_targets")]) + repr([tuple(r) for r in conn.execute("SELECT * FROM pack_mesh_removal")])
    store = w.rig.store
    return dump + json.dumps(store.get_login(), default=str) + repr(store.delegate_get(X)) + repr(w.rig.kc.items) + repr(w.rig.argent.live)


def _x(body):
    assert [c["install_id"] for c in body["computers"]] == [X]
    return body["computers"][0]


def test_a_removed_computers_copies_read_dead_only_on_a_204_and_dies_by_its_stored_expiry_otherwise(world, monkeypatch):
    r = world.get()
    assert r.status_code == 200, r.text
    body = r.json()
    x = _x(body)
    assert x["removed_at"] == int(REMOVED_AT * 1000) and x["state"] == "removed"
    got = [(c["kind"], c["account"], c["status"], c["expires_at"], c["killed_at"] is not None) for c in x["copies"]]
    assert got == [("argent", None, "dead_now", None, True), ("argent", None, "dies_by", DLG2_EXPIRY, False),
                   ("claude", "claude-acct", "dies_by", E1, False), ("codex", "codex-acct", "expiry_unknown", None, False)]
    assert body["argent_known"] is True and body["not_tracked"] == ["github"]
    assert world.deletes and "/v1/my/cli/delegates/dlg-1" in world.deletes[0]

    world.now = T0 + 8000
    claude = [c for c in _x(world.get().json())["copies"] if c["kind"] == "claude"]
    assert [c["status"] for c in claude] == ["expired"]
    world.now = T0

    text = world.get().text
    seeded = _seeded(world)
    for secret in SECRETS:
        assert secret in seeded, secret
        assert secret not in text, secret
    with closing(world.open_db()) as conn:
        conn.execute("INSERT INTO pack_relay_targets (account_key, target_install_id, target_profile, last_expiry_pushed, last_push_at, state) VALUES (?, ?, 'p', ?, 1.0, 'pushed')",
                     ("canary-ten_1-canary", X, E1))
        conn.commit()
    assert "ten_1" in world.get().text
    with closing(world.open_db()) as conn:
        conn.execute("DELETE FROM pack_relay_targets WHERE account_key = 'canary-ten_1-canary'")
        conn.commit()

    monkeypatch.setattr(pair_sync, "PAIR", None)
    none = world.get().json()
    assert none["argent_known"] is False and [c["kind"] for c in _x(none)["copies"]] == ["claude", "codex"]


def test_no_secret_reaches_a_log_line_or_stdout_and_a_database_error_never_echoes_its_text(world, monkeypatch, capsys):
    with structlog.testing.capture_logs() as logs:
        ok = world.get()

        def boom():
            raise sqlite3.OperationalError("leak-me")

        monkeypatch.setattr(peer_auth, "open_db", boom)
        bad = world.get()
    assert ok.status_code == 200 and bad.status_code == 503
    assert "api_request_failed" in [e["event"] for e in logs], "the route's own failure event must be captured first (the capture is not empty)"
    assert bad.json()["detail"]["code"] == "removed_logins_unavailable" and "leak-me" not in bad.text
    out = capsys.readouterr()
    for secret in SECRETS:
        assert secret not in json.dumps(logs, default=str) and secret not in out.out + out.err, secret
    print("stdout-canary-ten_1")
    with structlog.testing.capture_logs() as canary_logs:
        structlog.get_logger().info("canary", token="ten_1")
    seen = capsys.readouterr()
    assert "stdout-canary-ten_1" in seen.out and "ten_1" in json.dumps(canary_logs, default=str)


def test_only_the_owners_own_sign_in_reaches_it(world, monkeypatch):
    monkeypatch.setattr(api_key_store, "is_api_key", lambda v: str(v).startswith("cak_"))
    monkeypatch.setattr(pack_removed_logins_routes, "is_api_key", lambda v: str(v).startswith("cak_"))

    async def admit(_token, _request):
        return {}

    monkeypatch.setattr(auth_module.api_key_gate, "admit", admit)
    r = world.get({"Authorization": "Bearer cak_fixture"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "removed_logins_owner_only"
    world.tag = B
    r = world.get()
    assert r.status_code == 403 and r.json()["detail"]["code"] == "removed_logins_owner_only"
    world.tag = None
    world.via_peer_link = True
    r = world.get()
    assert r.status_code == 403 and r.json()["detail"]["code"] == "removed_logins_owner_only"
    world.via_peer_link = False
    assert world.get().status_code == 200
    with closing(world.open_db()) as conn:
        pub = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
        grant = grants.create_grant(conn, peer_install_id="iid-peer", public_key=pub, label="peer", scopes=("sessions", "machine"))
    for token in (peer_token.mint(grant, C)[0], peer_token.mint(grant, C, kind=peer_token.MESH_KIND)[0]):
        assert world.get({"Authorization": "Bearer " + token}).status_code == 401
    assert world.client.get(URL).status_code == 401
    assert world.client.post(URL, headers=world.head).status_code == 405


def test_with_the_switch_off_the_route_is_the_unknown_path_404_with_or_without_auth(world, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    unknown = world.client.get("/api/v1/pack/no-such-xyz", headers=world.head)
    assert unknown.status_code == 404
    for headers in ({}, world.head):
        r = world.client.get(URL, headers=headers)
        assert (r.status_code, r.json()) == (unknown.status_code, unknown.json())


def test_an_account_deleted_after_a_removal_stays_listed_until_its_expiry_and_no_choice_row_changes(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from src.core.pack.relay import owner_side, targets as targets_mod
    from src.core.pack.relay.removed_copies import build

    W = "install-w1"
    live, dead = E1, int((T0 - 10) * 1000)

    def seed(open_db):
        with closing(open_db()) as conn:
            mesh_removal._ensure(conn)
            for iid, state, at in ((X, "removed", REMOVED_AT), (W, "removed", REMOVED_AT), (Y, "listed", None)):
                conn.execute("INSERT INTO pack_mesh_removal (install_id, state, generation, removed_at) VALUES (?, ?, 2, ?)", (iid, state, at))
            rows = [("gone-acct", X, "p-claude", live, 1.0, "pushed"), ("gone-acct", W, "p-claude", live, 1.0, "refused"),
                    ("gone-acct", Y, "p-claude", live, 3.0, "pushed"), ("gone-acct", "*", "", None, None, "on"),
                    ("gone-old", X, "p-claude", dead, 1.0, "pushed"), ("gone-off", X, "tokenish-relay-codex", None, 2.0, "off"),
                    ("keep-acct", "*", "", None, None, "off"), ("keep-acct", X, "p-claude", live, 1.0, "refused"), ("keep-acct", Y, "p-claude", None, None, "off")]
            for row in rows:
                conn.execute("INSERT INTO pack_relay_targets (account_key, target_install_id, target_profile, last_expiry_pushed, last_push_at, state) "
                             "VALUES (?, ?, ?, ?, ?, ?)", row)
            conn.commit()

    sent: list = []
    now = [T0]

    def relay_for(open_db, candidates):
        def peer(iid):
            async def post(method, path, body):
                sent.append((iid, method, path))
                return 200, {}
            return (post, frozenset({owner_side.CAP_CREDENTIALS})) if iid == Y else None
        return owner_side.Relay(open_db=open_db, peer=peer, notify=lambda: None, self_id="iid-owner", candidates=lambda: candidates, clock=lambda: now[0])

    def listed(open_db, iid):
        return [(c["account"], c["status"], c["expires_at"]) for d in build(open_db, None, int(now[0] * 1000))["computers"] if d["install_id"] == iid
                for c in d["copies"]]

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    open_db = _tmp_db(tmp_path / "db")
    seed(open_db)
    with closing(open_db()) as conn:
        keep_before = conn.execute("SELECT * FROM pack_relay_targets WHERE account_key = 'keep-acct' ORDER BY target_install_id").fetchall()
    assert len(keep_before) == 3
    relay = relay_for(open_db, [])
    assert asyncio.run(relay.sweep_orphans({"keep-acct"})) == 6
    with closing(open_db()) as conn:
        assert conn.execute("SELECT * FROM pack_relay_targets ORDER BY account_key, target_install_id").fetchall() == \
            conn.execute("SELECT * FROM pack_relay_targets WHERE account_key = 'keep-acct' ORDER BY target_install_id").fetchall() == keep_before
    assert listed(open_db, X) == [("gone-acct", "dies_by", live), ("keep-acct", "dies_by", live)]
    assert listed(open_db, W) == [("gone-acct", "dies_by", live)]
    assert sent == [(Y, "DELETE", f"{owner_side.CREDENTIALS_PATH}/gone-acct")]
    with closing(open_db()) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(pack_relay_removed_copies)")}
        assert cols == {"target_install_id", "account_key", "kind", "expires_at", "pushed_at"}
        stored = conn.execute("SELECT * FROM pack_relay_removed_copies").fetchall()
        assert len(stored) == 2 and "p-claude" not in json.dumps([list(r) for r in stored])

    assert asyncio.run(relay.sweep_orphans({"keep-acct", "gone-acct"})) == 0
    with closing(open_db()) as conn:
        assert targets_mod.default_mode(conn, "gone-acct") is True
        assert "gone-acct" not in targets_mod.summary(conn)
    sent.clear()
    cred = SimpleNamespace(expires_at=datetime.fromtimestamp(T0 + 9000, timezone.utc), access_token="tok-fixture", scopes=(), subscription_type=None,
                           rate_limit_tier=None)
    assert asyncio.run(relay_for(open_db, [Y]).push_account("gone-acct", cred, "claude")) == [Y]
    assert [s[0] for s in sent] == [Y]
    assert [row[0] for row in listed(open_db, X)].count("gone-acct") == 1

    now[0] = T0 + 7201
    assert listed(open_db, X) == [("keep-acct", "expired", live)] and listed(open_db, W) == []
    asyncio.run(relay.sweep_orphans({"keep-acct", "gone-acct"}))
    with closing(open_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pack_relay_removed_copies").fetchone()[0] == 0

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    now[0] = T0
    off_db = _tmp_db(tmp_path / "off")
    seed(off_db)
    assert asyncio.run(relay_for(off_db, []).sweep_orphans({"keep-acct"})) == 6
    with closing(off_db()) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'pack_relay_removed_copies'").fetchall() == []

