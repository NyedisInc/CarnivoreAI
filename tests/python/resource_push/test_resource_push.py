
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core import resource_push
from src.core.resource_push import topics
from src.core.resource_push.client_build import ClientBuildWatch

WINDOW = 0.05


@pytest.fixture()
def bus():
    loop = asyncio.new_event_loop()
    frames: List[Dict[str, Any]] = []

    def publish(frame: Dict[str, Any]) -> int:
        frames.append(frame)
        return 1

    resource_push.install(publish, loop=loop, window_seconds=WINDOW)

    def settle() -> None:
        loop.run_until_complete(asyncio.sleep(WINDOW * 3))

    yield loop, frames, settle
    resource_push.uninstall()
    loop.close()


def test_a_burst_is_one_frame_naming_each_topic_once(bus):
    _, frames, settle = bus
    for topic in (topics.LAYOUTS, topics.TOASTS, topics.LAYOUTS, topics.LAYOUTS):
        resource_push.notify(topic)
    settle()
    assert frames == [{"type": "resources.changed", "topics": ["layouts", "toasts"], "seq": 1}]
    resource_push.notify(topics.LAYOUTS)
    settle()
    assert frames[-1] == {"type": "resources.changed", "topics": ["layouts"], "seq": 2}


def test_nothing_is_published_at_idle_and_unknown_topics_are_dropped(bus):
    _, frames, settle = bus
    settle()
    resource_push.notify("not-a-topic")
    settle()
    assert frames == []


def test_a_notify_from_a_worker_thread_lands_on_the_loop(bus):
    _, frames, settle = bus
    worker = threading.Thread(target=resource_push.notify, args=(topics.BROWSERS,))
    worker.start()
    worker.join()
    settle()
    assert [f["topics"] for f in frames] == [["browsers"]]


def test_without_an_install_notify_is_a_quiet_no_op():
    resource_push.uninstall()
    resource_push.notify(topics.LAYOUTS)


def test_a_session_set_notice_moves_its_derived_topics(bus):
    _, frames, settle = bus
    resource_push.on_hub_publish("session.status")
    settle()
    assert frames == []
    resource_push.on_hub_publish("sessions.changed")
    resource_push.on_hub_publish("session.renamed")
    settle()
    assert [f["topics"] for f in frames] == [["auto_sleep", "projects", "restore_offer"]]


def test_the_toast_inbox_names_toasts_on_a_raise_and_a_real_ack_only(bus):
    from src.core.sessions.toast_inbox import ToastInbox

    _, frames, settle = bus
    inbox = ToastInbox()
    toast, _ = inbox.store("ses_1", kind="stop", title="done", body=None, color=None,
                           session_label="x", session_name="cloude_x")
    settle()
    assert [f["topics"] for f in frames] == [["toasts"]]
    assert inbox.ack("ses_1", toast.id, reason="dismissed") is True
    settle()
    assert inbox.ack("ses_1", toast.id, reason="dismissed") is False
    settle()
    assert [f["topics"] for f in frames] == [["toasts"], ["toasts"]]


def test_the_switch_store_names_account_switch_only_when_it_wrote(bus, tmp_path: Path):
    from src.core.account_switch import store

    _, frames, settle = bus
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}))
    store.set_auto(config, enabled=True)
    settle()
    store.set_auto(config, enabled=True)
    settle()
    assert [f["topics"] for f in frames] == [["account_switch"]]


def test_the_layout_routes_name_layouts_once_per_write(bus, tmp_path, monkeypatch):
    from tests.layouts_helpers import add_sessions, client_for, grid, row

    _, frames, settle = bus
    client, db_path, _ = client_for(tmp_path, monkeypatch)
    (a, _), (b, _) = add_sessions(db_path, 2)
    created = client.post("/api/v1/layouts", json={"name": "pair", "shape": grid(row(a), row(b))})
    assert created.status_code == 200, created.text
    settle()
    assert [f["topics"] for f in frames] == [["layouts"]]
    uuid = created.json()["layout"]["layout_uuid"]
    assert client.patch(f"/api/v1/layouts/{uuid}", json={"name": "duo"}).status_code == 200
    client.get("/api/v1/layouts")
    settle()
    assert [f["topics"] for f in frames] == [["layouts"], ["layouts"]]


def test_the_client_build_watch_announces_a_moved_key_only():
    loop = asyncio.new_event_loop()
    frames: List[Dict[str, Any]] = []
    resource_push.install(lambda f: frames.append(f) or 1, loop=loop, window_seconds=WINDOW)
    try:
        keys = iter(["aaa", "aaa", "", "bbb"])
        watch = ClientBuildWatch(lambda: next(keys))
        assert [watch.check() for _ in range(4)] == [False, False, False, True]
        loop.run_until_complete(asyncio.sleep(WINDOW * 3))
        assert [f["topics"] for f in frames] == [["client_build"]]
    finally:
        resource_push.uninstall()
        loop.close()


def test_the_ledger_names_itself_only_when_what_it_shows_moved(bus):
    from tests.test_provider_ledger_poller import (
        FakeClock, build_poller, claude_account, live_claude_credential)

    loop, frames, settle = bus
    clock = FakeClock()
    poller = build_poller([claude_account()], clock=clock, claude_credential=None)
    for _ in range(4):
        loop.run_until_complete(poller.run_pass())
        clock.advance(600)
        settle()
    ledger_frames = [f for f in frames if "provider_ledger" in f["topics"]]
    assert len(ledger_frames) == 1, frames
    assert ledger_frames[0]["topics"] == ["account_switch", "provider_ledger"]

    poller._read_claude_credential = lambda config_dir: live_claude_credential()
    loop.run_until_complete(poller.run_pass())
    settle()
    assert len([f for f in frames if "provider_ledger" in f["topics"]]) == 2
