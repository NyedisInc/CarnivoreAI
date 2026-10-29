
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import db_models, relay_keychain
from src.core.db import connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_schema_audit import UNGATED_VERSION_DDL
from src.core.federation import fed_key, grants
from src.core.federation.ddl import DDL_V43, REVERSAL_SQL_V43
from src.core.archive_db_partition import APP_TABLES


@pytest.fixture()
def conn(tmp_path: Path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as c:
        yield c


def _key(seed_byte: int = 1) -> str:
    return fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([seed_byte]) * 32))


def test_the_schema_has_43_and_the_table_exists(conn):
    assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 43
    cols = {r[1] for r in conn.execute("PRAGMA table_info(federation_grants)")}
    assert {"grant_id", "peer_install_id", "public_key", "fid", "scopes", "remote_grant_id",
            "revoked_at"} <= cols


def test_the_maps_carry_v43(conn):
    assert UNGATED_VERSION_DDL[43] == DDL_V43
    assert db_models.REVERSAL_SQL_V43 == REVERSAL_SQL_V43
    assert db_models.REVERSAL_DESTROYS[43] == ("federation_grants (whole table)",)
    assert "federation_grants" in APP_TABLES


def test_the_step_is_idempotent_and_the_reversal_drops_it(conn):
    for statement in DDL_V43:
        conn.execute(statement)
    for statement in REVERSAL_SQL_V43:
        conn.execute(statement)
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'federation_grants'").fetchone()


def test_create_get_revoke_and_regrant(conn):
    g = grants.create_grant(conn, peer_install_id="iid-hosta", public_key=_key(), label=" hosta ")
    assert g.label == "hosta" and g.allows("sessions") and grants.get_live(conn, g.grant_id) == g
    with pytest.raises(grants.GrantError) as dup:
        grants.create_grant(conn, peer_install_id="iid-hosta", public_key=_key(), label="x")
    assert dup.value.code == "grant_exists"
    assert grants.revoke(conn, g.grant_id) is True and grants.revoke(conn, g.grant_id) is False
    assert grants.get_live(conn, g.grant_id) is None and grants.get_grant(conn, g.grant_id).revoked
    again = grants.create_grant(conn, peer_install_id="iid-hosta", public_key=_key(2), label="hosta")
    assert again.grant_id != g.grant_id and len(grants.list_grants(conn)) == 2


def test_bad_key_and_unknown_scope_are_refused(conn):
    with pytest.raises(grants.GrantError) as e1:
        grants.create_grant(conn, peer_install_id="a", public_key="not-a-key", label="x")
    assert e1.value.code == "public_key_invalid"
    with pytest.raises(grants.GrantError) as e2:
        grants.create_grant(conn, peer_install_id="a", public_key=_key(), label="x", scopes=("root",))
    assert e2.value.code == "scope_unknown"


def test_unpair_deletes_the_row(conn):
    g = grants.create_grant(conn, peer_install_id="a", public_key=_key(), label="x")
    assert grants.delete_grant(conn, g.grant_id) is True and grants.get_grant(conn, g.grant_id) is None


def test_the_federation_key_reads_the_federation_service_and_mints_create_only():
    calls = []
    store = {}

    def read(service, account):
        calls.append(("read", service))
        v = store.get((service, account))
        return (relay_keychain.READ_OK, v) if v else (relay_keychain.READ_ABSENT, None)

    def write(service, account, secret, replace=True):
        calls.append(("write", service, replace))
        store[(service, account)] = secret

    key = fed_key.load_key("install-1", read=read, write=write)
    again = fed_key.load_key("install-1", read=read, write=write)
    assert key.raw_pub == again.raw_pub
    assert {c[1] for c in calls} == {relay_keychain.FEDERATION_KEY_SERVICE}
    assert ("write", relay_keychain.FEDERATION_KEY_SERVICE, False) in calls
    assert fed_key.fid_for(key.raw_pub) == key.device_id


def test_the_production_keychain_item_is_refused_under_test():
    state, value = relay_keychain.read_password_state(relay_keychain.FEDERATION_KEY_SERVICE, "x")
    assert state == relay_keychain.READ_UNAVAILABLE and value is None
    with pytest.raises(relay_keychain.KeychainWriteError):
        relay_keychain.write_password(relay_keychain.FEDERATION_KEY_SERVICE, "x", "abc")


def test_local_fid_is_the_fingerprint_of_the_federation_key_and_never_raises(tmp_path):
    ensure_db_migrated(tmp_path)
    store = {}

    def read(service, account):
        v = store.get((service, account))
        return (relay_keychain.READ_OK, v) if v else (relay_keychain.READ_ABSENT, None)

    def write(service, account, secret, replace=True):
        store[(service, account)] = secret

    fid = fed_key.local_fid(tmp_path, read=read, write=write)
    (service, _account), _ = next(iter(store.items()))
    assert service == relay_keychain.FEDERATION_KEY_SERVICE and fid and len(fid) == 26
    assert fed_key.local_fid(tmp_path, read=read, write=write) == fid
    assert fed_key.local_fid(tmp_path) is None
    assert fed_key.local_fid(tmp_path / "nowhere") is None
