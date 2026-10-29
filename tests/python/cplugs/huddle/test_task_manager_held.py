
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import one_shot_routes
from src.cplugs.huddle import held, service
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401

SEND = "/api/v1/cplugs/huddle/send"
HELD = "/api/v1/cplugs/huddle/held"


class Pane:

    def __init__(self) -> None:
        self.dialog = True
        self.gone = False
        self.attempts = 0
        self.pasted: list = []

    async def __call__(self, request, session_id, text):
        self.attempts += 1
        if self.gone:
            raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "no such session"})
        if self.dialog:
            raise HTTPException(status_code=409, detail={"code": "pane_dialog_open", "message": "a dialog is open"})
        self.pasted.append((session_id, text))
        return SimpleNamespace(pasted_bytes=len(text), submitted=True)


@pytest.fixture
def pane(monkeypatch):
    fake = Pane()
    monkeypatch.setattr(one_shot_routes, "paste_through_gates", fake)
    monkeypatch.setattr(held, "POLL_S", 0.02)
    yield fake
    held.reset()


def wait_for(predicate, seconds: float = 3.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def waiting(client) -> int:
    return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == "12")["waiting_to_send"]


def entry(client):
    rows = client.get(HELD).json()["held"]
    return rows[0] if rows else None


def test_a_busy_session_holds_the_tell_and_it_goes_out_when_free_never_into_the_dialog(client, app, pane):
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert (result["status"], result["target"], result["code"]) == ("held", "ses_old", "pane_dialog_open")
    assert entry(client)["state"] == "held" and waiting(client) == 1
    wait_for(lambda: pane.attempts >= 4)
    assert pane.pasted == []
    assert waiting(client) == 1
    pane.dialog = False
    wait_for(lambda: entry(client) is None)
    assert [s for s, _t in pane.pasted] == ["ses_old"] and "(list 12, since 0)" in pane.pasted[0][1]
    assert waiting(client) == 0


def test_a_hold_that_times_out_raises_a_toast_and_the_items_stay_waiting(client, app, pane, monkeypatch):
    toasts = []
    monkeypatch.setattr(held, "minutes", lambda ctx: 0.001)
    from src.cplugs.host import capabilities
    monkeypatch.setattr(capabilities, "toaster", lambda cid, st: lambda sid, title: toasts.append((sid, title)) or None)
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    assert client.post(SEND, json={"lists": ["12"]}).json()["results"][0]["status"] == "held"
    wait_for(lambda: (entry(client) or {}).get("state") == "expired")
    assert toasts == [("ses_old", held.EXPIRED_TOAST_TITLE)]
    assert pane.pasted == [] and waiting(client) == 1
    attempts = pane.attempts
    time.sleep(0.1)
    assert pane.attempts == attempts
    assert client.delete(f"{HELD}/12").json() == {"cleared": True, "held": []}


def test_a_target_that_stops_while_held_sends_nothing_and_the_next_tell_asks(client, app, pane):
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    assert client.post(SEND, json={"lists": ["12"]}).json()["results"][0]["status"] == "held"
    pane.gone = True
    live = [r for r in asyncio.run(app.state.session_manager.list_session_infos()) if r.session.id != "ses_old"]

    async def infos():
        return live

    app.state.session_manager = SimpleNamespace(list_session_infos=infos)
    wait_for(lambda: (entry(client) or {}).get("state") == "gone")
    assert entry(client)["code"] == "session_not_found" and pane.pasted == []
    assert waiting(client) == 1
    nxt = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert nxt["status"] == "no_session" and "ses_old" not in [s["id"] for s in nxt["sessions"]]
    assert pane.pasted == []


def test_the_single_list_route_holds_too_and_a_send_clears_the_entry(client, app, pane):
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    body = client.post("/api/v1/cplugs/huddle/lists/12/send", json={}).json()
    assert body["status"] == "held"
    pane.dialog = False
    wait_for(lambda: entry(client) is None)
    assert len(pane.pasted) == 1


def test_a_hard_refusal_is_kept_as_not_sent_for_every_window(client, app, monkeypatch):
    async def refuse(request, session_id, text):
        raise HTTPException(status_code=409, detail={"code": "pane_not_an_agent", "message": "a shell"})

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", refuse)
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert result["status"] == "refused"
    assert entry(client)["state"] == "gone"
    held.reset()


