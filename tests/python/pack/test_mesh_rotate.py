
from __future__ import annotations

import asyncio
import json
import subprocess
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import structlog

from src.api import auth as auth_module, pack_removed_logins_routes, pack_rotate_routes, peer_auth
from src.core.api_keys import store as api_key_store
from src.core.argent import pair_sync
from src.core.pack.machines import capabilities
from src.core.pack.relay import removed_copies, rotation
from src.core.provider_ledger import accounts_store, poller
from tests.argent.test_argent_refresh import T0
from src.core.computers import mesh_removal
from tests.python.pack.test_mesh_data_links import CERT
from tests.python.pack.test_mesh_removal import B, X
from tests.python.pack.test_mesh_removed_logins import E1, World, _fresh_member_cache  # noqa: F401

URL = "/api/v1/pack/rotate"
IDENT = "owner-fixture@example.invalid"
ACCESS = "access-token-sentinel-7e"
SECRETS = ("dlg-", "relay", "ten_1", "idn_1", IDENT, ACCESS, "DELEGATE-token-fixture", rotation.identity_hash(SimpleNamespace(identity=IDENT)))
LOGIN0 = datetime.fromtimestamp(T0 + 86400, tz=timezone.utc)


def _usage(aid, provider, login=LOGIN0, ident=IDENT, state="ok"):
    return SimpleNamespace(id=aid, name="Work " + aid[:3], provider=provider, credential_state=state, login_expires_at=login, identity=ident,
                           access_token=ACCESS)


