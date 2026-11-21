
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.json_artifact import UnreadableArtifact
from src.core.plugin_registry import marker
from src.plugins.host import identity, owner_switch, registry_projection, registry_store, sideload
from src.plugins.host import state as owner_state

REPO = Path(__file__).resolve().parents[3]
UUID_A = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def support(tmp_path: Path) -> Path:
    folder = tmp_path / "support"
    folder.mkdir()
    ensure_db_migrated(folder, 4, "0.8.2")
    return folder


def registry(support: Path) -> Dict[str, Any]:
    return json.loads(registry_store.registry_path(support).read_text(encoding="utf-8"))


def db_marker(support: Path) -> marker.Marker:
    conn = connect(db_path_for(support), create=False)
    try:
        held = marker.read_marker(conn)
    finally:
        conn.close()
    assert held is not None
    return held


def seed(support: Path) -> None:
    def put(docs: registry_store.Documents) -> None:
        docs.load("state").update(version=1, cplugs={
            "huddle": {"enabled": True, "grants": ["net.loopback"], "settings": {"view": "list"}, "revision": 12, "digest": None, "updated_at": 1.0},
            "clock": {"enabled": True, "grants": ["net.fetch"], "settings": {}, "revision": 3, "digest": "sha256:aa", "updated_at": 2.0},
            "oldtool": {"enabled": False, "grants": ["net.fetch"], "settings": {"a": 1}, "revision": 2, "digest": "sha256:bb", "updated_at": 3.0}})
        docs.load("installs").update(version=1, installs={
            "clock": {"uuid": UUID_A, "catalog_id": "acme/clock", "publisher_key_id": "k1-acme"},
            "myclock": {"uuid": "f" * 32, "catalog_id": "local/myclock", "source": "/src/myclock"},
            "oldtool": {"uuid": "e" * 32, "catalog_id": "acme/oldtool", "publisher_key_id": "k1-acme",
                        "removed": {"at": "2026-11-09T00:00:00Z", "version": "0.9.1", "publisher_key_id": "k1-acme"}}})
        docs.load("sideload").update(items={"myclock": {"source": "/src/myclock", "digest": "sha256:cc"}})
        docs.load("third_party").update(enabled=True)
    registry_store.commit(support, put)


def test_the_projection_has_the_plan_shape(support):
    seed(support)
    doc = registry(support)
    assert set(doc) == {"schema", "generation", "switches", "items", "tombstones", "other"} and doc["schema"] == 1
    assert doc["other"] == {"state": {"version": 1}, "installs": {"version": 1}}
    assert doc["switches"] == {"third_party": True}
    huddle = doc["items"]["huddle"]
    assert huddle == {"kind": "feature", "enabled": True, "grants": ["net.loopback"], "settings": {"view": "list"}, "revision": 12, "digest": None, "updated_at": 1.0}
    clock = doc["items"]["clock"]
    assert (clock["kind"], clock["source"], clock["catalog_id"], clock["install_uuid"], clock["publisher_key_id"]) == ("plugin", "catalog", "acme/clock", UUID_A, "k1-acme")
    assert clock["grants"] == ["net.fetch"] and clock["revision"] == 3 and clock["digest"] == "sha256:aa"
    mine = doc["items"]["myclock"]
    assert (mine["source"], mine["source_path"], mine["catalog_id"], mine["enabled"]) == ("folder", "/src/myclock", "local/myclock", False)
    assert "data_dir" not in json.dumps(doc)
    assert "oldtool" not in doc["items"]
    tomb = doc["tombstones"]["oldtool"]
    assert {k: tomb[k] for k in ("catalog_id", "install_uuid", "publisher_key_id", "version", "grants", "settings", "removed_at")} == {
        "catalog_id": "acme/oldtool", "install_uuid": "e" * 32, "publisher_key_id": "k1-acme", "version": "0.9.1",
        "grants": ["net.fetch"], "settings": {"a": 1}, "removed_at": "2026-11-09T00:00:00Z"}
    assert tomb["ledger"]["removed"]["version"] == "0.9.1" and tomb["state"]["revision"] == 2


