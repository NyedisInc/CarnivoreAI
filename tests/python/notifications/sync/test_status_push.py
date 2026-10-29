
from __future__ import annotations

import pytest

from src.core.notifications.sync import status as status_mod
from src.core.notifications.sync.status import SyncStatus

from .test_converge import create, link_all, rounds


@pytest.fixture
def announced(monkeypatch):
    topics_seen = []
    monkeypatch.setattr(status_mod.resource_push, "notify", lambda topic: topics_seen.append(topic))
    return topics_seen


def test_a_pass_that_changes_no_settings_but_updates_a_peer_status_announces_once(cluster, make, announced):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    create(a)
    rounds(a, b)
    announced.clear()
    revs = (a.doc()["rev"], b.doc()["rev"])
    assert a.sync() == {"B": "no_change"}
    assert (a.doc()["rev"], b.doc()["rev"]) == revs
    assert announced == ["notification_settings"]


def test_recording_an_identical_status_announces_nothing(announced):
    status = SyncStatus()
    status.record("iid", "ok", 100.0)
    assert announced == ["notification_settings"]
    status.record("iid", "ok", 100.0)
    assert announced == ["notification_settings"]
    status.record("iid", "ok", 101.0)
    status.record("iid", "error", 101.0)
    assert announced == ["notification_settings"] * 3
