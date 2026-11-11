
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.notifications.sources import common, login


def _acct(state: str, poke: Any = None, login_expires_at: Any = None) -> Any:
    return SimpleNamespace(id="a", name="a", provider="claude", credential_state=state, poke=poke,
                           login_expires_at=login_expires_at)


@pytest.fixture()
def clock(monkeypatch):
    t = {"now": 1_000_000.0}
    monkeypatch.setattr(common, "now", lambda: t["now"])
    return t


def test_an_expired_access_token_with_a_live_grant_does_not_fire(captured, clock) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("ok")])
    live = datetime.now(timezone.utc) + timedelta(days=20)
    for _ in range(3):
        clock["now"] += 600
        assert watch.observe([_acct("expired", login_expires_at=live)]) == []
    assert captured == []


def test_a_verified_needs_login_verdict_fires_once(captured, clock) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("expired")])
    assert watch.observe([_acct("expired", poke=SimpleNamespace(state="needs_login"))]) == ["a"]
    assert watch.observe([_acct("expired", poke=SimpleNamespace(state="needs_login"))]) == []
    assert len(captured) == 1


def test_a_one_poll_missing_blip_does_not_fire(captured, clock) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("ok")])
    clock["now"] += 5
    assert watch.observe([_acct("missing")]) == []
    clock["now"] += 5
    assert watch.observe([_acct("ok")]) == []
    assert captured == []


def test_a_sustained_missing_or_blanked_credential_fires_once(captured, clock) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("ok")])
    assert watch.observe([_acct("missing")]) == []
    clock["now"] += login.MISSING_GRACE_SECONDS + 1
    assert watch.observe([_acct("missing")]) == ["a"]
    clock["now"] += 600
    assert watch.observe([_acct("missing")]) == []
    assert len(captured) == 1


def test_a_refresh_token_past_its_own_deadline_fires(captured, clock) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("ok")])
    dead = datetime.now(timezone.utc) - timedelta(hours=1)
    assert watch.observe([_acct("expired", login_expires_at=dead)]) == ["a"]
