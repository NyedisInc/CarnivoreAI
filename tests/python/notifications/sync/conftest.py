
from __future__ import annotations

import pytest

from .fakes import Cluster, Computer


@pytest.fixture(autouse=True)
def _quiet_topics(monkeypatch):
    from src.core.notifications.settings_doc import store as store_mod

    monkeypatch.setattr(store_mod.resource_push, "notify", lambda *a, **k: None)


@pytest.fixture
def cluster() -> Cluster:
    return Cluster()


@pytest.fixture
def make(tmp_path, cluster):
    return lambda name: Computer(name, tmp_path, cluster)