def test_the_hold_bound_is_a_plugin_setting_with_a_default():
    from src.cplugs.host import runtime
    field = runtime.find("huddle").manifest.settings_schema["fields"][held.SETTING]
    assert field["default"] == held.DEFAULT_MINUTES == 30 and field["kind"] == "number"
    assert held.minutes(SimpleNamespace(settings={})) == 30
    assert held.minutes(SimpleNamespace(settings={held.SETTING: 5})) == 5
    assert held.BUSY_CODES == {
        "pane_dialog_open",
        "paste_not_settled",
        "agent_waking",
        "restore_offer_open",
    }
    assert service.SEND_FAMILIES


def test_a_fresh_no_session_tell_and_a_cancel_or_stop_leave_the_items_waiting_to_send(client, app, pane):
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    assert waiting(client) == 1
    first = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert first["status"] == "no_session" and pane.pasted == []
    assert waiting(client) == 1
    rows = client.get("/api/v1/cplugs/huddle/lists/12").json()["items"]
    assert [i["status"] for i in rows] == ["waiting_to_send"]
    assert client.get(HELD).json()["held"] == []


def test_a_dropped_hold_marks_nothing_told_so_the_items_keep_waiting_until_a_read_carries_them(client, app, pane):
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    assert client.post(SEND, json={"lists": ["12"]}).json()["results"][0]["status"] == "held"
    pane.gone = True
    wait_for(lambda: (entry(client) or {}).get("state") == "gone")
    lists = {r["key"]: r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"]}
    assert lists["12"]["waiting_to_send"] == 1 and lists["12"]["untold"] >= 1
    assert [i["status"] for i in client.get("/api/v1/cplugs/huddle/lists/12").json()["items"]] == ["waiting_to_send"]


def test_a_hold_retried_many_times_writes_one_start_and_one_end_line(monkeypatch):
    from structlog.testing import capture_logs

    monkeypatch.setattr(held, "POLL_S", 0.001)
    ctx = SimpleNamespace(settings={}, notify=lambda *_a, **_k: None, toast=lambda *_a: None)
    attempts: list = []

    async def deliver():
        attempts.append(time.time())
        if len(attempts) < 9:
            raise one_shot_routes._refuse("pane_dialog_open", "a dialog is open", "ses_1")
        return {}

    async def scenario():
        held.hold(ctx, "12", "ses_1", None, HTTPException(status_code=409, detail={"code": "pane_dialog_open"}), deliver)
        while held.snapshot():
            await asyncio.sleep(0.005)

    with capture_logs() as logs:
        asyncio.run(scenario())
    loud = [e["event"] for e in logs if e.get("log_level") != "debug"]
    assert loud.count("one_shot_refused") == 0 and loud.count("task_manager_send_held") == 1 and loud.count("task_manager_held_send_sent") == 1
    assert next(e for e in logs if e["event"] == "task_manager_held_send_sent")["attempts"] == 9
    gaps = [b - a for a, b in zip(attempts, attempts[1:])]
    assert gaps[-1] > gaps[0]


def stored(ctx) -> list:
    from src.cplugs.huddle import held_rows

    return held_rows.load(service.store(ctx))


def host_ctx(app):
    from src.cplugs.host import runtime

    return runtime.host_for(app).context("huddle", background=True)


def test_a_hold_survives_a_restart_and_goes_out_when_free(client, app, pane):
    from src.cplugs.huddle import held_resume

    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    assert client.post(SEND, json={"lists": ["12"]}).json()["results"][0]["status"] == "held"
    ctx = host_ctx(app)
    assert [r["list"] for r in stored(ctx)] == ["12"]
    since = entry(client)["since"]
    held.reset()
    assert held.snapshot() == [] and len(stored(ctx)) == 1
    pane.dialog = False

    async def restart():
        assert await held_resume.resume(ctx) == 1
        assert held.snapshot()[0]["since"] == since
        while held.snapshot():
            await asyncio.sleep(0.02)

    asyncio.run(restart())
    assert [s for s, _t in pane.pasted] == ["ses_old"] and stored(ctx) == [] and waiting(client) == 0


def test_a_hold_past_its_original_deadline_expires_at_boot_and_sends_nothing(client, app, pane):
    from src.cplugs.huddle import held_resume

    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"})
    note(app, "ses_old", "12", 100.0)
    assert client.post(SEND, json={"lists": ["12"]}).json()["results"][0]["status"] == "held"
    ctx = host_ctx(app)
    held.reset()
    pane.dialog = False
    from src.cplugs.huddle import held_rows

    row_ = stored(ctx)[0]
    held_rows.save(service.store(ctx), {**row_, "deadline": time.time() - 1})

    async def restart():
        return await held_resume.resume(ctx)

    assert asyncio.run(restart()) == 0
    assert entry(client)["state"] == "expired" and stored(ctx) == [] and pane.pasted == [] and waiting(client) == 1
