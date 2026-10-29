
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ledger_wd_")
)
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ledger_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.catalog.index_state import IndexStateStore, RevocationStore
from src.core.catalog.revocation import RevocationRef
from src.core.db import connect, db_path_for, table_exists
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.skills.ledger import (
    GLOBAL_PROJECT_PATH,
    HARNESS_CLAUDE,
    HARNESS_CODEX,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    AlreadyInstalled,
    InstallLedger,
    InstallNotFound,
    InstallTarget,
    InstalledItem,
    LedgerError,
    StaleRevision,
    as_dict,
)

V27_TABLES = (
    "installed_items",
    "installed_item_targets",
    "catalog_revocations_seen",
    "catalog_index_state",
)

STAMP = "2026-09-15T12:00:00Z"
LATER = "2026-09-15T13:00:00Z"


def make_item(
    *,
    install_id: str = "i1",
    item_id: str = "alex/review",
    name: str = "review",
    scope: str = SCOPE_GLOBAL,
    project_path: str = GLOBAL_PROJECT_PATH,
    version: str = "1.0.0",
    auto_update: bool = False,
) -> InstalledItem:
    return InstalledItem(
        install_id=install_id,
        item_id=item_id,
        kind="skill",
        publisher=item_id.split("/")[0],
        name=name,
        version=version,
        digest="sha256:" + "a" * 64,
        scope=scope,
        project_path=project_path,
        auto_update=auto_update,
        source_index_url="https://example.invalid/index.json",
        consented_digest=None,
        consented_body_sha=None,
        publisher_key_id="RWQtestkeyid",
        revision=1,
        installed_at=STAMP,
        updated_at=STAMP,
        consent_via="sheet",
    )


@pytest.fixture
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as handle:
        yield handle


@pytest.fixture
def ledger(conn):
    return InstallLedger(conn)



def test_fresh_install_reaches_v27_with_all_four_tables(tmp_path) -> None:
    state = ensure_db_migrated(tmp_path, 4, "0.8.2")
    assert state.status == "ok"
    assert state.schema_version == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION >= 27
    with closing(connect(db_path_for(tmp_path))) as handle:
        for table in V27_TABLES:
            assert table_exists(handle, table), table


def test_a_v26_database_gains_the_tables_at_v27(tmp_path) -> None:
    with closing(connect(db_path_for(tmp_path))) as handle:
        run_chain(handle, 0, 26)
        for table in V27_TABLES:
            assert not table_exists(handle, table), table

        run_chain(handle, 26, 27)
        for table in V27_TABLES:
            assert table_exists(handle, table), table


def test_the_v27_step_is_idempotent(tmp_path) -> None:
    with closing(connect(db_path_for(tmp_path))) as handle:
        run_chain(handle, 0, CURRENT_SCHEMA_VERSION)
        InstallLedger(handle).insert(make_item())

        run_chain(handle, 26, 27)

        assert InstallLedger(handle).get("i1") is not None



def test_the_same_item_twice_in_one_scope_is_refused(ledger) -> None:
    first = ledger.insert(make_item(install_id="i1"))

    with pytest.raises(AlreadyInstalled) as caught:
        ledger.insert(make_item(install_id="i2", name="review-again"))

    assert caught.value.existing == first
    assert ledger.list() == (first,)


def test_two_different_items_claiming_one_name_is_refused(ledger) -> None:
    first = ledger.insert(make_item(install_id="i1", item_id="alex/review"))

    with pytest.raises(AlreadyInstalled) as caught:
        ledger.insert(
            make_item(install_id="i2", item_id="someone/review", name="review")
        )

    assert caught.value.existing.item_id == "alex/review"
    assert caught.value.existing == first


def test_a_reused_install_id_is_refused_as_already_installed(ledger) -> None:
    first = ledger.insert(make_item(install_id="i1"))

    with pytest.raises(AlreadyInstalled) as caught:
        ledger.insert(
            make_item(install_id="i1", item_id="other/thing", name="thing")
        )

    assert caught.value.existing == first


def test_one_item_installed_globally_and_for_a_project_coexist(ledger) -> None:
    project = "/Users/a/Development/thing"
    globally = ledger.insert(make_item(install_id="i1"))
    scoped = ledger.insert(
        make_item(
            install_id="i2", scope=SCOPE_PROJECT, project_path=project
        )
    )

    assert ledger.list(scope=SCOPE_GLOBAL) == (globally,)
    assert ledger.list(scope=SCOPE_PROJECT, project_path=project) == (scoped,)
    assert set(ledger.find_name_any_scope("review")) == {globally, scoped}


