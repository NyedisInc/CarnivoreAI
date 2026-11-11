
from __future__ import annotations

import pytest

from src.core.notifications import types
from tests.python.agent_notify.test_agent_attachment import rig  # noqa: F401
from tests.python.agent_notify.test_agent_notify import _h, _names, env  # noqa: F401
from tests.python.mcp.test_mcp_endpoint import _rpc


@pytest.fixture(autouse=True)
def _no_fanout(env, monkeypatch):  # noqa: F811
    from src.core.notifications import agent_message

    async def none(toast, **kw):
        return None
    monkeypatch.setattr(agent_message, "_broadcast", none)


def _review(client, mgr, attachment, text="the mockup is ready"):
    args = {"text": text} if attachment is None else {"text": text, "attachment": attachment}
    return client.post("/mcp", json=_rpc("tools/call", {"name": "review_send", "arguments": args}), headers=_h(mgr)).json()["result"]


def test_review_records_the_review_type_with_a_link_and_a_file(rig):  # noqa: F811
    client, mgr, project, hints = rig
    res = _review(client, mgr, {"url": "https://example.com/pr/7", "title": "pr 7"})
    assert not res.get("isError"), res
    assert mgr.toasts[-1]["notify_type"] == "agent.review" and hints[-1]["url"] == "https://example.com/pr/7"
    (project / "report.txt").write_text("all green")
    assert not _review(client, mgr, {"path": str(project / "report.txt")}).get("isError")
    assert mgr.toasts[-1]["notify_type"] == "agent.review" and hints[-1]["media"]["name"] == "report.txt"
    assert "review_send" in _names(client, _h(mgr))


def test_route_type_field_picks_the_review_type_and_default_stays_message(rig):  # noqa: F811
    client, mgr, _, _ = rig
    body = {"text": "look", "attachment": {"url": "https://example.com/a"}}
    assert client.post("/api/v1/sessions/ses_a/agent-message", json=body, headers=_h(mgr)).status_code == 201
    assert mgr.toasts[-1]["notify_type"] == "agent.message"
    assert client.post("/api/v1/sessions/ses_a/agent-message", json={**body, "type": "agent.review"}, headers=_h(mgr)).status_code == 201
    assert mgr.toasts[-1]["notify_type"] == "agent.review"
    assert client.post("/api/v1/sessions/ses_a/agent-message", json={**body, "type": "session.died"}, headers=_h(mgr)).status_code in (400, 422)


@pytest.mark.parametrize("attachment", [
    None,
    {},
    {"url": "https://example.com/a", "path": "/tmp/x"},
    {"url": "http://example.com/a"},
    {"path": "/etc/hosts"},
])
def test_review_refuses_no_attachment_two_attachments_http_and_outside_the_project(rig, attachment):  # noqa: F811
    client, mgr, _, _ = rig
    before = len(mgr.toasts)
    assert _review(client, mgr, attachment)["isError"] is True
    assert len(mgr.toasts) == before


def test_review_type_is_seeded_for_phone_and_screen_but_not_sms():
    row = next(t for t in types.TYPES if t.id == "agent.review")
    assert row.defaults.screen and row.defaults.seed and row.family == types.FAMILY_MESSAGES
    assert "agent.review" in types.seed_for_kind("apns") and "agent.review" in types.seed_for_kind("webpush")
    assert "agent.review" not in types.seed_for_kind("sns") and "agent.review" not in types.seed_for_kind("twilio")
    assert "agent.message" not in types.seed_for_kind("apns")
