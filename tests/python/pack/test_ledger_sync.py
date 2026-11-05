
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import ProviderAccount
from src.core.account_switch import auto_switch, relay_candidates
from src.core.pack.relay import ddl, ledger_sync_store as store, ledger_sync_view as view, targets
from src.core.pack.relay.ledger_sync_push import LedgerSync, own_sessions_by_account
from src.core.pack.relay.ledger_sync_wire import CAP_LEDGER_STATUS, SESSIONS_PATH, STATUS_PATH, LedgerStatusBody, status_of
from src.core.pack.relay.target_side import relay_profile_name
from src.core.provider_ledger import credentials, relay_accounts
from src.core.provider_ledger.total import compute_total
from src.models.provider_ledger import AccountUsage, LedgerSnapshot, LedgerTotal, LoopStatus, PokeStatus, UsageWindow

OWNER, RECEIVER = "iid-owner", "iid-recv"
KEY = "acme"
NOW = datetime.now(timezone.utc)
SECRET = "FAKE-ACCESS-TOKEN-VALUE-0000"
PEERS = {OWNER: ("nostromo", "peer-aaaa"), RECEIVER: ("studio", "peer-bbbb")}


def _owner_row() -> AccountUsage:
    return AccountUsage(
        id=KEY, name="Acme", provider="claude", plan="max", identity="a@x.io", credential_state="ok", fetched_at=NOW,
        windows=[UsageWindow(kind="five_hour", label="5h", used_pct=12.0, window_seconds=18000, resets_at=NOW + timedelta(hours=2)),
                 UsageWindow(kind="seven_day", label="7d", used_pct=40.0, window_seconds=604800, resets_at=NOW + timedelta(days=3))],
        poke=PokeStatus(state="idle", last_at=NOW), login_expires_at=NOW + timedelta(days=20), managed=True)


def _info(tmux: str, account: str, title: str = "") -> SimpleNamespace:
    return SimpleNamespace(account_id=account, tmux_session=tmux, activity_status="idle", claude_title=title or None,
                           session=SimpleNamespace(id="ses_" + tmux), host_key="local", agent_family="claude")


class _Link:

    def __init__(self) -> None:
        self.posts = []

    async def post(self, method, path, body):
        self.posts.append((method, path, body))
        return 200, {"ok": True}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(tmp_path / "accounts"))
    monkeypatch.setattr(store, "PATH", lambda: tmp_path / "sync.db")
    db = tmp_path / "main.db"

    def open_db():
        conn = sqlite3.connect(str(db))
        ddl.apply_pack_relay(conn)
        return conn

    conn = open_db()
    conn.execute("INSERT INTO pack_relay_targets (account_key, target_install_id, target_profile, state) VALUES (?, ?, '', 'pushed')",
                 (KEY, RECEIVER))
    conn.commit()
    conn.close()
    me = {"id": OWNER}
    monkeypatch.setattr(view, "directory", lambda: (PEERS, me["id"]))
    return SimpleNamespace(open_db=open_db, me=me, tmp=tmp_path)


def _sync(world, self_id, link, rows=()):
    snap = LedgerSnapshot(accounts=list(rows), total=LedgerTotal(accounts=len(rows)), loop=LoopStatus(alive=True))
    label = PEERS[self_id][0]
    return LedgerSync(open_db=world.open_db, peer=lambda iid: (link.post, [CAP_LEDGER_STATUS]), snapshot=lambda: snap,
                      self_id=self_id, self_label=label)