@pytest.fixture()
def rot(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path)
    w.usage = {"claude-acct": _usage("claude-acct", "claude"), "codex-acct": _usage("codex-acct", "codex", login=None, ident=None),
               "auto-claude-default": _usage("auto-claude-default", "claude")}
    stored = [SimpleNamespace(id="claude-acct", name="Work cla", provider="claude"), SimpleNamespace(id="codex-acct", name="Work cod", provider="codex"),
              SimpleNamespace(id="agy", name="Agy", provider="antigravity")]
    monkeypatch.setattr(pack_rotate_routes, "time", SimpleNamespace(time=lambda: w.now))
    monkeypatch.setattr(accounts_store, "list_accounts", lambda _p: stored)
    monkeypatch.setattr(poller, "snapshot", lambda: SimpleNamespace(accounts=list(w.usage.values())))
    w.spied = []
    monkeypatch.setattr(poller, "poll_soon", lambda *a, **k: w.spied.append("poll_soon"))
    real_popen = subprocess.Popen

    def spy_popen(args, *a, **k):
        first = args if isinstance(args, str) else (args[0] if args else "")
        if str(first).rsplit("/", 1)[-1].split(" ")[0] in ("claude", "codex", "tmux"):
            w.spied.append("popen")
        return real_popen(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", spy_popen)
    asyncio.run(w.sync.revoke_removed(X))
    return w


def _acct(body, aid):
    return [a for a in body["accounts"] if a["account"] == aid][0]


def _start(w, aid="claude-acct"):
    return w.client.post(URL + "/start", json={"account": aid}, headers=w.head)


def test_switch_off_is_the_unknown_path_404_for_all_three_routes(rot, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    unknown = rot.client.get("/api/v1/pack/no-such-xyz", headers=rot.head)
    for headers in ({}, rot.head):
        for method, path in (("GET", URL), ("POST", URL + "/start"), ("POST", URL + "/argent")):
            r = rot.client.request(method, path, headers=headers, json={"account": "claude-acct"} if path.endswith("start") else None)
            assert (r.status_code, r.json()) == (unknown.status_code, unknown.json()), (method, path)
    with closing(rot.open_db()) as conn:
        assert rotation.read_rows(conn) == {}
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'pack_rotation'").fetchone() is None


def test_only_the_owners_own_sign_in_reaches_the_routes(rot, monkeypatch):
    monkeypatch.setattr(api_key_store, "is_api_key", lambda v: str(v).startswith("cak_"))
    monkeypatch.setattr(pack_removed_logins_routes, "is_api_key", lambda v: str(v).startswith("cak_"))

    async def admit(_token, _request):
        return {}

    monkeypatch.setattr(auth_module.api_key_gate, "admit", admit)
    calls = (("GET", URL), ("POST", URL + "/start"), ("POST", URL + "/argent"))

    def refused(headers):
        for method, path in calls:
            r = rot.client.request(method, path, headers=headers, json={"account": "claude-acct"} if path.endswith("start") else None)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "rotate_owner_only", (method, path, r.status_code)

    refused({"Authorization": "Bearer cak_fixture"})
    rot.tag = B
    refused(rot.head)
    rot.tag = None
    for method, path in calls:
        assert rot.client.request(method, path).status_code == 401
    inner = rot.client.app

    async def via(scope, receive, send):
        await inner(dict(scope, via_peer_link=True) if scope["type"] == "http" else scope, receive, send)

    from fastapi.testclient import TestClient
    rot.client = TestClient(via)
    refused(rot.head)
    with closing(rot.open_db()) as conn:
        assert rotation.read_rows(conn) == {}, "a refused start must record nothing"


def test_get_lists_stored_accounts_and_the_auto_default_as_terminal_and_a_copy_dies_by_its_expiry(rot):
    r = rot.client.get(URL, headers=rot.head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(a["account"], a["sign_in"]) for a in body["accounts"]] == [("claude-acct", "app"), ("codex-acct", "app"), ("auto-claude-default", "terminal")]
    c = _acct(body, "claude-acct")["copies"]
    assert [(x["install_id"], x["status"], x["expires_at"], x["ended_by"]) for x in c] == [(X, "dies_by", E1, None)]
    assert [(x["status"], x["ended_by"], x["killed_at"] is not None) for x in body["argent"]["copies"]] == [("dead_now", "argent_204", True), ("dies_by", None, False)]
    assert body["argent"]["known"] is True and _acct(body, "claude-acct")["sign_in_seen"] == "not_started"
    assert _acct(body, "claude-acct")["sign_in_ends"] == "unknown"


def test_a_new_sign_in_is_seen_only_for_a_moved_deadline_and_never_changes_a_copy_while_the_table_says_unknown(rot):
    r = _start(rot)
    assert r.status_code == 200 and r.json()["sign_in_seen"] == "not_seen" and r.json()["account"] == "claude-acct"
    assert _acct(rot.client.get(URL, headers=rot.head).json(), "claude-acct")["sign_in_seen"] == "not_seen"
    rot.usage["claude-acct"] = _usage("claude-acct", "claude", login=LOGIN0 + timedelta(seconds=1))
    assert _acct(rot.client.get(URL, headers=rot.head).json(), "claude-acct")["sign_in_seen"] == "not_seen"
    rot.usage["claude-acct"] = _usage("claude-acct", "claude", login=LOGIN0 + timedelta(days=30))
    body = rot.client.get(URL, headers=rot.head).json()
    assert _acct(body, "claude-acct")["sign_in_seen"] == "seen"
    assert [x["status"] for x in _acct(body, "claude-acct")["copies"]] == ["dies_by"], "unmeasured 7b: a seen sign-in must not read dead"
    assert [x["status"] for x in rot.client.get("/api/v1/pack/removed-logins", headers=rot.head).json()["computers"][0]["copies"] if x["kind"] == "claude"] == ["dies_by"]
    rot.usage["claude-acct"] = _usage("claude-acct", "claude", login=LOGIN0 + timedelta(days=30), ident="someone-else@example.invalid")
    assert _acct(rot.client.get(URL, headers=rot.head).json(), "claude-acct")["sign_in_seen"] == "other_account"
    assert _start(rot, "codex-acct").status_code == 200
    assert _acct(rot.client.get(URL, headers=rot.head).json(), "codex-acct")["sign_in_seen"] == "not_checkable"
    assert _start(rot, "agy").status_code == 404
    default = _start(rot, "auto-claude-default")
    assert default.status_code == 409 and default.json()["detail"]["code"] == "rotate_terminal_only", "listed as terminal: the refusal must say so, not that it is unknown"
    assert rot.client.post(URL + "/start", json={"account": "claude-acct", "x": 1}, headers=rot.head).status_code == 400


def test_a_measured_sign_in_ends_is_a_data_change_that_kills_only_copies_pushed_before_the_seen_start(rot, monkeypatch):
    monkeypatch.setitem(removed_copies.SIGN_IN_ENDS, "claude", "ends")
    assert _start(rot).status_code == 200
    assert [x["status"] for x in _acct(rot.client.get(URL, headers=rot.head).json(), "claude-acct")["copies"]] == ["dies_by"]
    rot.usage["claude-acct"] = _usage("claude-acct", "claude", login=LOGIN0 + timedelta(days=30))
    body = rot.client.get(URL, headers=rot.head).json()
    assert _acct(body, "claude-acct")["sign_in_ends"] == "ends"
    assert [(x["status"], x["ended_by"], x["killed_at"]) for x in _acct(body, "claude-acct")["copies"]] == [("dead_now", "sign_in", None)]
    with closing(rot.open_db()) as conn:
        conn.execute("UPDATE pack_relay_targets SET last_push_at = ? WHERE account_key = 'claude-acct' AND target_install_id = ?", (rot.now + 100, X))
        conn.commit()
    assert [x["status"] for x in _acct(rot.client.get(URL, headers=rot.head).json(), "claude-acct")["copies"]] == ["dies_by"]
    monkeypatch.setitem(removed_copies.SIGN_IN_ENDS, "codex", "ends")
    _start(rot, "codex-acct")
    assert [x["status"] for x in _acct(rot.client.get(URL, headers=rot.head).json(), "codex-acct")["copies"]] == ["expiry_unknown"]


def test_start_signs_nothing_in_and_starts_nothing(rot):
    assert _start(rot).status_code == 200
    assert rot.spied == []
    with closing(rot.open_db()) as conn:
        assert list(rotation.read_rows(conn)) == ["claude-acct"]


def test_argent_cancels_only_removed_computers_and_needs_the_pair_sync(rot, monkeypatch):
    seen = []
    orig = rot.sync.revoke_removed

    async def spy(iid):
        seen.append(iid)
        return await orig(iid)

    monkeypatch.setattr(rot.sync, "revoke_removed", spy)
    from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
    row = RosterComputerV2(install_id="iid-alpha", label="a", fed_public_key="A" * 43, cert=CERT, mesh=True, may_receive_logins=True)
    held = RosterV2(generation=1, alpha="iid-alpha", home="iid-alpha", issued_at=1, computers=[row])
    monkeypatch.setattr(mesh_removal, "REMOVAL", SimpleNamespace(_self="iid-self", _held=lambda: held))
    r = rot.client.post(URL + "/argent", headers=rot.head)
    assert r.status_code == 200 and seen == [X], (r.text, seen)
    assert r.json()["computers"][0]["install_id"] == X and r.json()["computers"][0]["state"] in ("none", "dead", "pending", "expired")
    monkeypatch.setattr(mesh_removal, "REMOVAL", SimpleNamespace(_self="iid-self", _held=lambda: None))
    seen.clear()
    r = rot.client.post(URL + "/argent", headers=rot.head)
    assert r.status_code == 200 and r.json() == {"computers": []} and seen == []
    monkeypatch.setattr(pair_sync, "PAIR", None)
    r = rot.client.post(URL + "/argent", headers=rot.head)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "rotate_argent_not_running"
    assert rot.client.get(URL, headers=rot.head).json()["argent"]["known"] is False


def test_no_secret_reaches_a_body_a_log_line_or_stdout_and_a_database_error_never_echoes_its_text(rot, monkeypatch, capsys):
    assert any(IDENT in u.identity and u.access_token == ACCESS for u in poller.snapshot().accounts)
    assert any("dlg-1" in d for d in rot.deletes), "the delegate id is in the Argent store"
    with structlog.testing.capture_logs() as logs:
        start = _start(rot)
        ok = rot.client.get(URL, headers=rot.head)
        arg = rot.client.post(URL + "/argent", headers=rot.head)

        def boom():
            raise rot_sqlite("leak-me")

        monkeypatch.setattr(peer_auth, "open_db", boom)
        bad = rot.client.get(URL, headers=rot.head)
        bad2 = _start(rot)
    assert ok.json()["accounts"][0]["copies"] and ok.json()["argent"]["copies"], "the rows must be in the body"
    assert [r.status_code for r in (start, ok, arg)] == [200, 200, 200] and bad.status_code == bad2.status_code == 503
    assert bad.json()["detail"]["code"] == "rotate_unavailable" and "leak-me" not in bad.text + bad2.text
    assert any(e["event"] == "pack_rotate_started" for e in logs), "the capture must see the start event"
    out = capsys.readouterr()
    blob = json.dumps(logs, default=str) + out.out + out.err + start.text + ok.text + arg.text + bad.text
    for secret in SECRETS:
        assert secret not in blob, secret


def test_the_screens_truth_nits_unlisted_copies_unreadable_config_garbage_body_and_argent_store_errors(rot, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    for headers in ({}, rot.head):
        off = rot.client.post(URL + "/start", content=b"{not json", headers=dict(headers, **{"Content-Type": "application/json"}))
        unknown = rot.client.post("/api/v1/pack/no-such-xyz", content=b"{not json", headers=dict(headers, **{"Content-Type": "application/json"}))
        assert (off.status_code, off.json()) == (unknown.status_code, unknown.json()) and off.status_code == 404
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    on = rot.client.post(URL + "/start", content=b"{not json", headers=dict(rot.head, **{"Content-Type": "application/json"}))
    assert on.status_code == 400 and on.json()["detail"]["code"] == "invalid_request"
    stored = [a for a in accounts_store.list_accounts(None) if a.id != "codex-acct"]
    monkeypatch.setattr(accounts_store, "list_accounts", lambda _p: stored)
    body = rot.client.get(URL, headers=rot.head).json()
    assert [a["account"] for a in body["accounts"]] == ["claude-acct", "auto-claude-default"]
    assert [(u["account"], u["provider"], [c["install_id"] for c in u["copies"]]) for u in body["unlisted"]] == [("codex-acct", "codex", [X])]
    assert body["not_tracked"] == ["github"]
    def no_config(_p):
        raise FileNotFoundError("no config")
    monkeypatch.setattr(accounts_store, "list_accounts", no_config)
    r = rot.client.get(URL, headers=rot.head)
    assert r.status_code == 200 and [a["account"] for a in r.json()["accounts"]] == ["auto-claude-default"]
    from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
    row = RosterComputerV2(install_id="iid-alpha", label="a", fed_public_key="A" * 43, cert=CERT, mesh=True, may_receive_logins=True)
    held = RosterV2(generation=1, alpha="iid-alpha", home="iid-alpha", issued_at=1, computers=[row])
    monkeypatch.setattr(mesh_removal, "REMOVAL", SimpleNamespace(_self="iid-self", _held=lambda: held))

    async def boom(_iid):
        raise rot_sqlite("leak-me-too")

    monkeypatch.setattr(rot.sync, "revoke_removed", boom)
    r = rot.client.post(URL + "/argent", headers=rot.head)
    assert r.status_code == 200 and "leak-me-too" not in r.text
    assert r.json() == {"computers": [{"install_id": X, "state": "unavailable"}]}


def test_s6_a_store_error_on_the_second_computer_keeps_the_first_computers_line(rot, monkeypatch):
    from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
    row = RosterComputerV2(install_id="iid-alpha", label="a", fed_public_key="A" * 43, cert=CERT, mesh=True, may_receive_logins=True)
    held = RosterV2(generation=1, alpha="iid-alpha", home="iid-alpha", issued_at=1, computers=[row])
    monkeypatch.setattr(mesh_removal, "REMOVAL", SimpleNamespace(_self="iid-self", _held=lambda: held))
    monkeypatch.setattr(removed_copies, "removed_computers", lambda _conn: [("iid-x1", "s", 1), ("iid-x2", "s", 1)])

    async def revoke(iid):
        if iid == "iid-x2":
            raise rot_sqlite("leak-me-three")
        return "dead"

    monkeypatch.setattr(rot.sync, "revoke_removed", revoke)
    r = rot.client.post(URL + "/argent", headers=rot.head)
    assert r.status_code == 200 and "leak-me-three" not in r.text
    assert r.json() == {"computers": [{"install_id": "iid-x1", "state": "dead"}, {"install_id": "iid-x2", "state": "unavailable"}]}


def rot_sqlite(msg):
    import sqlite3
    return sqlite3.OperationalError(msg)
