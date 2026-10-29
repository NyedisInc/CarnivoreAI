
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.core import resource_push
from src.core.db import connect
from src.core.federation import discovery, peer_hosts
from src.core.hosts import store
from src.core.resource_push import topics
from tests.layouts_helpers import migrated


@pytest.fixture
def rung(monkeypatch) -> list:
    seen: list = []
    monkeypatch.setattr(resource_push, "notify", lambda topic: seen.append(topic))
    return seen


def test_the_topic_is_announced_in_hello() -> None:
    assert topics.PACK_ROSTER in topics.RESOURCE_TOPICS


def test_every_hosts_table_writer_rings_the_topic(tmp_path: Path, rung: list) -> None:
    db_path = migrated(tmp_path / "state")
    with closing(connect(db_path, create=False)) as conn:
        host = store.create_host(conn, label="Hosta", ssh_target="acme@hosta")
        store.update_host(conn, host.key, label="Hosta 2")
        store.record_probe(conn, host.key, {**{name: None for name in store.PROBE_COLUMNS}, "probe_state": "ok"})
        store.delete_host(conn, host.key)
        peer_hosts.upsert(conn, install_id="iid-a", label="a", grant_id="g", fid="f", initiator=True)
        peer_hosts.set_state(conn, "iid-a", "connected", 1)
        peer_hosts.set_initiator(conn, "iid-a", False)
        peer_hosts.set_fid(conn, "iid-a", "f2")
        peer_hosts.delete(conn, "iid-a")
    assert rung == [topics.PACK_ROSTER] * 9


def test_discovery_rings_only_when_what_it_answers_moved(rung: list) -> None:
    svc = discovery.Discovery(config_path=Path("/nonexistent/config.json"))
    svc.state = discovery.STATE_ADVERTISING
    svc.state = discovery.STATE_ADVERTISING
    svc.browse_state = "browsing"
    svc.advertising_wanted = False
    assert rung == [topics.PACK_ROSTER] * 3
    rung.clear()
    svc._on_resolve(0, "other", "other.local.", 22, b"")
    assert rung == [topics.PACK_ROSTER]
