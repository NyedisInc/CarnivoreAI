
from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from tests.layouts_helpers import add_sessions, client_for, grid, row

# ruff: noqa: E402
from src.api.auth import require_auth
from src.core.layouts import broadcast as layout_broadcast
from src.core.db import connect
from src.core.tmux_one_shot import PasteNotSettledError

API = "/api/v1/layouts"


class FakeBackend:

    def __init__(self, alive: bool = True, fail: Exception | None = None) -> None:
        self.alive = alive
        self.fail = fail
        self.sent: List[str] = []

    def is_alive(self) -> bool:
        return self.alive

    async def paste_and_submit(self, text: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append(text)


def _info(row_id: int, sid: str, status: str = "idle", gate: str = "ready") -> Any:
    return SimpleNamespace(session_row_id=row_id, session=SimpleNamespace(id=sid),
                           activity_status=status, startup_gate=gate)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    client, db_path, frames = client_for(tmp_path, monkeypatch)
    sessions = add_sessions(db_path, 4)
    live: Dict[str, Any] = {"infos": [], "backends": {}}

    async def list_session_infos():
        return list(live["infos"])

    app = client.app
    app.state.session_manager = SimpleNamespace(list_session_infos=list_session_infos)
    app.state.services = SimpleNamespace(
        registry=SimpleNamespace(get_backend=lambda sid: live["backends"].get(sid)))
    return client, db_path, frames, sessions, live


def _layout(client, *row_ids) -> Dict[str, Any]:
    res = client.post(API, json={"name": "pair", "shape": grid(*[row(r) for r in row_ids])})
    assert res.status_code == 200, res.text
    return res.json()["layout"]


def _toggle(client, uuid, session_uuid, enabled):
    return client.put(f"{API}/{uuid}/members/{session_uuid}/broadcast", json={"enabled": enabled})


def test_every_member_starts_on_and_the_toggle_persists_without_a_revision(env):
    client, _, frames, sessions, _ = env
    (a, ua), (b, ub) = sessions[:2]
    layout = _layout(client, a, b)
    assert [m["broadcast"] for m in layout["members"]] == [True, True]
    before = len(frames)
    res = _toggle(client, layout["layout_uuid"], ub, False)
    assert res.status_code == 200, res.text
    after = res.json()["layout"]
    assert [m["broadcast"] for m in after["members"]] == [True, False]
    assert after["revision"] == layout["revision"]
    assert len(frames) == before + 1 and frames[-1]["reason"] == "layouts"
    listed = client.get(API).json()["layouts"][0]
    assert [m["broadcast"] for m in listed["members"]] == [True, False]
    again = _toggle(client, layout["layout_uuid"], ub, False)
    assert [m["broadcast"] for m in again.json()["layout"]["members"]] == [True, False]
    back = _toggle(client, layout["layout_uuid"], ub, True).json()["layout"]
    assert [m["broadcast"] for m in back["members"]] == [True, True]


def test_toggle_refuses_a_non_member_and_an_unknown_layout(env):
    client, _, _, sessions, _ = env
    (a, _), (b, _), (_, uc) = sessions[:3]
    layout = _layout(client, a, b)
    res = _toggle(client, layout["layout_uuid"], uc, False)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "member_unresolved"
    res = _toggle(client, "no-such-layout", uc, False)
    assert res.status_code == 404 and res.json()["detail"]["code"] == "layout_not_found"
    assert client.put(f"{API}/{layout['layout_uuid']}/members/x/broadcast", json={}).status_code == 422


def test_an_off_toggle_goes_with_its_membership(env):
    client, db_path, _, sessions, _ = env
    (a, _), (b, _), (c, uc) = sessions[:3]
    layout = _layout(client, a, b, c)
    uuid = layout["layout_uuid"]
    assert _toggle(client, uuid, uc, False).status_code == 200
    shape = client.put(f"{API}/{uuid}/shape", json={"shape": grid(row(a), row(b)),
                                                    "expected_revision": layout["revision"]})
    assert shape.status_code == 200, shape.text
    with closing(connect(db_path, create=False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM layout_broadcast_off").fetchone()[0] == 0
    added = client.post(f"{API}/{uuid}/members", json={"session_uuid": uc}).json()["layout"]
    assert [m["broadcast"] for m in added["members"]] == [True, True, True]


def test_broadcast_reaches_only_live_toggled_on_members(env):
    client, _, frames, sessions, live = env
    (a, _), (b, ub), (c, _), (d, _) = sessions
    layout = _layout(client, a, b, c, d)
    uuid = layout["layout_uuid"]
    assert _toggle(client, uuid, ub, False).status_code == 200
    backends = {"sa": FakeBackend(), "sb": FakeBackend(), "sd": FakeBackend()}
    live["backends"] = backends
    live["infos"] = [_info(a, "sa"), _info(b, "sb"), _info(d, "sd", status="question")]
    before = len(frames)
    res = client.post(f"{API}/{uuid}/broadcast", json={"text": "git status\t-s"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [(r["session_row_id"], r["status"], r["code"]) for r in body["results"]] == [
        (a, "sent", None), (b, "skipped_off", None), (c, "skipped_not_live", None),
        (d, "failed", "pane_dialog_open"),
    ]
    assert (body["sent"], body["skipped"], body["failed"]) == (1, 2, 1)
    assert backends["sa"].sent == ["git status\t-s"]
    assert backends["sb"].sent == [] and backends["sd"].sent == []
    assert len(frames) == before, "a broadcast changes no stored data and must publish nothing"


def test_a_dead_or_unsettled_pane_is_reported_not_raised(env):
    client, _, _, sessions, live = env
    (a, _), (b, _), (c, _), (d, _) = sessions
    uuid = _layout(client, a, b, c, d)["layout_uuid"]
    live["backends"] = {"sa": FakeBackend(alive=False), "sb": FakeBackend(fail=PasteNotSettledError("x")),
                        "sc": FakeBackend(), "sd": FakeBackend(fail=RuntimeError("tmux said no"))}
    live["infos"] = [_info(a, "sa"), _info(b, "sb"), _info(c, "sc", gate="awaiting_startup_prompt"),
                     _info(d, "sd")]
    body = client.post(f"{API}/{uuid}/broadcast", json={"text": "ls"}).json()
    assert [(r["status"], r["code"]) for r in body["results"]] == [
        ("skipped_not_live", None), ("failed", "paste_not_settled"),
        ("failed", "pane_dialog_open"), ("failed", "send_failed"),
    ]
    assert live["backends"]["sc"].sent == []


@pytest.mark.parametrize("text, code", [
    ("", "broadcast_text_empty"),
    ("   ", "broadcast_text_empty"),
    ("ls\nrm -rf x", "broadcast_text_control"),
    ("ls\r", "broadcast_text_control"),
    ("ls \x1b[A", "broadcast_text_control"),
    ("x" * (layout_broadcast.TEXT_MAX_BYTES + 1), "broadcast_text_too_large"),
])
def test_a_refused_text_sends_nothing_anywhere(env, text, code):
    client, _, _, sessions, live = env
    (a, _), (b, _) = sessions[:2]
    uuid = _layout(client, a, b)["layout_uuid"]
    live["backends"] = {"sa": FakeBackend(), "sb": FakeBackend()}
    live["infos"] = [_info(a, "sa"), _info(b, "sb")]
    res = client.post(f"{API}/{uuid}/broadcast", json={"text": text})
    assert res.status_code == 400 and res.json()["detail"]["code"] == code
    assert live["backends"]["sa"].sent == [] and live["backends"]["sb"].sent == []


def test_the_limit_itself_is_accepted_and_unknown_layout_is_404(env):
    client, _, _, sessions, live = env
    (a, _), (b, _) = sessions[:2]
    uuid = _layout(client, a, b)["layout_uuid"]
    live["backends"] = {"sa": FakeBackend()}
    live["infos"] = [_info(a, "sa")]
    at_limit = "y" * layout_broadcast.TEXT_MAX_BYTES
    assert client.post(f"{API}/{uuid}/broadcast", json={"text": at_limit}).status_code == 200
    assert live["backends"]["sa"].sent == [at_limit]
    res = client.post(f"{API}/nope/broadcast", json={"text": "ls"})
    assert res.status_code == 404 and res.json()["detail"]["code"] == "layout_not_found"


def test_both_routes_require_auth(env):
    client, _, _, sessions, _ = env
    (a, _), (b, ub) = sessions[:2]
    uuid = _layout(client, a, b)["layout_uuid"]
    app = client.app
    app.dependency_overrides.pop(require_auth)
    anonymous = TestClient(app)
    assert anonymous.post(f"{API}/{uuid}/broadcast", json={"text": "ls"}).status_code in (401, 403)
    assert anonymous.put(f"{API}/{uuid}/members/{ub}/broadcast",
                         json={"enabled": False}).status_code in (401, 403)


def test_the_text_is_never_logged(env, capsys):
    import structlog

    client, _, _, sessions, live = env
    (a, _), (b, _) = sessions[:2]
    uuid = _layout(client, a, b)["layout_uuid"]
    live["backends"] = {"sa": FakeBackend(), "sb": FakeBackend(fail=RuntimeError("boom"))}
    live["infos"] = [_info(a, "sa"), _info(b, "sb")]
    marker = "SECRETMARKER837"
    with structlog.testing.capture_logs() as logs:
        client.post(f"{API}/{uuid}/broadcast", json={"text": f"echo {marker}"})
        client.post(f"{API}/{uuid}/broadcast", json={"text": f"echo {marker}\n"})
    assert any(entry["event"] == "layout_broadcast" for entry in logs), logs
    assert marker not in repr(logs)
    assert marker not in capsys.readouterr().out
