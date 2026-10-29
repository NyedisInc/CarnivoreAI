
from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import swarm_routes
from src.api.auth import require_auth
from src.core import ui_preferences
from src.core.notifications import contracts, engine as engine_mod, routing_view, types as notify_types
from src.core.notifications.sources import open_checks, toast as toast_source
from src.core.swarm import alerts, reports, routing, stream, thread_port, views, watch
from src.cplugs.huddle import swarm_port
from src.core.work.storage import WorkStorage
from src.cplugs.sdk import chat_category
from src.cplugs.sdk.chat_category import CATEGORIES, card_ref, derive, is_shown
from tests.python.notifications.engine_fakes import LATE, NOON, QUIET_NIGHT, Clock, FakeSender, FakeView, FakeWriter
from tests.python.notifications.engine_fakes import dest as fake_dest
from tests.python.swarm.test_swarm_routing_chain import (  # noqa: F401
    PROJECT_TEXT, QUESTION, UNCOVERED, ask, env, escalate, run, teach,
)

THREAD = "agent:4"


@pytest.fixture()
def sink() -> Iterator[List[contracts.NotifyEvent]]:
    got: List[contracts.NotifyEvent] = []
    contracts.install_sink(got.append)
    yield got
    contracts.uninstall_sink()


@pytest.fixture()
def phone_engine() -> Iterator[Callable[..., SimpleNamespace]]:
    stack: List[Any] = []

    def build(*, ticked: bool = True, paused: bool = False, quiet: bool = False) -> SimpleNamespace:
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        sender = FakeSender()
        target = fake_dest(kind="webpush", quiet=QUIET_NIGHT if quiet else None)
        view = FakeView([target], {(target.id, "swarm.question_climbed"): ticked}, paused)

        async def secrets(dest_id: str) -> Dict[str, str]:
            return {}

        engine = engine_mod.NotifyEngine(sender_lookup=lambda kind: sender, is_muted=lambda sid: False, secrets_lookup=secrets,
                                         clock=Clock(LATE if quiet else NOON))
        on_loop = lambda coro: asyncio.run_coroutine_threadsafe(coro, loop).result(10)  # noqa: E731
        on_loop(engine.start())
        routing_view.install_routing(lambda: view, FakeWriter())
        engine_mod.install_engine(engine)
        stack.append((engine, loop, thread, on_loop))

        def sent() -> List[contracts.NotifyEvent]:
            on_loop(engine.join())
            return [call[0] for call in sender.calls]

        return SimpleNamespace(engine=engine, sent=sent)

    yield build
    for engine, loop, thread, on_loop in stack:
        on_loop(engine.stop())
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()
    routing_view.uninstall_routing()
    engine_mod.install_engine(None)


@pytest.fixture()
def huddle(tmp_path: Path) -> SimpleNamespace:
    ctx = SimpleNamespace(storage=WorkStorage(tmp_path / "huddle"), settings={}, swarm=None,
                          notify=lambda *a, **k: None)
    port = swarm_port.TaskManagerSwarmPort(ctx)
    return SimpleNamespace(ctx=ctx, port=port, store=port._store())


def go(coro: Any) -> Any:
    return asyncio.run(coro)



