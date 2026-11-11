
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.plugin_health import model
from src.core.plugin_health.gather import build_report
from src.core.plugin_health.presence import GONE, PRESENT, UNREADABLE, folder_presence
from src.cplugs.host import folder_watch, identity, prune_gone, runtime, sidecar_registry, sideload
from src.cplugs.host import state as owner_state
from src.cplugs.runtime import sandbox
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401
from tests.python.plugin_health.world import StubProcess, make_world, write_code

CATALOG, LOCAL = "acme/gonecat", "local/gonedev"


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def served(tmp_path, client, owner_jwt, key_store):  # noqa: F811
    from src.main import app

    w = make_world(tmp_path)
    source = write_code(tmp_path / "dev" / "gonedev", "gonedev")
    code = w.install_catalog(CATALOG, enabled=True)
    w.install_catalog(LOCAL, enabled=True, local_source=source)
    w.settle()
    w.data = {}
    for item_id in (CATALOG, LOCAL):
        record = identity.lookup(w.state, item_id.partition("/")[2])
        folder = identity.data_dir(w.state, record.uuid)
        (folder / "files").mkdir(parents=True)
        (folder / "files" / "keep.txt").write_text(f"data of {item_id}")
        w.data[item_id] = folder
    w.procs = {n: StubProcess() for n in ("gonecat", "gonedev")}
    w.rt.supervisor._procs.update(w.procs)
    w.source, w.code = source, code
    app.state.sidecar_runtime, app.state.cplugs_host = w.rt, w.host
    w.host.app = app
    w.client, w.owner = client, bearer(owner_jwt)
    try:
        yield w
    finally:
        del app.state.sidecar_runtime, app.state.cplugs_host
        sidecar_registry.install(None)


def test_moving_either_folder_to_the_trash_removes_the_plugin_and_keeps_its_data(served, tmp_path):
    w = served
    assert w.client.get("/api/v1/cplugs/gonecat", headers=w.owner).status_code == 200
    assert w.client.get("/api/v1/cplugs/gonedev", headers=w.owner).status_code == 200
    data_before = {k: tree(v) for k, v in w.data.items()}
    trash = tmp_path / "Trash"
    trash.mkdir()
    shutil.move(str(w.source), str(trash / "gonedev"))
    shutil.move(str(w.code), str(trash / "gonecat"))

    assert asyncio.run(prune_gone.prune_pass(w.rt)) == [CATALOG, LOCAL]

    for stub in w.procs.values():
        assert stub.stops == ["folder_gone"]
    assert w.client.get("/api/v1/cplugs/gonecat", headers=w.owner).status_code == 404
    assert w.client.get("/api/v1/cplugs/gonedev", headers=w.owner).status_code == 404
    assert sidecar_registry.find("gonecat") is None and sidecar_registry.find("gonedev") is None
    assert {k: tree(v) for k, v in w.data.items()} == data_before

    rows = {r.item_id for r in w.rt.installed_rows()}
    assert CATALOG not in rows and LOCAL not in rows
    assert "gonedev" not in sideload.items(w.state) and not (w.state / "plugins" / "gonedev").exists()
    stored = json.loads(owner_state.state_path(w.state).read_text())["cplugs"]
    assert "gonedev" not in stored
    assert stored["gonecat"]["enabled"] is False and stored["gonecat"]["grants"] == ["notify"] and stored["gonecat"]["digest"]

    held = {r.name: r for r in identity.installs(w.state)}
    assert set(held) == {"gonecat", "gonedev"}
    tomb = identity.removal_of(w.state, "gonecat")
    assert tomb["version"] == "1.0.0" and tomb["publisher_key_id"] == "KEYOK" and tomb["at"].endswith("Z")
    report = build_report(w.host, w.rt)
    assert {r.name: (r.version, r.removed_at is not None) for r in report.removed} == {"gonecat": ("1.0.0", True), "gonedev": ("1.0.0", True)}
    assert not any(r.id in (CATALOG, LOCAL) for r in report.rows)

    notices = [(k, a) for k, a in w.alerts if k.endswith(".removed")]
    assert sorted(k for k, _ in notices) == ["cplug.gonecat.removed", "cplug.gonedev.removed"]
    by_key = dict(notices)
    assert by_key["cplug.gonedev.removed"]["detail_key"].endswith("detail_sideload") and str(w.data[LOCAL]) == by_key["cplug.gonedev.removed"]["params"]["folder"]
    assert by_key["cplug.gonecat.removed"]["detail_key"].endswith("detail_catalog") and by_key["cplug.gonecat.removed"]["sticky"] is True

    assert asyncio.run(prune_gone.prune_pass(w.rt)) == []
    assert len([k for k, _ in w.alerts if k.endswith(".removed")]) == 2


