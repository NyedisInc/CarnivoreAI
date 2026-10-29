from __future__ import annotations

import pytest

import src.config  # noqa: F401
from src.core.automations import seed, targets
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setitem(targets.RUNNERS, "recipe", lambda *a, **k: None)
    return AutomationStore(storage_for(tmp_path))


def _rows(store):
    return [r for r in store.list_all() if r["seed_key"] == seed.SEED_KEY]


def test_seed_lifecycle(store):
    assert seed.apply(store) is True
    (row,) = _rows(store)
    assert row["enabled"] is False and row["trigger"]["cron"] == "0 7 * * 1" and row["delivery"]["notify_on"] == "report" and row["created_by"] == "seed"
    assert row["target"]["recipe"] == "scrooge" and row["next_fire_at"] is None

    assert seed.apply(store) is False
    assert len(_rows(store)) == 1

    store.set_enabled(row["automation_id"], True)
    assert seed.apply(store) is False
    (row,) = _rows(store)
    assert row["enabled"] is True and row["next_fire_at"] is not None

    store.delete(row["automation_id"])
    assert _rows(store) == []
    assert seed.apply(store) is False
    assert _rows(store) == []