def test_two_projects_may_each_install_the_same_item(ledger) -> None:
    a = ledger.insert(
        make_item(install_id="i1", scope=SCOPE_PROJECT, project_path="/p/a")
    )
    b = ledger.insert(
        make_item(install_id="i2", scope=SCOPE_PROJECT, project_path="/p/b")
    )

    assert ledger.find("alex/review", SCOPE_PROJECT, "/p/a") == a
    assert ledger.find("alex/review", SCOPE_PROJECT, "/p/b") == b



def test_foreign_keys_are_on_for_the_connection_under_test(conn) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_deleting_an_install_cascades_its_targets_away(ledger, conn) -> None:
    ledger.insert(
        make_item(),
        [
            InstallTarget("i1", HARNESS_CLAUDE, "/Users/a/.claude/skills/review"),
            InstallTarget("i1", HARNESS_CODEX, "/Users/a/.codex/skills/review"),
        ],
    )
    assert len(ledger.targets("i1")) == 2

    assert ledger.delete("i1") is True

    assert ledger.get("i1") is None
    assert ledger.targets("i1") == ()
    left = conn.execute(
        "SELECT COUNT(*) FROM installed_item_targets"
    ).fetchone()[0]
    assert left == 0


def test_deleting_something_that_is_not_there_is_false_not_an_error(
    ledger,
) -> None:
    assert ledger.delete("nope") is False


def test_targets_come_back_in_path_order_with_their_harness(ledger) -> None:
    ledger.insert(
        make_item(),
        [
            InstallTarget("i1", HARNESS_CODEX, "/z/last"),
            InstallTarget("i1", HARNESS_CLAUDE, "/a/first"),
        ],
    )

    stored = ledger.targets("i1")

    assert [t.path for t in stored] == ["/a/first", "/z/last"]
    assert [t.harness for t in stored] == [HARNESS_CLAUDE, HARNESS_CODEX]


def test_replace_targets_swaps_the_whole_list(ledger) -> None:
    ledger.insert(make_item(), [InstallTarget("i1", HARNESS_CLAUDE, "/old")])

    result = ledger.replace_targets(
        "i1", [InstallTarget("i1", HARNESS_CLAUDE, "/new")]
    )

    assert [t.path for t in result] == ["/new"]
    assert [t.path for t in ledger.targets("i1")] == ["/new"]


def test_replace_targets_on_an_unknown_install_raises(ledger) -> None:
    with pytest.raises(InstallNotFound):
        ledger.replace_targets("nope", [])



def test_update_with_the_current_revision_bumps_it(ledger) -> None:
    ledger.insert(make_item())

    updated = ledger.update(
        "i1", expected_revision=1, now=LATER, version="1.1.0", auto_update=True
    )

    assert updated.revision == 2
    assert updated.version == "1.1.0"
    assert updated.auto_update is True
    assert updated.updated_at == LATER
    assert updated.installed_at == STAMP
    assert ledger.get("i1") == updated


def test_update_with_a_stale_revision_raises_and_writes_nothing(
    ledger,
) -> None:
    ledger.insert(make_item())
    winner = ledger.update("i1", expected_revision=1, now=LATER, version="1.1.0")

    with pytest.raises(StaleRevision) as caught:
        ledger.update(
            "i1", expected_revision=1, now=LATER, version="9.9.9"
        )

    assert caught.value.current == winner
    assert caught.value.current.revision == 2
    assert ledger.get("i1").version == "1.1.0"
    assert as_dict(caught.value.current)["version"] == "1.1.0"


def test_update_refuses_a_column_it_does_not_own(ledger) -> None:
    ledger.insert(make_item())

    for field in ("revision", "installed_at", "updated_at", "install_id"):
        with pytest.raises(LedgerError):
            ledger.update("i1", expected_revision=1, now=LATER, **{field: "x"})


def test_update_with_no_fields_is_refused(ledger) -> None:
    ledger.insert(make_item())

    with pytest.raises(LedgerError):
        ledger.update("i1", expected_revision=1, now=LATER)


def test_update_of_a_missing_row_is_not_a_stale_revision(ledger) -> None:
    with pytest.raises(InstallNotFound):
        ledger.update("nope", expected_revision=1, now=LATER, version="2")


def test_renaming_onto_a_taken_name_raises_already_installed(ledger) -> None:
    ledger.insert(make_item(install_id="i1", item_id="alex/review", name="review"))
    ledger.insert(
        make_item(install_id="i2", item_id="alex/triage", name="triage")
    )

    with pytest.raises(AlreadyInstalled) as caught:
        ledger.update("i2", expected_revision=1, now=LATER, name="review")

    assert caught.value.existing.install_id == "i1"
    assert ledger.get("i2").name == "triage"
    assert ledger.get("i2").revision == 1