def test_an_unreadable_folder_prunes_nothing_and_reads_held_unreadable(served):
    w = served
    os.chmod(w.code, 0o000)
    try:
        assert asyncio.run(prune_gone.prune_pass(w.rt)) == []
        row = {r.id: r for r in build_report(w.host, w.rt).rows}[CATALOG]
        assert (row.word, row.reason) == (model.WORD_HELD, model.REASON_FOLDER_UNREADABLE)
        assert CATALOG in {r.item_id for r in w.rt.installed_rows()} and w.procs["gonecat"].stops == []
        assert [k for k, _ in w.alerts if k.endswith(".removed")] == []
    finally:
        os.chmod(w.code, 0o755)


needs_kqueue = pytest.mark.skipif(not folder_watch.KQUEUE_AVAILABLE, reason="folder events are kqueue on macOS")


async def until(check, seconds: float = 5.0) -> bool:
    end = asyncio.get_running_loop().time() + seconds
    while not check() and asyncio.get_running_loop().time() < end:
        await asyncio.sleep(0.02)
    return check()


@needs_kqueue
def test_a_folder_event_prunes_with_no_polling_and_stop_closes_the_descriptors(served, tmp_path, monkeypatch):
    w = served
    calls = []
    real = prune_gone.folder_states
    monkeypatch.setattr(prune_gone, "folder_states", lambda live: calls.append(1) or real(live))
    assert not hasattr(folder_watch, "WATCH_INTERVAL_S") and not hasattr(prune_gone, "WATCH_INTERVAL_S")

    async def scenario() -> list:
        watch = folder_watch.FolderWatch(w.rt, settle=0.05)
        watch.start()
        fds = list(watch._fds.values())
        assert {w.code.parent, w.source.parent} <= set(watch.watched)
        await asyncio.sleep(0.4)
        assert calls == []
        shutil.move(str(w.code), str(tmp_path / "Trash-cat"))
        assert await until(lambda: CATALOG not in {r.item_id for r in w.rt.installed_rows()})
        assert LOCAL in {r.item_id for r in w.rt.installed_rows()}
        await watch.stop()
        return fds

    fds = asyncio.run(scenario())
    assert fds and calls
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@needs_kqueue
def test_an_event_during_an_update_swap_prunes_nothing(served, tmp_path):
    w = served
    moved = tmp_path / "swap"

    async def scenario() -> None:
        watch = folder_watch.FolderWatch(w.rt, settle=0.4)
        watch.start()
        shutil.move(str(w.code), str(moved))
        await asyncio.sleep(0.1)
        shutil.move(str(moved), str(w.code))
        await asyncio.sleep(0.8)
        await watch.stop()

    asyncio.run(scenario())
    assert CATALOG in {r.item_id for r in w.rt.installed_rows()}


@needs_kqueue
def test_a_second_folder_deleted_during_the_settle_pause_is_pruned_too(served, tmp_path):
    w = served

    async def scenario() -> None:
        watch = folder_watch.FolderWatch(w.rt, settle=0.4)
        watch.start()
        shutil.move(str(w.code), str(tmp_path / "Trash-cat"))
        await asyncio.sleep(0.15)
        shutil.move(str(w.source), str(tmp_path / "Trash-dev"))
        assert await until(lambda: not {CATALOG, LOCAL} & {r.item_id for r in w.rt.installed_rows()})
        await watch.stop()

    asyncio.run(scenario())
    assert not {CATALOG, LOCAL} & {r.item_id for r in w.rt.installed_rows()}


@needs_kqueue
def test_the_watch_reads_the_install_ledger_off_the_loop_thread(served, tmp_path, monkeypatch):
    import threading

    w = served
    threads = []
    real = prune_gone.installed
    monkeypatch.setattr(prune_gone, "installed", lambda live: threads.append(threading.current_thread()) or real(live))

    async def scenario() -> None:
        watch = folder_watch.FolderWatch(w.rt, settle=0.05)
        watch.start()
        threads.clear()
        shutil.move(str(w.code), str(tmp_path / "Trash-cat"))
        assert await until(lambda: CATALOG not in {r.item_id for r in w.rt.installed_rows()})
        await until(lambda: bool(threads))
        await watch.stop()
        assert threads and all(t is not threading.main_thread() for t in threads)

    asyncio.run(scenario())


