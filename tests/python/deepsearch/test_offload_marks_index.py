
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace

from src.core.backup_health import offloaded_marker
from src.core.deepsearch import constants as K
from src.core.deepsearch import fallback_hook as fb
from src.core.deepsearch import grouped
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.pipeline_plugin import DEEPSEARCH
from src.core.pipeline import plugin_db
from src.core.pipeline.engine import Engine
from src.core.pipeline.registry import plugins as pipeline_plugins
from src.plugins.save import offload_start
from src.plugins.save.offload import constants as OC
from src.plugins.save.offload import run as offload_run
from tests.python.deepsearch.helpers import cq, drain, go_ready, scan
from tests.python.deepsearch.test_deepsearch_vault_read import CONV, _capture, _delete_conversation, _indexed, _register, rig  # noqa: F401

WORD = "wombatmain"


def _engine(world) -> Engine:
    kinds = frozenset({"conversation", "subagent"})
    now = [0.0]
    engine = Engine(world["state"], db_path=world["db"], clock=lambda: now[0], plugins=pipeline_plugins([replace(DEEPSEARCH, file_kinds=kinds)]),
                    refresh_fn=lambda: SimpleNamespace(changed=()))
    engine.now = now  # type: ignore[attr-defined]
    fb.on_conversation_gone(engine.files_gone)
    return engine


def _run(engine: Engine) -> None:
    engine.now[0] += 10.0
    for _ in range(2000):
        delay = engine.step()
        if delay is None or delay > 0:
            engine.signal_caught_up()
            return
    raise AssertionError("the worker never ran out of due work")


def _search(world):
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], WORD, overrides={})


def test_an_offload_marks_the_index_rows_and_the_search_has_readable_hits(rig):  # noqa: F811
    _indexed(rig)
    _capture(rig)
    _register(rig)
    gone = _delete_conversation(rig)
    engine = _engine(rig.world)
    try:
        _run(engine)
        assert {m for (m,) in cq(rig.world, f"SELECT base_point_id FROM {K.LIVE_TABLE}")} == {None}
        stale = _search(rig.world)
        assert stale["stale"] == [CONV] and stale["groups"][0]["hits"] == []

        offload_run.tell_index([CONV])
        _run(engine)
    finally:
        fb.remove_gone_listener(engine.files_gone)
    rows = cq(rig.world, f"SELECT path, base_point_id FROM {K.LIVE_TABLE} ORDER BY path")
    assert sorted(p for p, _ in rows) == sorted(gone) and {m for _, m in rows} == {"vault"}
    go_ready(rig.world)
    offloaded_marker.write(rig.world["state"], [(CONV, ["sess-uuid-1"], 100)], {CONV: 1793972688.0})
    answer = _search(rig.world)
    (group,) = answer["groups"]
    assert answer["stale"] == []
    assert group["hits"] and all(h["from_backup"] is True for h in group["hits"]) and "\x02wombatmain\x03" in group["hits"][0]["snippet"]
    assert group["offloaded"] is True and group["offloaded_at"] == 1793972688.0


def test_a_conversation_that_is_not_offloaded_says_so(rig):  # noqa: F811
    _indexed(rig)
    (group,) = _search(rig.world)["groups"]
    assert group["offloaded"] is False and group["offloaded_at"] is None


def _marks(rig):
    return {m for (m,) in cq(rig.world, f"SELECT base_point_id FROM {K.LIVE_TABLE}")}


def test_a_notice_for_files_still_on_disk_leaves_their_rows_alone(rig):  # noqa: F811
    _indexed(rig)
    _capture(rig)
    _register(rig)
    engine = _engine(rig.world)
    try:
        offload_run.tell_index([CONV])
        _run(engine)
    finally:
        fb.remove_gone_listener(engine.files_gone)
    assert _marks(rig) == {None}
    (group,) = _search(rig.world)["groups"]
    assert group["hits"] and all(h["from_backup"] is False for h in group["hits"])


def test_a_restore_after_the_notice_brings_the_rows_back_to_disk(rig):  # noqa: F811
    _indexed(rig)
    _capture(rig)
    _register(rig)
    originals = {p: p.read_bytes() for p in (rig.world["main"], *rig.world["subagents"])}
    _delete_conversation(rig)
    engine = _engine(rig.world)
    try:
        offload_run.tell_index([CONV])
        _run(engine)
    finally:
        fb.remove_gone_listener(engine.files_gone)
    assert _marks(rig) == {"vault"}
    for path, data in originals.items():
        path.write_bytes(data)
    scan(rig.world)
    drain(rig.world)
    go_ready(rig.world)
    assert _marks(rig) == {None}
    (group,) = _search(rig.world)["groups"]
    assert group["hits"] and all(h["from_backup"] is False for h in group["hits"])


def _boom(*_args, **_kwargs):
    raise plugin_db.PluginUnavailable("deepsearch.db cannot be opened")


def test_an_unreadable_index_database_does_not_fail_the_offload_notice(rig, monkeypatch):  # noqa: F811
    _indexed(rig)
    engine = _engine(rig.world)
    monkeypatch.setattr(plugin_db, "pooled_db", _boom)
    try:
        offload_run.tell_index([CONV])
    finally:
        fb.remove_gone_listener(engine.files_gone)


def test_a_listener_that_throws_does_not_stop_the_notice_or_the_next_listener():
    heard = []

    def broken(_conversation_id):
        raise KeyError("a listener bug")

    fb.on_conversation_gone(broken)
    fb.on_conversation_gone(heard.append)
    try:
        assert fb.notify_conversation_gone("c-9") == 2
    finally:
        fb.remove_gone_listener(broken)
        fb.remove_gone_listener(heard.append)
    assert heard == ["c-9"]


class _Ledger:

    def __init__(self, states):
        self._rows = {cid: SimpleNamespace(conversation_id=cid, state=state) for cid, state in states.items()}

    def read(self):
        return self._rows


def test_the_start_up_resend_tells_the_index_of_every_offloaded_conversation_only():
    heard = []
    fb.on_conversation_gone(heard.append)
    try:
        offload_start.tell_index_of_offloaded(_Ledger({"c1": OC.STATE_OFFLOADED, "c2": OC.STATE_OFFLOADING, "c3": OC.STATE_OFFLOADED}))
    finally:
        fb.remove_gone_listener(heard.append)
    assert sorted(heard) == ["c1", "c3"]


def test_the_start_up_resend_runs_on_its_own_thread_and_survives_a_broken_ledger(monkeypatch):
    import threading

    seen = []
    monkeypatch.setattr(offload_start, "tell_index_of_offloaded", lambda ledger: seen.append(threading.current_thread().name))
    monkeypatch.setattr(offload_start, "Ledger", lambda *_a: _Ledger({}))
    monkeypatch.setattr(offload_start, "RUNTIME", SimpleNamespace(vault=lambda: SimpleNamespace(root="/v")))
    monkeypatch.setattr(offload_start.tf, "state_dir", lambda: "/s")
    offload_start.resend_in_background().join(5)
    assert seen == ["offload-index-resend"]
    monkeypatch.setattr(offload_start, "RUNTIME", SimpleNamespace(vault=lambda: (_ for _ in ()).throw(offload_start.VaultUnavailable("no vault"))))
    offload_start.resend_in_background().join(5)