def test_find_and_find_by_name_ask_different_questions(ledger) -> None:
    stored = ledger.insert(make_item())

    assert ledger.find("alex/review", SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) == stored
    assert ledger.find_by_name("review", SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) == stored
    assert ledger.find("someone/review", SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) is None
    assert ledger.find_by_name("triage", SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) is None


def test_auto_update_round_trips_as_a_bool(ledger) -> None:
    stored = ledger.insert(make_item(auto_update=True))

    assert stored.auto_update is True
    assert ledger.get("i1").auto_update is True

    turned_off = ledger.update(
        "i1", expected_revision=1, now=LATER, auto_update=False
    )
    assert turned_off.auto_update is False


def test_list_is_totally_ordered_by_name_then_install_id(ledger) -> None:
    ledger.insert(make_item(install_id="i2", item_id="alex/b", name="b"))
    ledger.insert(make_item(install_id="i1", item_id="alex/a", name="a"))

    assert [item.name for item in ledger.list()] == ["a", "b"]



def test_record_writes_a_first_serial_and_raises_it(conn) -> None:
    store = IndexStateStore(conn)
    assert store.get("key-a") is None

    store.record("key-a", 10, STAMP, 'W/"one"')
    assert store.get("key-a").last_verified_serial == 10

    store.record("key-a", 42, LATER, 'W/"two"')
    stored = store.get("key-a")
    assert stored.last_verified_serial == 42
    assert stored.last_verified_at == LATER
    assert stored.etag == 'W/"two"'


def test_record_never_lowers_the_serial_and_keeps_the_old_etag(conn) -> None:
    store = IndexStateStore(conn)
    store.record("key-a", 42, STAMP, 'W/"high"')

    returned = store.record("key-a", 7, LATER, 'W/"low"')

    assert returned.last_verified_serial == 42
    stored = store.get("key-a")
    assert stored.last_verified_serial == 42
    assert stored.last_verified_at == STAMP
    assert stored.etag == 'W/"high"'


def test_an_equal_serial_refreshes_the_timestamp_and_etag(conn) -> None:
    store = IndexStateStore(conn)
    store.record("key-a", 42, STAMP, 'W/"one"')

    store.record("key-a", 42, LATER, 'W/"two"')

    stored = store.get("key-a")
    assert stored.last_verified_at == LATER
    assert stored.etag == 'W/"two"'


def test_the_floor_is_kept_per_signing_key(conn) -> None:
    store = IndexStateStore(conn)
    store.record("key-a", 42, STAMP)
    store.record("key-b", 3, STAMP)

    assert store.get("key-a").last_verified_serial == 42
    assert store.get("key-b").last_verified_serial == 3


def test_a_missing_etag_is_stored_as_none(conn) -> None:
    store = IndexStateStore(conn)
    store.record("key-a", 1, STAMP)

    assert store.get("key-a").etag is None



def _ref(subject: str, since: str = STAMP) -> RevocationRef:
    return RevocationRef(kind="version", subject=subject, since=since)


def test_remember_is_idempotent(conn) -> None:
    store = RevocationStore(conn)
    refs = [_ref("alex/review@1.0.0"), _ref("alex/review@1.1.0")]

    assert store.remember("key-a", refs) == 2
    assert store.remember("key-a", refs) == 0

    assert store.seen("key-a") == frozenset(refs)


def test_a_re_dated_revocation_does_not_overwrite_the_stored_one(conn) -> None:
    store = RevocationStore(conn)
    store.remember("key-a", [_ref("alex/review@1.0.0", since=STAMP)])

    store.remember("key-a", [_ref("alex/review@1.0.0", since=LATER)])

    assert store.seen("key-a") == frozenset(
        {_ref("alex/review@1.0.0", since=STAMP)}
    )


def test_revocations_are_kept_per_index_key_id(conn) -> None:
    store = RevocationStore(conn)
    store.remember("key-a", [_ref("alex/review@1.0.0")])
    store.remember("key-b", [_ref("someone/else@2.0.0")])

    assert store.seen("key-a") == frozenset({_ref("alex/review@1.0.0")})
    assert store.seen("key-b") == frozenset({_ref("someone/else@2.0.0")})
    assert store.seen("key-c") == frozenset()


def test_the_revocation_store_has_no_way_to_remove_one(conn) -> None:
    store = RevocationStore(conn)

    removers = [
        name
        for name in dir(store)
        if not name.startswith("_")
        and any(word in name for word in ("delete", "remove", "forget", "clear"))
    ]

    assert removers == []