def test_projection_is_pure_and_matches_the_files_it_came_from(support):
    seed(support)
    doc = registry(support)
    docs = {n: json.loads(registry_store.legacy_path(support, n).read_text()) for n in registry_store.LEGACY_FILES}
    assert registry_projection.build_document(generation=doc["generation"], docs=docs) == doc


def test_every_legacy_writer_bumps_the_generation_and_the_marker(support):
    seed(support)
    seen = [registry(support)["generation"]]
    steps = [
        lambda: identity.register_install(support, "newone", "acme/newone", frozenset(), publisher_key_id="k1-acme"),
        lambda: owner_switch.write(support, False),
        lambda: sideload.set_switch(support, True, hours=None),
        lambda: owner_state.switch_off(support, "clock"),
        lambda: owner_state.strip_consent(support, "clock"),
        lambda: owner_state.forget(support, "huddle"),
        lambda: identity.release_install(support, "newone"),
    ]
    for step in steps:
        step()
        seen.append(registry(support)["generation"])
    assert seen == list(range(seen[0], seen[0] + len(steps) + 1))
    assert db_marker(support).generation == seen[-1] and db_marker(support).schema == 1
    doc = registry(support)
    assert "huddle" not in doc["items"] and doc["items"]["clock"]["enabled"] is False and doc["items"]["clock"]["grants"] == []
    assert doc["switches"] == {"third_party": False} and "newone" not in doc["items"]


def test_one_call_that_writes_two_stores_projects_once(support):
    seed(support)
    before = registry(support)["generation"]

    def both(docs: registry_store.Documents) -> None:
        docs.load("third_party").update(enabled=False)
        docs.load("installs")["installs"]["clock"]["publisher_key_id"] = "k2"

    registry_store.commit(support, both)
    after = registry(support)
    assert after["generation"] == before + 1
    assert after["switches"] == {"third_party": False} and after["items"]["clock"]["publisher_key_id"] == "k2"


def test_commit_writes_only_the_stores_that_changed(support):
    seed(support)
    untouched = registry_store.legacy_path(support, "sideload")
    inode = untouched.stat().st_ino
    registry_store.commit(support, lambda docs: docs.load("third_party").update(enabled=False))
    assert untouched.stat().st_ino == inode


def test_a_mutator_that_raises_leaves_every_file_unchanged(support):
    seed(support)
    names = [*registry_store.LEGACY_FILES.values(), registry_store.REGISTRY_FILE]
    before = {n: (support / "cplugs" / n).read_bytes() for n in names}

    def boom(docs: registry_store.Documents) -> None:
        docs.load("state")["cplugs"]["clock"]["enabled"] = False
        docs.load("third_party").update(enabled=False)
        raise RuntimeError("the writer failed half way")

    with pytest.raises(RuntimeError):
        registry_store.commit(support, boom)
    assert {n: (support / "cplugs" / n).read_bytes() for n in names} == before
    assert db_marker(support).generation == json.loads(before["plugins.json"])["generation"]


def test_an_unreadable_store_is_never_written_over_and_nothing_is_projected(support):
    seed(support)
    generation = registry(support)["generation"]
    registry_store.legacy_path(support, "sideload").write_text("{ torn")
    with pytest.raises(UnreadableArtifact):
        registry_store.commit(support, lambda docs: docs.load("sideload").update(x=1))
    assert registry_store.legacy_path(support, "sideload").read_text() == "{ torn"
    owner_switch.write(support, False)
    assert json.loads(registry_store.legacy_path(support, "third_party").read_text()) == {"enabled": False}
    assert registry(support)["generation"] == generation


