
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from src.plugins.host import webhook_routes
from tests.python.plugins_v3.test_timers_webhooks_feed_ui import _setup_webhook_app

URL = "/api/v1/cplugs/hooker/webhook/ci"
PROXY = "192.0.2.11"
LIMIT = webhook_routes._FAIL_LIMIT_PER_MINUTE
WINDOW = webhook_routes._FAIL_WINDOW_SECONDS


class _Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def app_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app, _delivered = _setup_webhook_app(tmp_path, monkeypatch)
    monkeypatch.setattr("src.core.mcp.trusted_proxy.configured", lambda: [PROXY])
    clock = _Clock()
    monkeypatch.setattr(webhook_routes, "_fail_limiter", webhook_routes.FailLimiter(clock=clock))
    yield app, clock
    webhook_routes.clear_install("k-hooker")


def _bad(app, peer: str, xff: Optional[str] = None, n: int = 1) -> List[httpx.Response]:
    headers: Dict[str, str] = {"x-timestamp": "1", "x-nonce": "n" * 16, "x-signature": "00"}
    if xff:
        headers["x-forwarded-for"] = xff
    client = TestClient(app, client=(peer, 50000))
    return [client.post(URL, content=b"{}", headers=headers) for _ in range(n)]


def test_one_source_trips_at_limit_with_retry_after(app_clock) -> None:
    app, _ = app_clock
    first = _bad(app, "203.0.113.5", n=LIMIT)
    assert all(r.status_code == 401 for r in first)
    blocked = _bad(app, "203.0.113.5")[0]
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "rate_limited"
    assert blocked.headers["retry-after"] == "60"


def test_same_count_spread_over_sources_is_not_throttled(app_clock) -> None:
    app, _ = app_clock
    codes = [_bad(app, f"203.0.113.{i}")[0].status_code for i in range(LIMIT * 2)]
    assert set(codes) == {401}


def test_forwarded_clients_behind_trusted_proxy_get_separate_windows(app_clock) -> None:
    app, _ = app_clock
    _bad(app, PROXY, xff="198.51.100.7", n=LIMIT)
    assert _bad(app, PROXY, xff="198.51.100.7")[0].status_code == 429
    assert _bad(app, PROXY, xff="198.51.100.8")[0].status_code == 401


def test_spoofed_header_from_untrusted_peer_does_not_split_the_key(app_clock) -> None:
    app, _ = app_clock
    for i in range(LIMIT):
        _bad(app, "203.0.113.5", xff=f"192.0.2.{i}")
    assert _bad(app, "203.0.113.5", xff="192.0.2.250")[0].status_code == 429


def test_source_recovers_after_the_window(app_clock) -> None:
    app, clock = app_clock
    _bad(app, "203.0.113.5", n=LIMIT)
    assert _bad(app, "203.0.113.5")[0].status_code == 429
    clock.now += WINDOW + 1
    assert _bad(app, "203.0.113.5")[0].status_code == 401
