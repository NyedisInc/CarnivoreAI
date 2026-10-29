
import asyncio
import time

from src.core.catalog import catalog_auth, hosted_api
from src.core.catalog.token_store import CatalogSession, open_token_store

BASE = "https://host/api/v1"


def _seed(state, refresh="r0", provider="google"):
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession("ann@x.test", "a0", now - 10, refresh, now + 86400, provider))


def test_twenty_concurrent_callers_make_one_refresh(tmp_path, monkeypatch):
    _seed(tmp_path)
    posts = []

    async def call(base, method, path, *, json_body=None, bearer=None):
        posts.append((path, json_body))
        await asyncio.sleep(0.05)
        return hosted_api.HostedAnswer(
            status=200,
            body={"access_token": "a1", "refresh_token": "r1", "expires_in": 28800, "refresh_expires_in": 2592000},
        )

    monkeypatch.setattr(hosted_api, "call", call)

    async def run():
        return await asyncio.gather(*(catalog_auth.bearer(tmp_path, BASE) for _ in range(20)))

    tokens = asyncio.run(run())
    assert len(posts) == 1 and posts[0][0] == "/auth/refresh"
    assert set(tokens) == {"a1"}
    with open_token_store(tmp_path) as store:
        held = store.read()
    assert held.refresh_token == "r1" and held.provider == "google"


def test_refused_refresh_for_a_replaced_pair_does_not_clear(tmp_path, monkeypatch):
    _seed(tmp_path)
    events = []
    catalog_auth.subscribe(events.append)

    async def call(base, method, path, *, json_body=None, bearer=None):
        now = int(time.time())
        with open_token_store(tmp_path) as store:
            store.save(CatalogSession("ann@x.test", "a9", now + 3600, "r9", now + 86400, "google"))
        return hosted_api.HostedAnswer(status=401, body={"code": "unauthorized"})

    monkeypatch.setattr(hosted_api, "call", call)
    try:
        try:
            asyncio.run(catalog_auth.bearer(tmp_path, BASE))
            raised = False
        except catalog_auth.SignedOut:
            raised = True
    finally:
        catalog_auth.unsubscribe(events.append)
    assert raised
    with open_token_store(tmp_path) as store:
        held = store.read()
    assert held is not None and held.refresh_token == "r9"
    assert events == []


def test_refused_refresh_clears_and_announces_signed_out(tmp_path, monkeypatch):
    _seed(tmp_path)
    events = []
    catalog_auth.subscribe(events.append)

    async def call(base, method, path, *, json_body=None, bearer=None):
        return hosted_api.HostedAnswer(status=401, body={})

    monkeypatch.setattr(hosted_api, "call", call)
    try:
        try:
            asyncio.run(catalog_auth.bearer(tmp_path, BASE))
        except catalog_auth.SignedOut:
            pass
    finally:
        catalog_auth.unsubscribe(events.append)
    assert events == [{"signed_in": False, "login": None, "provider": None}]
    with open_token_store(tmp_path) as store:
        assert store.read() is None


def test_network_error_never_signs_out(tmp_path, monkeypatch):
    _seed(tmp_path)

    async def call(base, method, path, *, json_body=None, bearer=None):
        raise hosted_api.HostedUnavailable("unreachable", "down")

    monkeypatch.setattr(hosted_api, "call", call)
    try:
        asyncio.run(catalog_auth.bearer(tmp_path, BASE))
        assert False, "expected HostedUnavailable"
    except hosted_api.HostedUnavailable:
        pass
    with open_token_store(tmp_path) as store:
        assert store.read().refresh_token == "r0"


def test_provider_column_migrates_an_old_file(tmp_path):
    import sqlite3
    path = tmp_path / "catalog_tokens.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE catalog_tokens (id INTEGER PRIMARY KEY CHECK (id = 1), login TEXT NOT NULL, "
                 "access_token TEXT NOT NULL, access_expires_at INTEGER NOT NULL, refresh_token TEXT NOT NULL, "
                 "refresh_expires_at INTEGER NOT NULL)")
    conn.execute("INSERT INTO catalog_tokens VALUES (1, 'old', 'a', 1, 'r', 2)")
    conn.commit()
    conn.close()
    with open_token_store(tmp_path) as store:
        held = store.read()
    assert held.login == "old" and held.provider is None