def test_an_unwatchable_folder_is_logged_once_and_covered_at_boot(served, monkeypatch):
    w = served
    seen = []
    monkeypatch.setattr(folder_watch.logger, "warning", lambda event, **kw: seen.append(event))
    monkeypatch.setattr(folder_watch.os, "open", lambda *a, **k: (_ for _ in ()).throw(PermissionError("nope")))

    async def scenario() -> None:
        watch = folder_watch.FolderWatch(w.rt)
        watch.start()
        watch.refresh()
        assert watch.watched == []
        await watch.stop()

    asyncio.run(scenario())
    assert seen.count("plugin_folder_not_watched") == 2


def test_a_database_error_on_one_install_skips_it_and_boot_goes_on(served, tmp_path, monkeypatch):
    w = served
    shutil.move(str(w.code), str(tmp_path / "Trash-cat"))
    shutil.move(str(w.source), str(tmp_path / "Trash-dev"))
    real = prune_gone._drop_stores

    def drop(state_dir, item_id):
        if item_id == CATALOG:
            raise sqlite3.OperationalError("database is locked")
        return real(state_dir, item_id)

    monkeypatch.setattr(prune_gone, "_drop_stores", drop)
    from src.cplugs.host import owner_switch

    owner_switch.write(w.state, True)
    w.rt.host = w.host

    async def no_fetch(*args, **kwargs):
        pass

    w.rt.index.sync = w.rt.index.ensure = no_fetch

    async def boot_and_stop() -> None:
        await w.rt.start()
        await w.rt.folder_watch.stop()

    asyncio.run(boot_and_stop())
    ids = {r.item_id for r in w.rt.installed_rows()}
    assert CATALOG in ids and LOCAL not in ids


def test_an_unreadable_install_ledger_prunes_nothing_and_does_not_raise(served, monkeypatch):
    def broken(live):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(prune_gone, "folder_states", broken)
    assert asyncio.run(prune_gone.prune_pass(served.rt)) == []


def test_a_placeholder_or_a_missing_parent_is_can_not_see_it(tmp_path):
    folder = tmp_path / "proj" / "plugin"
    assert folder_presence(folder) == UNREADABLE
    folder.parent.mkdir()
    assert folder_presence(folder) == GONE
    (folder.parent / ".plugin.icloud").write_text("")
    assert folder_presence(folder) == UNREADABLE
    (folder.parent / ".plugin.icloud").unlink()
    folder.write_text("a file where a folder belongs")
    assert folder_presence(folder) == UNREADABLE
    folder.unlink()
    folder.mkdir()
    assert folder_presence(folder) == PRESENT


def test_a_boot_prune_runs_before_anything_activates(served, tmp_path):
    w = served
    shutil.move(str(w.code), str(tmp_path / "Trash-cat"))
    from src.cplugs.host import owner_switch

    owner_switch.write(w.state, True)
    w.rt.supervisor._procs.pop("gonedev")
    w.rt.host = w.host

    async def no_fetch(*args, **kwargs):
        pass

    w.rt.index.sync = w.rt.index.ensure = no_fetch

    async def boot_and_stop() -> None:
        await w.rt.start()
        await w.rt.folder_watch.stop()

    asyncio.run(boot_and_stop())
    assert CATALOG not in {r.item_id for r in w.rt.installed_rows()} and sidecar_registry.find("gonecat") is None
    assert w.procs["gonecat"].stops == ["folder_gone"] and w.procs["gonedev"].stops == []


def test_reinstalling_the_same_catalog_id_gets_its_data_back_and_clears_the_tombstone(served, tmp_path):
    w = served
    uuid_before = identity.lookup(w.state, "gonecat").uuid
    shutil.move(str(w.code), str(tmp_path / "Trash-cat"))
    asyncio.run(prune_gone.prune_pass(w.rt))
    assert identity.removal_of(w.state, "gonecat") is not None
    again = identity.register_install(w.state, "gonecat", CATALOG, frozenset(d.id for d in runtime.definitions()), publisher_key_id="KEYOK")
    assert again.uuid == uuid_before and identity.removal_of(w.state, "gonecat") is None


def test_runtime_copies_are_moveable_so_the_trash_can_take_them(tmp_path):
    state = tmp_path / "support"
    state.mkdir()
    copy = sandbox.copy_runtime(state, "9.9.9")
    modes = {stat.S_IMODE(p.stat().st_mode) for p in [copy, *copy.rglob("*")] if p.is_dir()}
    files = {stat.S_IMODE(p.stat().st_mode) for p in copy.rglob("*") if p.is_file()}
    assert modes == {0o755} and files == {0o444}
    trash = tmp_path / "Trash"
    trash.mkdir()
    shutil.move(str(copy), str(trash / "9.9.9"))
    assert (trash / "9.9.9" / "runner.py").is_file()
    assert sandbox.copy_runtime(state, "9.9.9").is_dir()