def test_sdk_literals_equal_core_and_the_mapping_is_pinned() -> None:
    assert chat_category.REPORT_PREFIX == reports.REPORT_PREFIX
    assert set(chat_category.IMPORTANT_PREFIXES) == {alerts.ALERT_PREFIX, *(p for p in alerts.IMMEDIATE_PREFIXES if p != alerts.IMMEDIATE_REF)}
    assert chat_category.DEFAULT_SHOWN == ("conversation", "result", "question", "important")
    assert len(set(CATEGORIES)) == len(CATEGORIES) == 20
    assert set(chat_category.EVENT_CATEGORY.values()) <= set(CATEGORIES)
    card = lambda kind, ref="": {"kind": "card", "card": kind, "item": {"swarm_ref": ref}}  # noqa: E731
    expected = [
        ({"kind": "owner"}, "conversation"), ({"kind": "agent"}, "conversation"), ({"kind": "traffic"}, "traffic"),
        ({"kind": "event", "event": "reported"}, "result"), ({"kind": "event", "event": "accepted"}, "result"),
        ({"kind": "event", "event": "asked"}, "question"), ({"kind": "event", "event": "escalated"}, "question"),
        ({"kind": "event", "event": "answered"}, "receipt"), ({"kind": "event", "event": "learned"}, "learned"),
        ({"kind": "event", "event": "spawned"}, "info"), ({"kind": "event", "event": "promoted"}, "info"),
        ({"kind": "event", "event": "never_heard_of_it"}, "info"),
        (card("question", "question:3"), "question"), (card("info", "report:9"), "result"), (card("done"), "result"),
        (card("info", "alert:flash:4:ab"), "important"), (card("info", "stuck:4:ab"), "important"),
        (card("info", "dead:4:2"), "important"), (card("info"), "card_created"), (card("review"), "question"), (card("review", "naming:2"), "question"),
        (card("info", "naming:2"), "info"),
        ({"kind": "owner", "category": "important"}, "important"),
    ]
    for entry, category in expected:
        assert derive(entry) == category, entry


def test_check_muted_and_the_default_filter() -> None:
    assert chat_category.check_muted(None) is None and chat_category.check_muted([]) == []
    assert chat_category.check_muted(["info", "traffic", "info"]) == ["info", "traffic"]
    for bad in (["conversation"], ["nonsense"], "info", [3], ["info", "conversation"]):
        with pytest.raises(ValueError):
            chat_category.check_muted(bad)  # type: ignore[arg-type]
    assert {c for c in CATEGORIES if is_shown(c, None)} == set(chat_category.DEFAULT_SHOWN)
    assert is_shown("info", []) and not is_shown("info", ["info"]) and is_shown("dealt", ["info"])
    assert is_shown("conversation", ["conversation"])
    with pytest.raises(ValueError, match="swarm_chat_muted"):
        ui_preferences.validate_changes({"swarm_chat_muted": ["conversation"]})
    assert ui_preferences.validate_changes({"swarm_chat_muted": ["info", "info"]})["swarm_chat_muted"] == ["info"]



def test_a_categorized_card_line_shows_and_an_uncategorized_swarm_line_stays_hidden(huddle: SimpleNamespace, sink: list) -> None:
    port = huddle.port
    go(port.post_owner_message(THREAD, "do it"))
    go(port.post_agent_message(THREAD, "on it", "sess-key"))
    go(port.post_traffic(THREAD, "Loki reported: all done", "reported:3"))
    go(port.post_traffic(THREAD, "dealt to Loki", card_ref("dealt", 41)))
    go(port.post_traffic(THREAD, "handed off to Odin", card_ref("handed_off", 41)))
    go(port.post_card(THREAD, "info", "report", "the report", "report:9"))
    go(port.post_card(THREAD, "info", "stuck", "it is stuck", "stuck:4:ab"))
    go(port.post_card(THREAD, "", "a plain task", "a plain task", ""))
    entries = go(port.read_thread(THREAD, 50))
    by_text = {(e.get("text") or e["item"]["text"]): e for e in entries}
    assert "Loki reported: all done" not in by_text
    assert [e["category"] for e in entries if e["kind"] == "event"] == ["dealt", "handed_off"]
    dealt = by_text["dealt to Loki"]
    assert (dealt["kind"], dealt["event"], dealt["ref"], dealt["id"].startswith("msg:")) == ("event", "card", "card:41", True)
    assert by_text["do it"]["category"] == by_text["on it"]["category"] == "conversation"
    cards = {e["item"]["swarm_ref"]: e["category"] for e in entries if e["kind"] == "card"}
    assert cards == {"report:9": "result", "stuck:4:ab": "important", "": "card_created"}
    with pytest.raises(ValueError):
        go(port.post_traffic(THREAD, "x", "card:nonsense:41"))
    assert sink == []


class FakeThread:

    def __init__(self, entries: List[Dict[str, Any]]) -> None:
        self.entries = entries

    async def read_thread(self, key: str, limit: int, cards=True) -> List[Dict[str, Any]]:
        return list(self.entries)

    async def ensure_thread(self, key: str, title: str) -> None: ...


