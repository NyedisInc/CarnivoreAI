
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from src.core import relay_keychain
from src.core.catalog import guest_account, hosted_api, install_reporter
from src.core.catalog.token_store import CatalogSession, open_token_store

NOW = 1_800_000_000
GUEST = "guest:11111111-2222-4333-8444-555555555555"


@pytest.fixture(autouse=True)
def fake_keychain(monkeypatch):
    items: dict = {}
    monkeypatch.setattr(relay_keychain, "read_password_state",
                        lambda s, a: ("ok", items[(s, a)]) if (s, a) in items else ("absent", None))
    monkeypatch.setattr(relay_keychain, "write_password",
                        lambda s, a, secret, replace=True: items.__setitem__((s, a), secret))
    monkeypatch.setattr(relay_keychain, "delete_password", lambda s, a: items.pop((s, a), None) is not None)
    monkeypatch.setattr(guest_account, "_cooldown_until", 0.0)
    return items


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('install_id', 'install-1')")
    return conn


class Host:

    def __init__(self, report_status: int = 200, delay: float = 0.0) -> None:
        self.calls: list = []
        self.report_status = report_status
        self.delay = delay

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        self.calls.append((method, path, json_body, bearer))
        await asyncio.sleep(self.delay)
        if path == "/pow":
            return hosted_api.HostedAnswer(200, {"challenge": "v1.guest_create.9999999999.1.salt.mac", "bits": 1})
        if path in ("/auth/guest", "/auth/guest/session"):
            return hosted_api.HostedAnswer(200, {
                "guest_id": GUEST, "access_token": "g-access", "refresh_token": "g-refresh",
                "expires_in": 28800, "refresh_expires_in": 2592000})
        return hosted_api.HostedAnswer(self.report_status, {})

    def paths(self, path: str) -> list:
        return [c for c in self.calls if c[1] == path]


def _report(tmp_path: Path, host, item_id: str = "a/b") -> str:
    return asyncio.run(install_reporter.report_installed(
        state_dir=tmp_path, api_base_url="https://h/api/v1", open_db=open_db,
        item_id=item_id, version="1.0.0", call=host, clock=lambda: NOW))


def _sign_in(tmp_path: Path) -> None:
    with open_token_store(tmp_path) as store:
        store.save(CatalogSession("ann", "access-token", NOW + 3600, "refresh", NOW + 86400))


def test_with_no_config_key_at_all_a_report_is_sent(tmp_path):
    host = Host()
    assert _report(tmp_path, host) == "sent"
    assert host.paths("/items/a/b/installed")[0][2:] == ({"version": "1.0.0"}, "g-access")
    assert len(host.paths("/auth/guest")) == 1


def test_a_signed_in_account_reports_as_itself_and_no_guest_is_made(tmp_path):
    _sign_in(tmp_path)
    host = Host()
    assert _report(tmp_path, host) == "sent"
    assert host.paths("/items/a/b/installed")[0][3] == "access-token"
    assert host.paths("/auth/guest") == [] and host.paths("/pow") == []


def test_a_bad_item_and_a_failing_host_are_soft(tmp_path):
    host = Host()
    assert _report(tmp_path, host, item_id="../x/y") == "bad_item"
    assert host.calls == []
    _sign_in(tmp_path)

    async def down(*_a, **_k):
        raise hosted_api.HostedUnavailable("unavailable", "down")

    assert _report(tmp_path, down) == "unreachable"
    assert _report(tmp_path, Host(report_status=429)) == "limited"
    assert _report(tmp_path, Host(report_status=404)) == "refused"


def test_backfill_reports_each_installed_item_once_and_records_the_marker(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"catalog": {"api_base_url": "https://example.net"}}))

    class Row:
        def __init__(self, item_id, version):
            self.item_id, self.version = item_id, version

    class Ledger:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def list(self):
            return [Row("a/b", "1.0.0"), Row("a/b", "1.0.0"), Row("c/d", "2.0.0")]

    def run(host):
        return asyncio.run(install_reporter.backfill_installed(
            config_path=config, state_dir=tmp_path, api_base_url="https://h/api/v1",
            open_db=open_db, ledger=Ledger, call=host, clock=lambda: NOW))

    first = Host()
    assert run(first) == "done"
    assert [c[1] for c in first.calls if c[1].endswith("/installed")] == ["/items/a/b/installed", "/items/c/d/installed"]
    block = json.loads(config.read_text())["catalog"]
    assert block["install_backfill_done"] is True and block["api_base_url"] == "https://example.net"
    second = Host()
    assert run(second) == "already" and second.calls == []


def test_backfill_that_hits_the_daily_cap_keeps_no_marker(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")

    class Ledger:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def list(self):
            return [type("R", (), {"item_id": "a/b", "version": "1.0.0"})()]

    assert asyncio.run(install_reporter.backfill_installed(
        config_path=config, state_dir=tmp_path, api_base_url="https://h/api/v1", open_db=open_db,
        ledger=Ledger, call=Host(report_status=429), clock=lambda: NOW)) == "retry"
    assert not install_reporter.backfill_done(config)