def test_plugins_json_is_readable_by_the_owner_and_keeps_a_backup_of_the_previous_bytes(support):
    seed(support)
    path = registry_store.registry_path(support)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    previous = path.read_bytes()
    owner_switch.write(support, False)
    assert path.with_suffix(".json.bak").read_bytes() == previous
    assert stat.S_IMODE(registry_store.legacy_path(support, "state").stat().st_mode) == 0o600


def test_a_file_higher_than_the_marker_is_accepted_and_the_next_write_goes_above_both(support):
    seed(support)
    path = registry_store.registry_path(support)
    path.write_text(json.dumps({**registry(support), "generation": 50}))
    assert db_marker(support).generation == 1
    owner_switch.write(support, False)
    assert registry(support)["generation"] == 51 and db_marker(support).generation == 51


def test_a_file_lower_than_the_marker_never_makes_the_generation_go_back(support):
    seed(support)
    conn = connect(db_path_for(support), create=False)
    try:
        marker.write_marker(conn, 90, 1)
    finally:
        conn.close()
    owner_switch.write(support, False)
    assert registry(support)["generation"] == 91


def test_without_a_database_the_write_still_succeeds(tmp_path):
    folder = tmp_path / "bare"
    folder.mkdir()
    assert owner_switch.write(folder, True) is True
    assert registry(folder)["generation"] == 1 and registry(folder)["switches"] == {"third_party": True}


def test_describe_reports_generation_and_source(support, tmp_path):
    assert registry_store.describe(tmp_path / "nothing") == (None, "none")
    seed(support)
    assert registry_store.describe(support) == (registry(support)["generation"], "legacy_files")
    registry_store.registry_path(support).write_text("not json")
    assert registry_store.describe(support) == (None, "legacy_files")


HOLDER = """
import sys
from pathlib import Path
from src.plugins.host import registry_store
with registry_store.exclusive(Path(sys.argv[1])):
    print("locked", flush=True)
    sys.stdin.readline()
"""


def test_a_second_process_is_refused_while_another_holds_the_lock(support, monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", HOLDER, str(support)], cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(REPO)})
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(registry_store.RegistryBusy):
            with registry_store.exclusive(support, timeout=0.3):
                pytest.fail("the lock was granted while another process held it")
        monkeypatch.setattr(registry_store, "LOCK_WAIT_SECONDS", 0.3)
        assert owner_switch.write(support, True) is False
        with pytest.raises(owner_state.StateWriteFailed):
            owner_state.forget(support, "x")
        with pytest.raises(owner_state.StateWriteFailed):
            identity.release_install(support, "x")
        with pytest.raises(sideload.SideloadRefused) as refused:
            sideload.forget(support, "x")
        assert refused.value.code == "registry_busy" and refused.value.status == 503
        assert not registry_store.legacy_path(support, "third_party").exists()
    finally:
        child.stdin.write("\n")
        child.stdin.flush()
        child.wait(timeout=30)
    with registry_store.exclusive(support, timeout=1.0):
        pass



def test_a_corrupt_database_never_fails_a_write_and_the_file_is_still_projected(support):
    seed(support)
    before = registry(support)["generation"]
    db_path_for(support).write_bytes(b"this is not a sqlite database" * 50)
    assert owner_switch.write(support, False) is True
    assert registry_store.legacy_path(support, "third_party").exists()
    assert registry(support)["generation"] == before + 1 and registry(support)["switches"] == {"third_party": False}


def test_a_writer_with_nothing_to_do_never_creates_the_cplugs_folder(tmp_path):
    folder = tmp_path / "support"
    (folder / "addons").mkdir(parents=True)
    assert owner_state.forget(folder, "nothing") is False
    assert owner_state.switch_off(folder, "nothing") is False
    assert identity.release_install(folder, "nothing") is False
    assert not (folder / "cplugs").exists()
    assert owner_switch.write(folder, True) is True
    assert registry_store.lock_path(folder).exists()
