
import asyncio
from types import SimpleNamespace

import pytest

from src.api import session_account_listing as sal
from src.core.account_switch import pane_account


def _info(name="cloude_a", family="claude", status="idle", epoch=7):
    return SimpleNamespace(
        tmux_session=name, agent_family=family, activity_status=status,
        host_key="local", account_id="stale",
        session=SimpleNamespace(tmux_created_epoch=epoch),
    )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sal.reset()
    calls = []

    async def fake(socket, name, provider, accounts, *, gate=None):
        calls.append((name, provider))
        return "acct-1" if name == "cloude_a" else None

    monkeypatch.setattr(pane_account, "resolve_pane_account", fake)
    from src.api import provider_ledger_routes as routes
    from src.core.provider_ledger import accounts_store, poller_scan
    monkeypatch.setattr(routes, "_config_path", lambda: "x")
    monkeypatch.setattr(accounts_store, "list_accounts", lambda p: [])
    monkeypatch.setattr(poller_scan, "with_auto_default", lambda a: a)
    yield calls
    sal.reset()


async def _settle():
    while sal._tasks:
        await asyncio.gather(*list(sal._tasks))


def _state():
    return SimpleNamespace(session_manager=SimpleNamespace(_tmux_socket_name=lambda: "cloude"))


@pytest.mark.asyncio
async def test_resolved_once_then_stamped_from_cache(_clean):
    state, row = _state(), _info()
    sal.mark_session_account(state, [row])
    assert row.account_id is None
    await _settle()
    sal.mark_session_account(state, [row])
    assert row.account_id == "acct-1"
    sal.mark_session_account(state, [row])
    assert _clean == [("cloude_a", "claude")]


@pytest.mark.asyncio
async def test_unmatched_dead_and_non_agent_rows_stay_null(_clean):
    state = _state()
    rows = [_info("cloude_b"), _info("cloude_c", status="dead"), _info("cloude_d", family="shell")]
    sal.mark_session_account(state, rows)
    await _settle()
    sal.mark_session_account(state, rows)
    assert [r.account_id for r in rows] == [None, None, None]
    assert [c[0] for c in _clean] == ["cloude_b"]


@pytest.mark.asyncio
async def test_a_new_pane_instance_under_the_same_name_is_read_again(_clean):
    state = _state()
    sal.mark_session_account(state, [_info(epoch=1)])
    await _settle()
    sal.mark_session_account(state, [_info(epoch=2)])
    await _settle()
    assert len(_clean) == 2


@pytest.mark.asyncio
async def test_a_restart_invalidates_the_cached_account(_clean):
    state, row = _state(), _info()
    sal.mark_session_account(state, [row])
    await _settle()
    sal.mark_session_account(state, [row])
    assert row.account_id == "acct-1"
    sal.invalidate("cloude_a")
    sal.mark_session_account(state, [row])
    assert row.account_id is None
    await _settle()
    assert len(_clean) == 2
