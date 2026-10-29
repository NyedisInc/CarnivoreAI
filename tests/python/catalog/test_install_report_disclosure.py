
from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path

import pytest

from src.core import relay_keychain
from src.core.catalog import guest_account, hosted_api, install_report_disclosure, install_reporter

NOW = 1_800_000_000
GUEST = "guest:11111111-2222-4333-8444-555555555555"
CATALOG_JS = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"


@pytest.fixture(autouse=True)
def fake_keychain(monkeypatch):
    items: dict = {}
    monkeypatch.setattr(relay_keychain, "read_password_state",
                        lambda s, a: ("ok", items[(s, a)]) if (s, a) in items else ("absent", None))
    monkeypatch.setattr(relay_keychain, "write_password",
                        lambda s, a, secret, replace=True: items.__setitem__((s, a), secret))
    monkeypatch.setattr(guest_account, "_cooldown_until", 0.0)


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('install_id', 'install-1')")
    return conn


class Host:

    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        self.calls.append((method, path, json_body, bearer))
        if path == "/pow":
            return hosted_api.HostedAnswer(200, {"challenge": "v1.guest_create.9999999999.1.salt.mac", "bits": 1})
        if path in ("/auth/guest", "/auth/guest/session"):
            return hosted_api.HostedAnswer(200, {
                "guest_id": GUEST, "access_token": "g-access", "refresh_token": "g-refresh",
                "expires_in": 28800, "refresh_expires_in": 2592000})
        return hosted_api.HostedAnswer(200, {})

    def only(self, path: str) -> tuple:
        found = [c for c in self.calls if c[1] == path]
        assert len(found) == 1, (path, [c[1] for c in self.calls])
        return found[0]


def _run(tmp_path: Path, host: Host) -> None:
    asyncio.run(install_reporter.report_installed(
        state_dir=tmp_path, api_base_url="https://h/api/v1", open_db=_open_db,
        item_id="pub/item", version="1.2.3", call=host, clock=lambda: NOW))


def test_the_report_carries_exactly_the_listed_fields(tmp_path):
    host = Host()
    _run(tmp_path, host)
    _, path, body, bearer = host.only("/items/pub/item/installed")
    sent = {"item_id"} if "pub/item" in path else set()
    sent |= set(body or {})
    sent |= {"account_id"} if bearer else set()
    assert sent == set(install_report_disclosure.REPORT_FIELDS)


def test_the_first_guest_create_carries_exactly_the_listed_fields(tmp_path):
    host = Host()
    _run(tmp_path, host)
    _, _, body, _ = host.only("/auth/guest")
    assert set(body) == set(install_report_disclosure.GUEST_FIELDS)


def test_an_unlisted_field_turns_the_check_red(tmp_path, monkeypatch):
    monkeypatch.setattr(install_report_disclosure, "REPORT_FIELDS", ("item_id", "account_id"))
    host = Host()
    _run(tmp_path, host)
    _, _, body, _ = host.only("/items/pub/item/installed")
    assert set(body) != set(install_report_disclosure.REPORT_FIELDS) - {"item_id", "account_id"}


def test_every_listed_field_has_a_sentence_in_the_string_catalog():
    text = CATALOG_JS.read_text()
    listed = [*install_report_disclosure.REPORT_FIELDS, *install_report_disclosure.GUEST_FIELDS]
    missing = [f for f in listed if f"'{install_report_disclosure.field_key(f)}'" not in text]
    assert missing == []
    declared = set(re.findall(r"'privacy\.install_report\.field\.([a-z_]+)'", text))
    assert declared == set(listed)


def test_the_disclosure_route_answers_with_both_field_lists():
    from src.api import catalog_install_report_routes as routes

    body = asyncio.run(routes.get_install_report_disclosure())
    assert body == {key: list(ids) for key, ids in install_report_disclosure.disclosure().items()}
    assert body["report"] and body["guest"]
