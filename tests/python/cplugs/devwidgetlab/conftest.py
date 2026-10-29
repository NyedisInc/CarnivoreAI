
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cplugs.devwidgetlab.drafts import checkout
from src.cplugs.sdk import signed_links


@pytest.fixture(autouse=True)
def no_auto_pick(monkeypatch):
    checkout.forget_pick()
    checkout.bind_setting(None)
    monkeypatch.setattr(checkout, "auto_pick", lambda: None)
    monkeypatch.setattr(checkout, "NEVER_PICKED", frozenset())
    yield
    checkout.forget_pick()
    checkout.bind_setting(None)


@pytest.fixture(autouse=True)
def _signing(monkeypatch):
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))