def _line(i: int, category: str) -> Dict[str, Any]:
    return {"kind": "event", "id": f"msg:{i}", "at": float(i), "event": "card", "ref": "", "text": category, "category": category}


@pytest.fixture()
def route(monkeypatch: pytest.MonkeyPatch):
    thread = FakeThread([
        {"kind": "owner", "id": "msg:1", "at": 1.0, "text": "go", "category": "conversation"},
        _line(2, "dealt"), _line(3, "important"), _line(4, "info"), _line(5, "validated"),
        {"kind": "card", "id": "item:6", "at": 6.0, "card": "info", "item": {"id": 6, "swarm_ref": ""}, "category": "card_created"},
    ])
    thread_port.register(thread)
    monkeypatch.setattr(stream, "EXTRA_SOURCES", [])

    async def agent_row(agent_id: int) -> Dict[str, Any]:
        return {"id": agent_id, "thread_key": THREAD}

    monkeypatch.setattr(views, "get_agent_row", agent_row)
    app = FastAPI()
    app.include_router(swarm_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    state = SimpleNamespace(prefs={})
    app.state.ui_preferences_store = SimpleNamespace(read=lambda: {"values": state.prefs})
    yield TestClient(app), state
    thread_port.register(None)


def test_view_shown_drops_muted_categories_and_view_all_drops_nothing(route) -> None:
    client, state = route
    url = "/api/v1/swarm/agents/4/conversation"
    ids = lambda r: [e["id"] for e in r.json()["entries"]]  # noqa: E731
    everything = client.get(url)
    assert everything.status_code == 200 and ids(everything) == ["msg:1", "msg:2", "msg:3", "msg:4", "msg:5", "item:6"]
    assert all(e["category"] for e in everything.json()["entries"])
    assert ids(client.get(url + "?view=all")) == ids(everything)
    default = client.get(url + "?view=shown")
    assert ids(default) == ["msg:1", "msg:3"] and default.json()["cursor"] == "msg:3"
    state.prefs = {"swarm_chat_muted": ["info", "validated"]}
    assert ids(client.get(url + "?view=shown")) == ["msg:1", "msg:2", "msg:3", "item:6"]
    state.prefs = {"swarm_chat_muted": []}
    assert ids(client.get(url + "?view=shown")) == ids(everything)
    state.prefs = {"swarm_chat_muted": "garbage"}
    assert ids(client.get(url + "?view=shown")) == ["msg:1", "msg:3"]
    state.prefs = {"swarm_chat_muted": ["dealt"]}
    assert ids(client.get(url + "?view=shown&since=msg:2")) == ["msg:3", "msg:4", "msg:5", "item:6"]
    assert client.get(url + "?view=bogus").status_code == 422


def test_stream_page_derives_a_category_for_core_entries_that_have_none(monkeypatch: pytest.MonkeyPatch) -> None:
    async def source(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        return [{"kind": "event", "id": "ev:1", "at": 1.5, "event": "reported", "ref": "", "text": "x reported"},
                {"kind": "traffic", "id": "tr:1", "at": 2.5, "text": "hi"}]

    thread_port.register(FakeThread([{"kind": "owner", "id": "msg:1", "at": 1.0, "text": "go", "category": "conversation"}]))
    monkeypatch.setattr(stream, "EXTRA_SOURCES", [source])
    try:
        page = go(stream.page({"thread_key": THREAD}))
        assert [(e["id"], e["category"]) for e in page["entries"]] == [("msg:1", "conversation"), ("ev:1", "result"), ("tr:1", "traffic")]
        shown = go(stream.page({"thread_key": THREAD}, view="shown"))
        assert [e["id"] for e in shown["entries"]] == ["msg:1", "ev:1"]
    finally:
        thread_port.register(None)



def _record_marks(env) -> List[int]:
    marked: List[int] = []

    async def mark_phone_sent(item_id: int) -> None:
        marked.append(item_id)

    env.port.mark_phone_sent = mark_phone_sent
    return marked


def test_a_question_no_tier_answered_is_pushed_once_and_marked_sent(env, phone_engine: Callable[..., SimpleNamespace],
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    rig = phone_engine()
    pushed: List[str] = []
    climbed = routing.phone.question_climbed

    async def spy(app_state: Any, item_id: int, question_id: int, text: str) -> bool:
        pushed.append(text)
        return await climbed(app_state, item_id, question_id, text)

    monkeypatch.setattr(routing.phone, "question_climbed", spy)
    marked = _record_marks(env)
    teach(env, env.loki, "swapping models", PROJECT_TEXT)

    asked = ask(env, QUESTION)
    assert env.port.cards == [] and rig.sent() == [] and marked == []
    env.told.clear()

    open_q = ask(env, UNCOVERED)
    assert escalate(env, open_q["question_id"]) == "open" and env.port.cards == [("all", "question", f"question:{open_q['question_id']}")]
    assert [(e.type_id, e.instance_key, e.open_item, e.severity) for e in rig.sent()] == [
        ("swarm.question_climbed", f"question:{open_q['question_id']}", True, contracts.SEVERITY_WARN)]
    assert rig.sent()[0].title and rig.sent()[0].kind == "swarm"
    assert pushed == ["Fixer: Can you answer this for the asker? (task: fixer)"]
    assert marked == [1]
    assert asked["question_id"] != open_q["question_id"]
    run(routing.advance(None, open_q["question_id"]))
    run(routing.sweep(None))
    assert len(rig.sent()) == 1 and marked == [1]


@pytest.mark.parametrize("case", ["type_unticked", "quiet_hours", "routing_paused"])
def test_a_push_the_engine_drops_leaves_the_card_unmarked(env, phone_engine: Callable[..., SimpleNamespace], case: str) -> None:
    rig = phone_engine(ticked=case != "type_unticked", quiet=case == "quiet_hours", paused=case == "routing_paused")
    marked = _record_marks(env)
    open_q = ask(env, UNCOVERED)
    assert escalate(env, open_q["question_id"]) == "open" and len(env.port.cards) == 1
    assert rig.sent() == [] and marked == []
    run(routing.sweep(None))
    assert len(env.port.cards) == 1 and rig.sent() == [] and marked == []


def test_with_no_engine_installed_nothing_is_marked_sent(env) -> None:
    marked = _record_marks(env)
    assert engine_mod.current_engine() is None
    escalate(env, ask(env, UNCOVERED)["question_id"])
    assert env.port.cards and marked == []


def test_the_mark_writes_phone_sent_at_through_the_real_store(huddle: SimpleNamespace) -> None:
    item_id = go(huddle.port.post_card("all", "question", "a question for you", "which vendor?", "question:7"))
    store = huddle.store

    def row() -> sqlite3.Row:
        with closing(store._connect(False)) as conn:
            return conn.execute("SELECT phone_sent_at, revision, seq FROM work_items WHERE id = ?", (item_id,)).fetchone()

    before = row()
    assert before["phone_sent_at"] is None
    go(huddle.port.mark_phone_sent(item_id))
    after = row()
    assert after["phone_sent_at"] is not None and after["revision"] == before["revision"] + 1 and after["seq"] > before["seq"]
    go(huddle.port.mark_phone_sent(99999))


def test_the_climbed_question_type_is_a_sessions_type_seeded_on_push_only() -> None:
    row = notify_types.get_type("swarm.question_climbed")
    assert row.family == notify_types.FAMILY_SESSIONS and "swarm.question_climbed" not in notify_types.NEEDS_YOU
    assert row.defaults.seed and not row.defaults.screen and not row.defaults.passes_quiet_hours
    assert {k for k in notify_types._ALL_KINDS if "swarm.question_climbed" in notify_types.seed_for_kind(k)} == {"webpush", "apns"}



LOKI_EPOCH, PLAIN_EPOCH = 1760000001, 1760000002


def _manager() -> Any:
    return SimpleNamespace(
        _instance_epochs={"ses_9": LOKI_EPOCH, "ses_1": PLAIN_EPOCH},
        _registry=SimpleNamespace(sessions={"ses_9": SimpleNamespace(tmux_session="carnivore_Loki"),
                                            "ses_1": SimpleNamespace(tmux_session="carnivore_plain")}),
        _identity_for_live_name=lambda name: {"project_name": "api"}, _label_for_tmux_name=lambda name: name,
        _attention_watcher=None)


def _toast(session_id: str, notify_type: str, n: int) -> Any:
    return SimpleNamespace(id=f"t{n}", version=1, kind="Stop", title="t", body="b", session_id=session_id,
                           session_label="x", notify_type=notify_type)


def test_a_swarm_bodys_finished_toast_stays_in_app_and_its_dialogs_still_go_out(sink: list, monkeypatch: pytest.MonkeyPatch) -> None:
    remembered: List[str] = []
    monkeypatch.setattr(open_checks, "remember_dialog", lambda key, watcher, sid: remembered.append(key))
    watch.reset()
    watch.register(None, "carnivore_Loki", 3, LOKI_EPOCH)
    try:
        assert watch.agent_for_instance("carnivore_Loki", LOKI_EPOCH) == 3
        assert watch.agent_for_instance("carnivore_plain", PLAIN_EPOCH) is None and watch.agent_for_instance(None, None) is None
        manager = _manager()
        for n, type_id in enumerate(toast_source.POSTED_IN_APP_ONLY):
            toast_source.emit_event(manager, _toast("ses_9", type_id, n))
        assert sink == [] and remembered == []
        toast_source.emit_event(manager, _toast("ses_9", "session.permission", 7))
        toast_source.emit_event(manager, _toast("ses_9", "session.question", 8))
        toast_source.emit_event(manager, _toast("ses_9", "session.plan_approval", 9))
        assert [e.type_id for e in sink] == ["session.permission", "session.question", "session.plan_approval"]
        sink.clear()
        for n, type_id in enumerate(toast_source.POSTED_IN_APP_ONLY):
            toast_source.emit_event(manager, _toast("ses_1", type_id, 20 + n))
        assert [e.type_id for e in sink] == list(toast_source.POSTED_IN_APP_ONLY)
    finally:
        watch.reset()


def test_a_destroyed_bodys_tmux_name_reused_by_a_plain_session_still_pushes(sink: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_checks, "remember_dialog", lambda key, watcher, sid: None)
    watch.reset()
    watch.register(None, "carnivore_Loki", 3, LOKI_EPOCH)
    try:
        reused = SimpleNamespace(
            _instance_epochs={"ses_new": LOKI_EPOCH + 500},
            _registry=SimpleNamespace(sessions={"ses_new": SimpleNamespace(tmux_session="carnivore_Loki")}),
            _identity_for_live_name=lambda name: {"project_name": "api"}, _label_for_tmux_name=lambda name: name,
            _attention_watcher=None)
        toast_source.emit_event(reused, _toast("ses_new", "session.finished", 1))
        assert [e.type_id for e in sink] == ["session.finished"]
        assert watch.agent_for_instance("carnivore_Loki", LOKI_EPOCH + 500) is None
        sink.clear()
        toast_source.emit_event(_manager(), _toast("ses_9", "session.finished", 2))
        assert sink == []
        toast_source.emit_event(reused, _toast("ses_new", "session.permission", 3))
        toast_source.emit_event(_manager(), _toast("ses_9", "session.question", 4))
        assert [e.type_id for e in sink] == ["session.permission", "session.question"]
        sink.clear()
        watch.forget("carnivore_Loki")
        assert watch.agent_for_instance("carnivore_Loki", LOKI_EPOCH) is None and "carnivore_Loki" not in watch._epochs
        watch.register(None, "carnivore_Loki", 3)
        toast_source.emit_event(_manager(), _toast("ses_9", "session.finished", 5))
        assert [e.type_id for e in sink] == ["session.finished"]
    finally:
        watch.reset()


def test_a_manager_with_no_epoch_map_still_sends_a_plain_sessions_finished_push(sink: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_checks, "remember_dialog", lambda key, watcher, sid: None)
    watch.reset()
    try:
        manager = _manager()
        manager._instance_epochs = None
        toast_source.emit_event(manager, _toast("ses_1", "session.finished", 1))
        assert [e.type_id for e in sink] == ["session.finished"]
    finally:
        watch.reset()
