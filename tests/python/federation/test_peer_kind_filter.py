
from __future__ import annotations

import re
from contextlib import closing
from pathlib import Path

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts
from src.core.hosts import registry, remote_listing, remote_readopt, store

SRC = Path(__file__).resolve().parents[3] / "src"


PEER_KEY = peer_hosts.host_key_for("AB-12")


@pytest.fixture
def conn(tmp_path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as c:
        peer_hosts.upsert(c, install_id="AB-12", label="studio", grant_id="g", fid="f", initiator=True)
        c.execute("INSERT INTO hosts (key, label, ssh_target, socket, enabled, created_at, updated_at) "
                  "VALUES ('ssh-box', 'box', 'box', 'carnivore-remote', 1, 'x', 'x')")
        for key in (PEER_KEY, "ssh-box"):
            rid = add_row(c, uuid=f"u-{key}", name=f"n-{key}", epoch=5, origin="created", socket="s")
            c.execute("UPDATE sessions SET host_key = ? WHERE id = ?", (key, rid))
        yield c


def test_the_boot_readopt_names_only_ssh_hosts(conn, tmp_path):
    got = remote_readopt.open_remote_hosts(lambda: connect(db_path_for(tmp_path), create=False))
    assert got == ["ssh-box"]


def test_the_registry_refuses_a_peer_host(conn):
    peer = store.get_host(conn, PEER_KEY)
    assert peer.kind == "peer"
    with pytest.raises(registry.HostUnavailable):
        registry.HostRegistry._check(peer)


def test_the_reap_reconcile_skips_a_peer_host(conn, tmp_path):
    from src.core.session_status_map import StatusMap

    class Manager:
        def _writable_datastore_connection(self):
            return connect(db_path_for(tmp_path), create=False)

    empty = StatusMap({}, complete=True, socket="s")
    assert remote_listing.reconcile_host_rows(Manager(), PEER_KEY, "s", empty) is None
    assert conn.execute("SELECT lifecycle FROM sessions WHERE host_key = '" + PEER_KEY + "'").fetchone()[0] == "running"
    assert remote_listing.reconcile_host_rows(Manager(), "ssh-box", "s", empty) is not None


def test_register_every_hosts_statement_outside_the_store_names_its_kind():
    found = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        for m in re.finditer(r"FROM hosts\b[^\"']*", text):
            if "kind" not in m.group(0) and "peer_install_id" not in m.group(0):
                found.add(str(path.relative_to(SRC)))
    assert found == {"core/hosts/store.py"}