def test_owner_push_receiver_row_sessions_total_and_auto_switch(world, monkeypatch):
    link = _Link()
    owner = _sync(world, OWNER, link, [_owner_row()])
    owner._own = own_sessions_by_account([_info("cloude_api", KEY, "api work"), _info("cloude_dead", "other")], OWNER, "nostromo")
    assert asyncio.run(owner.push_all()) == 1
    (method, path, body), = link.posts
    assert (method, path) == ("POST", STATUS_PATH)
    wire = json.dumps(body)
    for forbidden in (SECRET, "access_token", "refresh", "profile", "codex_home", "config_dir"):
        assert forbidden not in wire
    assert body["windows"][1]["used_pct"] == 40.0 and body["login_expires_at"] and body["poke"]["state"] == "idle"
    assert body["identity_key"] and body["sessions"][0]["name"] == "api work"
    with pytest.raises(ValidationError):
        LedgerStatusBody.model_validate({**body, "access_token": SECRET})
    assert asyncio.run(owner.push_all()) == 0 and len(link.posts) == 1
    owner.on_connect(RECEIVER)
    assert not owner._sent
    assert asyncio.run(owner.push_all()) == 1

    world.me["id"] = RECEIVER
    profile = relay_profile_name(KEY, OWNER)
    (world.tmp / "accounts" / profile).mkdir(parents=True)
    expires = {"in": timedelta(hours=3)}
    monkeypatch.setattr(credentials, "read_claude_credential", lambda _d: credentials.ClaudeCredential(
        access_token="t" * 30, expires_at=datetime.now(timezone.utc) + expires["in"], refresh_token_expires_at=None,
        scopes=("user:inference", "user:profile"), subscription_type="max", rate_limit_tier=None, source="keychain"))
    assert relay_accounts.relay_rows()[0].windows == []
    store.save_status(OWNER, LedgerStatusBody.model_validate(body))
    row, = relay_accounts.relay_rows()
    assert row.id == profile and row.relayed and [w.used_pct for w in row.windows] == [12.0, 40.0]
    assert (row.name, row.identity) == ("Acme (relayed)", "a@x.io") and body["identity"] == "a@x.io"
    assert row.plan == "max" and row.fetched_at and row.synced_at and row.login_expires_at and row.poke.state == "idle"
    assert [(s.computer, s.name, s.session_id) for s in row.sessions_elsewhere] == [("nostromo", "api work", "remote:peer-aaaa:cloude_api")]

    old = {k: v for k, v in body.items() if k not in ("name", "identity")}
    store.save_status(OWNER, LedgerStatusBody.model_validate(old))
    row, = relay_accounts.relay_rows()
    assert (row.name, row.identity) == (f"{KEY} (relayed)", None) and row.windows
    store.save_status(OWNER, LedgerStatusBody.model_validate(body))

    rlink = _Link()
    recv = _sync(world, RECEIVER, rlink)
    recv._own = own_sessions_by_account([_info("cloude_web", profile, "web work")], RECEIVER, "studio")
    assert asyncio.run(recv.push_all()) == 1
    (m2, p2, b2), = rlink.posts
    assert p2 == SESSIONS_PATH and b2["account_key"] == KEY and b2["sessions"][0]["name"] == "web work"
    world.me["id"] = OWNER
    from src.core.pack.relay.ledger_sync_wire import LedgerSessionsBody
    store.save_sessions(RECEIVER, LedgerSessionsBody.model_validate(b2))
    card, = view.decorate_local([_owner_row()])
    assert [(s.computer, s.name, s.session_id) for s in card.sessions_elsewhere] == [("studio", "web work", "remote:peer-bbbb:cloude_web")]
    world.me["id"] = RECEIVER

    local = _owner_row().model_copy(update={"id": "mine"})
    rows = [local, row]
    keys = view.identity_keys(rows)
    assert keys["mine"] == keys[row.id]
    assert compute_total(rows, keys).accounts == 1 and compute_total(rows).accounts == 2
    other = row.model_copy(update={"id": "x-relay"})
    assert compute_total([local, other], {"mine": "k1", "x-relay": "k2"}).accounts == 2

    assert relay_candidates.usable(row, NOW)
    assert not relay_candidates.usable(row.model_copy(update={"fetched_at": NOW - timedelta(minutes=20)}), NOW)
    assert not relay_candidates.usable(row.model_copy(update={"relay_expires_at": NOW + timedelta(minutes=5)}), NOW)
    hot = AccountUsage(id="local-a", name="local-a", provider="claude", credential_state="ok", identity="other@x.io",
                       windows=[UsageWindow(kind="five_hour", label="5h", used_pct=99.5, window_seconds=18000, resets_at=NOW + timedelta(hours=1))])
    accounts = [ProviderAccount(id="local-a", name="local-a", provider="claude"), *relay_accounts.relay_accounts()]
    switch = ProviderAccountSwitchConfig(auto_switch=True, active_claude="local-a")

    def plan() -> list:
        snap = LedgerSnapshot(accounts=[hot], total=LedgerTotal(accounts=1), loop=LoopStatus(alive=True))
        merged = relay_candidates.with_relayed(snap, datetime.now(timezone.utc))
        return auto_switch.plan_switches(merged, accounts, switch, now=datetime.now(timezone.utc), linkable=lambda _a: True)

    assert [d.to_account_id for d in plan()] == [profile]
    expires["in"] = timedelta(minutes=5)
    assert plan() == []
    expires["in"] = timedelta(hours=3)
    store.save_status(OWNER, status_of(_owner_row().model_copy(update={"fetched_at": NOW - timedelta(hours=1)}), []))
    assert plan() == []
