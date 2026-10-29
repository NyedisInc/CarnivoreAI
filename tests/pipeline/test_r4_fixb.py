
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from scripts.time_machine_retire import retire
from src.core.pipeline import lifecycle
from src.cplugs.sdk import save_triggers
from tests.python.time_machine_retire.test_retire import build


def _lifecycle(written: list) -> lifecycle.Lifecycle:
    def writer(db_path, kind, conversation_id, session_uuid, **kw):
        written.append((kind, conversation_id))
        return "written"
    return lifecycle.Lifecycle(Path("unused.db"), writer=writer)


def test_a_blocked_save_listener_does_not_stop_the_next_milestone():
    release, entered, written, heard = threading.Event(), threading.Event(), [], []

    def listener(save):
        heard.append(save.conversation_id)
        entered.set()
        release.wait(30)

    stop = save_triggers.subscribe(listener)
    try:
        lc = _lifecycle(written)
        first = lc.write_milestone("kill", "c1", time.time())
        assert first.result(timeout=10) == "written"
        assert entered.wait(10), "population: the first announce must actually be inside the listener"
        second = lc.write_milestone("sleep", "c2", time.time())
        assert second.result(timeout=10) == "written"
        assert written == [("kill", "c1"), ("sleep", "c2")]
        assert heard == ["c1"]
    finally:
        release.set()
        stop()


def test_a_full_announce_queue_drops_the_oldest_and_never_blocks(monkeypatch):
    release, entered, heard = threading.Event(), threading.Event(), []

    def listener(save):
        heard.append(save.conversation_id)
        entered.set()
        release.wait(30)

    monkeypatch.setattr(lifecycle, "MAX_ANNOUNCE_QUEUED", 2)
    stop = save_triggers.subscribe(listener)
    try:
        lc = _lifecycle([])
        lc.write_milestone("kill", "c0", time.time()).result(timeout=10)
        assert entered.wait(10)
        for n in range(1, 6):
            assert lc.write_milestone("kill", f"c{n}", time.time()).result(timeout=10) == "written"
        assert lc._announcer.pending() == 2
        release.set()
        end = time.monotonic() + 10
        while len(heard) < 3 and time.monotonic() < end:
            time.sleep(0.01)
        assert heard == ["c0", "c4", "c5"]
    finally:
        release.set()
        stop()


def _tm_files(state: Path) -> int:
    return sum(1 for p in (state / "time-machine").rglob("*") if p.is_file())


def _stored_save(state: Path, enabled: bool) -> None:
    path = state / "cplugs" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "cplugs": {"save": {"enabled": enabled, "grants": [], "revision": 1}}}))


def test_retire_keeps_the_save_plugins_folder_and_scope_while_it_is_on(tmp_path, capsys):
    state = build(tmp_path)
    _stored_save(state, True)
    assert _tm_files(state) == 1
    assert retire.run(state, state / "config.json", apply=True) == retire.EXIT_OK
    assert _tm_files(state) == 1
    cfg = json.loads((state / "config.json").read_text())
    assert cfg["save_pipeline"] == {"capture_scope": "x"}
    assert cfg["byoai"]["features"] == {"keep.me": {}}
    assert "save plugin is ON" in capsys.readouterr().out


def test_retire_removes_them_with_the_plugin_off_and_fails_closed_on_a_broken_state_file(tmp_path):
    off = build(tmp_path / "off")
    _stored_save(off, False)
    assert retire.run(off, off / "config.json", apply=True) == retire.EXIT_OK
    assert not (off / "time-machine").exists() and "save_pipeline" not in json.loads((off / "config.json").read_text())
    broken = build(tmp_path / "broken")
    (broken / "cplugs").mkdir()
    (broken / "cplugs" / "state.json").write_text("{not json")
    assert retire.run(broken, broken / "config.json", apply=True) == retire.EXIT_OK
    assert _tm_files(broken) == 1 and "capture_scope" in (broken / "config.json").read_text()
