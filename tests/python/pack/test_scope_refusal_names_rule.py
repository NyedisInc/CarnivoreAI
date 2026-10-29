
import asyncio

import pytest
from fastapi import HTTPException

from src.api import peer_auth
from src.core.pack.machines import config_state, restrictions


class _Cfg:
    def __init__(self, value):
        self._value = value

    def restrictions(self):
        return self._value


def _authorize(monkeypatch, scope, value):
    def lacks(token, wanted, also=()):
        raise peer_auth.ScopeNotGranted(wanted)

    monkeypatch.setattr(peer_auth, "_live_grant_for", lacks)
    monkeypatch.setattr(config_state, "default", lambda: _Cfg(value))
    return asyncio.run(peer_auth._authorize_peer("t", scope))


def test_withheld_scope_names_the_restriction(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _authorize(monkeypatch, "migrate", restrictions.Restrictions(may_receive_projects=False))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "pack_restricted" and exc.value.detail["rule"] == "may_receive_projects"


def test_scope_missing_with_no_rule_stays_401(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _authorize(monkeypatch, "migrate", restrictions.Restrictions())
    assert exc.value.status_code == 401
