
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import session_dialog_routes
from src.api.peer_auth import require_peer_sessions
from src.core.approvals.answer import AnswerRefused
from src.core.mcp import beast_mode
from src.models.dialogs import AnswerChoice, DialogAnswerRequest, QuestionsAnswerRequest, QuestionsAnswerResponse
from tests.python.mcp.test_beast_full_control import FINGERPRINT, PANE, SEEN, _call, world  # noqa: F401

QF = "c" * 64
ARGS = {"target": "cloude_b", "questions_fingerprint": QF, "answers": [{"option": "Green"}]}


def _dialog(**kw) -> dict:
    return {"kind": "ask_user_question", "fingerprint": FINGERPRINT, "questions_fingerprint": QF, "startup_kind": None, **kw}


@pytest.fixture()
def batch(world, monkeypatch):  # noqa: F811
    calls, armed = world
    SEEN["ses_cloude_b"] = _dialog()

    async def answer_all(request, session_id, body):
        calls.append(("answer_all", session_id))
        return QuestionsAnswerResponse(count=1, via="review", questions_fingerprint=body.questions_fingerprint)
    monkeypatch.setattr(session_dialog_routes, "answer_session_questions", answer_all)
    return calls, armed


def test_the_route_is_authenticated_and_a_stale_ask_is_a_409_with_a_reason(monkeypatch):
    route = next(r for r in session_dialog_routes.router.routes if r.path.endswith("/dialog/answer-all"))
    assert any(d.dependency is require_peer_sessions for d in route.dependencies)

    async def info(request, session_id):
        return object(), SimpleNamespace(tmux_session=None, session=SimpleNamespace(id=session_id))

    async def stale(**kw):
        raise AnswerRefused("questions_changed")
    monkeypatch.setattr(session_dialog_routes, "_info", info)
    monkeypatch.setattr(session_dialog_routes, "deliver_answers", stale)
    body = QuestionsAnswerRequest(questions_fingerprint=QF, answers=[{"option": "Green"}])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(session_dialog_routes.answer_session_questions(request, "ses_1", body))
    assert exc.value.status_code == 409 and exc.value.detail == {"reason": "questions_changed"}

    async def ok(**kw):
        return "review"
    monkeypatch.setattr(session_dialog_routes, "deliver_answers", ok)
    done = asyncio.run(session_dialog_routes.answer_session_questions(request, "ses_1", body))
    assert (done.count, done.via) == (1, "review")


def test_a_fingerprint_must_be_64_hex_and_the_banner_source_reaches_the_audit_source(monkeypatch):
    with pytest.raises(ValueError):
        DialogAnswerRequest(fingerprint="z" * 64, choice=AnswerChoice(option="Yes"))
    with pytest.raises(ValueError):
        QuestionsAnswerRequest(questions_fingerprint="Z" * 64, answers=[{"option": "Green"}])
    with pytest.raises(ValueError):
        DialogAnswerRequest(fingerprint="a" * 64, choice=AnswerChoice(option="Yes"), source="beast")
    seen = []

    async def info(request, session_id):
        return object(), SimpleNamespace(tmux_session=None, session=SimpleNamespace(id=session_id))

    async def one(**kw):
        seen.append(kw["source"])
        return SimpleNamespace(kind="permission", fingerprint=kw["fingerprint"])

    async def many(**kw):
        seen.append(kw["source"])
        return "direct"
    monkeypatch.setattr(session_dialog_routes, "_info", info)
    monkeypatch.setattr(session_dialog_routes, "deliver_answer", one)
    monkeypatch.setattr(session_dialog_routes, "deliver_answers", many)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    for source in ("owner_banner", None):
        asyncio.run(session_dialog_routes.answer_session_dialog(
            request, "ses_1", DialogAnswerRequest(fingerprint="a" * 64, choice=AnswerChoice(option="Yes"), source=source)))
        asyncio.run(session_dialog_routes.answer_session_questions(
            request, "ses_1", QuestionsAnswerRequest(questions_fingerprint=QF, answers=[{"option": "Green"}], source=source)))
    assert seen == ["owner_banner", "owner_banner", "owner", "owner"]


def test_the_tool_always_waits_for_the_owner_beast_on_or_off(batch):
    calls, armed = batch
    assert "pending" in str(_call("session_dialog_questions_answer", ARGS)) and calls == []
    armed["on"] = True
    assert asyncio.run(beast_mode.approve_pending()) == 0 and calls == []
    assert "pending" in str(_call("session_dialog_questions_answer", ARGS)) and calls == []


def test_your_own_dialog_waits_even_with_beast_on(batch):
    calls, armed = batch
    armed["on"] = True
    held = _call("session_dialog_questions_answer", {**ARGS, "target": "cloude_a"})
    assert "pending" in str(held) and calls == []
    assert asyncio.run(beast_mode.approve_pending()) == 0


@pytest.mark.parametrize("seen", [_dialog(startup_kind="trust"), None, _dialog(questions_fingerprint="e" * 64),
                                  {"kind": "ask_user_question", "fingerprint": FINGERPRINT}],
                         ids=["startup_screen", "none_open", "another_ask", "no_questions_fingerprint"])
def test_a_startup_screen_or_an_ask_it_cannot_read_waits_for_the_owner_with_beast_on(batch, seen):
    calls, armed = batch
    armed["on"] = True
    SEEN["ses_cloude_b"] = seen
    held = _call("session_dialog_questions_answer", ARGS)
    assert "pending" in str(held) and calls == []
    assert asyncio.run(beast_mode.approve_pending()) == 0
