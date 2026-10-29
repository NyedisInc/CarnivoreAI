
from __future__ import annotations

import math
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import attention_reader as reader_module
from src.core.attention.screen_reuse import ScreenReuse, screen_key
from src.core.attention.watcher import WatchTarget
from src.core.attention_reader import AttentionEvidenceReader
from src.core.session_instance_index import InstanceIndex
from src.core.session_status_map import StatusMap
from src.core.tmux_backend import TmuxBackend
from tests import socket_guard

PANE = ("sock", "cloude_a")


def _row(activity: int = 100, **over):
    row = {"pane_id": "%1", "pid": 7, "created_at_epoch": 1, "pane_dead": "0",
           "window_activity": activity, "pane_width": 80, "pane_height": 24,
           "pane_is_current": True}
    row.update(over)
    return row


def test_an_older_stamp_reuses_and_a_same_second_stamp_captures():
    screens = ScreenReuse()
    screens.keep(PANE, _row(), "screen", 101.5, 10.0)
    assert screens.reusable(PANE, _row(100), 103.0, 11.0) == "screen"
    assert screens.reusable(PANE, _row(101), 103.0, 11.0) is None
    assert screens.reusable(PANE, _row(102), 103.0, 11.0) is None


@pytest.mark.parametrize("change", [
    {"pane_width": 81}, {"pane_height": 25}, {"pid": 8}, {"pane_id": "%2"},
    {"created_at_epoch": 2}, {"pane_dead": "1"}, {"pane_is_current": False},
    {"pane_is_current": None}, {"window_activity": None},
])
def test_any_change_or_gap_in_the_key_captures(change):
    screens = ScreenReuse()
    screens.keep(PANE, _row(), "screen", 101.5, 10.0)
    assert screens.reusable(PANE, _row(100, **change), 103.0, 11.0) is None


def test_clock_backwards_and_the_backstop_capture():
    screens = ScreenReuse(max_reuse_seconds=30.0)
    screens.keep(PANE, _row(), "screen", 101.5, 10.0)
    assert screens.reusable(PANE, _row(100), 101.0, 11.0) is None
    assert screens.reusable(PANE, _row(100), 200.0, 40.0) is None
    assert screens.reusable(PANE, _row(100), 200.0, 39.9) == "screen"


def test_a_failed_capture_forgets_and_retain_only_prunes():
    screens = ScreenReuse()
    screens.keep(PANE, _row(), "screen", 101.5, 10.0)
    screens.keep(PANE, _row(), None, 102.5, 11.0)
    assert screens.reusable(PANE, _row(100), 103.0, 11.5) is None
    screens.keep(PANE, _row(), "screen", 101.5, 10.0)
    screens.retain_only([("sock", "other")])
    assert screens.reusable(PANE, _row(100), 103.0, 11.0) is None
    assert screen_key({}) is None


def test_the_reader_captures_once_while_the_stamp_holds(monkeypatch):
    rows = {"cloude_a": dict(_row(int(time.time()) - 5), status="running")}
    captures = []

    def capture(socket, name):
        captures.append(name)
        return "\n> \n"

    manager = SimpleNamespace(
        _build_tmux_status_map=lambda: StatusMap(dict(rows), complete=True, socket="cloude"),
        _identity_for_instance=lambda name, epoch: {"agent_type": "claude"},
        _instance_index_for_listing=lambda *, socket, names: InstanceIndex(),
        tmux_socket_name=lambda: "cloude",
        _wrappers_reader=lambda: [],
        _registry=SimpleNamespace(
            sessions={"s": SimpleNamespace(agent_type="claude", working_dir=None)},
            backends={"s": SimpleNamespace(socket_name="cloude")},
        ),
    )
    monkeypatch.setattr(reader_module, "read_registry_index", lambda: {})
    monkeypatch.setattr(reader_module, "read_instance_row", lambda *a, **k: {})
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *args: {})
    monkeypatch.setattr(AttentionEvidenceReader, "_process_snapshot",
                        lambda *args: reader_module.UNREADABLE)
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(capture))
    reader = AttentionEvidenceReader(manager, lambda sid: ("cloude_a", 1))
    first = reader(WatchTarget("s", "cloude_a@1"), datetime.now(timezone.utc))
    second = reader(WatchTarget("s", "cloude_a@1"), datetime.now(timezone.utc))
    assert captures == ["cloude_a"]
    assert first.pane == second.pane and first.pane is not None
    rows["cloude_a"]["window_activity"] = int(time.time()) + 1
    reader(WatchTarget("s", "cloude_a@1"), datetime.now(timezone.utc))
    assert captures == ["cloude_a", "cloude_a"]


@pytest.fixture
def tmux_socket():
    if shutil.which("tmux") is None:
        pytest.skip("tmux not on PATH")
    name = socket_guard.derive_test_socket("screenreuse")
    yield name
    os.system(f"{shutil.which('tmux')} -L {name} kill-server >/dev/null 2>&1")


def _wait(predicate, what: str, seconds: float = 5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    pytest.fail(f"timed out waiting for {what}")


def test_real_tmux_restamps_on_output_and_the_key_catches_a_resize(tmux_socket):
    probe = TmuxBackend.for_external(session_name="cloude_sr", on_output=None,
                                     working_dir=Path(tempfile.gettempdir()),
                                     socket_name=tmux_socket)
    rc, _, err = probe._run_tmux_sync("new-session", "-d", "-s", "cloude_sr",
                                      "-x", "80", "-y", "20", "cat", check=False)
    assert rc == 0, err
    capture = lambda: AttentionEvidenceReader._capture(tmux_socket, "cloude_sr")  # noqa: E731
    row = lambda: {r["name"]: r for r in probe.list_pane_status_all(fresh=True).sessions}["cloude_sr"]  # noqa: E731
    screens = ScreenReuse()

    def kept_after_quiet():
        stamp = row()["window_activity"]
        _wait(lambda: math.floor(time.time()) > stamp, "the activity second to pass")
        wall, mono = time.time(), time.monotonic()
        screens.keep(probe.socket_name, row(), capture(), wall, mono)

    probe._run_tmux_sync("send-keys", "-t", "=cloude_sr:", "first", check=False)
    _wait(lambda: "first" in (capture() or ""), "the first echo")
    kept_after_quiet()
    assert screen_key(row()) is not None
    reused = screens.reusable(probe.socket_name, row(), time.time(), time.monotonic())
    assert reused is not None and reused == capture()

    probe._run_tmux_sync("send-keys", "-t", "=cloude_sr:", "second", check=False)
    _wait(lambda: "second" in (capture() or ""), "the second echo")
    assert screens.reusable(probe.socket_name, row(), time.time(), time.monotonic()) is None

    kept_after_quiet()
    probe._run_tmux_sync("resize-window", "-t", "=cloude_sr:", "-x", "60", "-y", "20",
                         check=False)
    _wait(lambda: row()["pane_width"] == 60, "the resize")
    assert screens.reusable(probe.socket_name, row(), time.time(), time.monotonic()) is None
