
from __future__ import annotations

import pytest

from src.cplugs.devwidgetlab.drafts import checkout


@pytest.fixture(autouse=True)
def no_auto_pick(monkeypatch):
    checkout.forget_pick()
    checkout.bind_setting(None)
    monkeypatch.setattr(checkout, "auto_pick", lambda: None)
    yield
    checkout.forget_pick()
    checkout.bind_setting(None)
