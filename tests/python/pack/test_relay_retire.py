
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.config.provider_accounts import ProviderAccount
from src.core.pack.relay import owner_side, retire, target_side, targets
from src.core.pack.relay.ddl import apply_pack_relay

SENDER = "iid-owner"
PREFIX = hashlib.sha256(SENDER.encode()).hexdigest()[:12]


def _doc(sender: str, refresh: bool = False) -> str:
    oauth: Dict[str, Any] = {"accessToken": "x" * 30, "expiresAt": 1}
    if refresh:
        oauth["refreshToken"] = "r"
    return json.dumps({"claudeAiOauth": oauth, "carnivoreRelay": {"from": sender}})


def _wire(monkeypatch, tmp_path: Path, items: Dict[str, str]) -> Path:
    from src.core.pack.relay import keychain_write

    monkeypatch.setattr(target_side.keychain, "read_password", lambda service, account=None: items.get(service))
    monkeypatch.setattr(keychain_write, "delete_item", lambda service, **_k: items.pop(service))
    return tmp_path


def _folder(home: Path, key: str, sender: str = SENDER) -> Path:
    path = Path(target_side.relay_profile_dir(key, sender, home))
    path.mkdir(parents=True)
    (path / ".claude.json").write_text("{}")
    return path


def test_receiver_retires_copy_folder_and_defers_in_use(monkeypatch, tmp_path):
    from src.core.provider_ledger.credentials import claude_keychain_services

    items: Dict[str, str] = {}
    home = _wire(monkeypatch, tmp_path, items)
    gone, kept, mine, busy = (_folder(home, k) for k in ("old-account", "kept-history", "mine", "busy"))
    for key in ("old-account", "kept-history", "busy"):
        items[claude_keychain_services(target_side.relay_profile_dir(key, SENDER, home))[0]] = _doc(SENDER)
    items[claude_keychain_services(str(mine))[0]] = _doc(SENDER, refresh=True)
    (kept / "projects" / "p").mkdir(parents=True)
    (kept / "projects" / "p" / "a.jsonl").write_text("{}")

    async def run(key: str, busy_now: bool = False) -> str:
        async def in_use(*_a: Any) -> bool:
            return busy_now
        monkeypatch.setattr(retire, "_in_use", in_use)
        return await retire.retire(None, SENDER, key, ("claude",), home=home)

    assert asyncio.run(run("old-account")) == "removed" and not gone.exists() and not items.get(
        claude_keychain_services(str(gone))[0])
    assert asyncio.run(run("kept-history")) == "removed" and (kept / "projects" / "p" / "a.jsonl").exists()
    assert asyncio.run(run("mine")) == "nothing" and mine.exists()
    assert asyncio.run(run("busy", busy_now=True)) == "deferred" and busy.exists()
    assert claude_keychain_services(str(busy))[0] in items


def test_reconcile_names_only_this_senders_unoffered_copies(monkeypatch, tmp_path):
    other = hashlib.sha256(b"iid-other").hexdigest()[:12]
    fakes = [ProviderAccount(id=f"{PREFIX}-old-account-relay", name="x", provider="claude", managed=True),
             ProviderAccount(id=f"{PREFIX}-work-relay", name="x", provider="claude", managed=True),
             ProviderAccount(id=f"{other}-old-account-relay", name="x", provider="claude", managed=True)]
    from src.core.provider_ledger import relay_accounts
    monkeypatch.setattr(relay_accounts, "with_relay", lambda _a: fakes)
    assert retire.stranded_keys(SENDER, ["work"]) == ["old-account"]
    assert retire.stranded_keys(SENDER, ["work", "old-account"]) == []


def test_codex_sessions_are_kept_and_default_login_copy_is_not_stranded(monkeypatch, tmp_path):
    from src.core.pack.relay import codex_target
    from src.core.provider_ledger import relay_accounts

    folder = Path(codex_target.codex_relay_profile_dir("work", SENDER, tmp_path))
    (folder / "sessions" / "2026").mkdir(parents=True)
    (folder / "sessions" / "2026" / "rollout.jsonl").write_text("{}")
    assert retire._has_conversations(folder, "codex") and not retire._has_conversations(folder, "claude")
    (folder / "config.toml").write_text("")
    (folder / "sessions" / "2026" / "rollout.jsonl").unlink()
    assert not retire._has_conversations(folder, "codex")

    from src.core.pack.relay import offers
    from src.core.provider_ledger import poller_scan
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(poller_scan, "read_claude_credential", lambda _d: {"x": 1})
    monkeypatch.setattr(offers.targets, "effective_on", lambda _c, _i: True)
    got = offers.local_offers(lambda: sqlite3.connect(":memory:"), str(cfg))
    assert got and poller_scan.AUTO_DEFAULT_ACCOUNT_ID in [o["account_key"] for o in got]
    fakes = [ProviderAccount(id=f"{PREFIX}-{o['account_key']}-relay", name="x", provider="claude", managed=True) for o in got]
    monkeypatch.setattr(relay_accounts, "with_relay", lambda _a: fakes)
    assert retire.stranded_keys(SENDER, [o["account_key"] for o in got]) == []


def test_owner_sweep_tells_holders_then_drops_rows_and_retries_the_unreachable():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    with db:
        apply_pack_relay(db)
    calls: List[Tuple[str, str]] = []
    up = {"iid-b": 200, "iid-c": None}

    async def post_b(method, path, body):
        calls.append((method, path))
        return up["iid-b"], {}

    links = {"iid-b": (post_b, [owner_side.CAP_CREDENTIALS]), "iid-c": None}
    relay = owner_side.Relay(open_db=lambda: db, peer=lambda iid: links.get(iid), notify=lambda: None, self_id=SENDER,
                             candidates=lambda: ["iid-b", "iid-c"])
    relay._open_db = lambda: _Keep(db)
    with db:
        for iid in ("iid-b", "iid-c"):
            targets.arm_default(db, "old-account", [iid], SENDER)
            targets.record(db, "old-account", iid, "pushed", 5, 1.0)
        targets.arm_default(db, "work", ["iid-b"], SENDER)

    assert asyncio.run(relay.sweep_orphans({"work"})) == 2
    assert calls == [("DELETE", "/federation/pack/credentials/old-account")]
    left = {(t.account_key, t.target_install_id) for t in targets.orphan_rows(db, [])}
    assert ("old-account", "iid-c") in left and ("old-account", "iid-b") not in left and ("work", "iid-b") in left


class _Keep:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._c, name)

    def close(self) -> None:
        return None
