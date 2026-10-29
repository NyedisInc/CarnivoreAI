
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core import db, db_models
from src.core.computers import store
from src.core.computers.ddl import apply_computer_links
from src.core.db_schema_audit import audit_schema
from src.core.db_steps import STEPS


@pytest.fixture()
def conn(tmp_path: Path):
    c = sqlite3.connect(tmp_path / "t.db", isolation_level=None)
    apply_computer_links(c)
    store.CACHE.replace([])
    yield c
    c.close()


def _row(iid, **kw):
    kw.setdefault("role", "member")
    kw.setdefault("transport", "tls")
    return store.LinkRow(iid, updated_at="", **kw)


def test_put_get_cache_and_uniqueness(conn):
    store.put(conn, _row("a", cert_sha256="s1", link_fid="f1", cert_der=b"\x01", addresses=("10.0.0.2",)))
    got = store.get(conn, "a")
    assert got.addresses == ("10.0.0.2",) and got.cert_der == b"\x01" and got.updated_at
    assert store.CACHE.get("a") == got
    with pytest.raises(sqlite3.IntegrityError):
        store.put(conn, _row("b", cert_sha256="s1"))
    with pytest.raises(sqlite3.IntegrityError):
        store.put(conn, _row("b", link_fid="f1"))
    assert store.get(conn, "b") is None and store.CACHE.get("b") is None
    store.put(conn, _row("c", cert_sha256=None, link_fid=None))
    store.put(conn, _row("d", cert_sha256=None, link_fid=None))
    with pytest.raises(ValueError):
        store.put(conn, _row("e", role="boss"))
    assert store.delete(conn, "a") and store.CACHE.get("a") is None and not store.delete(conn, "a")


def test_roles_direction_and_touch(conn):
    store.put(conn, _row("m", role="main", join_kind="new", link_fid="fm"))
    store.put(conn, _row("x", role="member", link_fid="fx"))
    assert store.main_row(conn).peer_install_id == "m"
    assert [r.peer_install_id for r in store.members_tls(conn)] == ["x"]
    assert store.CACHE.tls_main_for("m") and store.CACHE.tls_main_for("x") is None
    ssh = store.set_direction(conn, "s", False)
    assert (ssh.role, ssh.transport, ssh.inbound_control) == ("peer", "ssh", 0)
    assert store.CACHE.tls_main_for("s") is None
    assert store.set_direction(conn, "x", False).inbound_control == 0
    assert store.get(conn, "x").provisional
    store.touch_link(conn, "x", first=True)
    first = store.get(conn, "x").first_link_at
    store.touch_link(conn, "x", first=True)
    row = store.get(conn, "x")
    assert first and row.first_link_at == first and row.last_link_at and not row.provisional


def test_provisional_sweep_and_next_cert(conn):
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    new = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    store.put(conn, _row("old", joined_at=old, cert_sha256="o"))
    store.put(conn, _row("fresh", joined_at=new, cert_sha256="n"))
    store.put(conn, _row("linked", joined_at=old, first_link_at=old, cert_sha256="l"))
    assert [r.peer_install_id for r in store.provisional_older_than(conn, 900)] == ["old"]
    assert store.set_next_cert(conn, "linked", b"\x02", "l2")
    assert store.promote_next_cert(conn, "linked", link_fid="fl")
    row = store.get(conn, "linked")
    assert (row.cert_der, row.cert_sha256, row.link_fid, row.next_cert_der) == (b"\x02", "l2", "fl", None)
    assert not store.promote_next_cert(conn, "linked") and not store.promote_next_cert(conn, "nobody")


def test_caller_transaction_and_rollback_refresh(conn):
    conn.execute("BEGIN IMMEDIATE")
    store.put(conn, _row("t", cert_sha256="t"))
    conn.execute("ROLLBACK")
    store.refresh(conn)
    assert store.CACHE.get("t") is None


def test_migration_step_and_audit(tmp_path: Path):
    assert db_models.CURRENT_SCHEMA_VERSION in STEPS or (db_models.CURRENT_SCHEMA_VERSION - 1) in STEPS
    c = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    STEPS[84](c)
    STEPS[84](c)
    assert audit_schema(c, 85).status in ("ok", "missing", "cannot_determine")
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    assert {"computer_links", "ux_computer_links_cert", "ux_computer_links_fid"} <= names
    assert "computer_links" in {o.name for o in __import__("src.core.db_schema_audit", fromlist=["x"]).declared_objects(85)}
