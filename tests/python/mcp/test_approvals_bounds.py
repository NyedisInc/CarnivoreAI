
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from structlog.testing import capture_logs

from src.api import approvals_routes
from src.api.peer_auth import require_peer_sessions
from src.core.approvals import peer_items
from src.core.approvals.ask_questions import AskOption, AskQuestion, AskQuestions
from src.core.approvals.inbox import ApprovalsInbox
from src.core.mcp import pending
from src.core.mcp.approvals import display
from src.core.mcp.pending import AgentActionProvider
from src.models.dialogs import ApprovalItem, QuestionsAnswerRequest
from tests.python.mcp.test_beast_full_control import _call, world  # noqa: F401
from tests.python.mcp.test_dialog_questions_answer import QF, batch  # noqa: F401


class _Extra:

    def __init__(self, items):
        self._items = items

    def signature(self):
        return frozenset(("dialog", i["id"], i["id"]) for i in self._items)

    async def items(self):
        return list(self._items)


def _client(monkeypatch, *providers) -> TestClient:
    inbox = ApprovalsInbox(publish=lambda frame: None)
    for provider in providers:
        inbox.register(provider)
    app = FastAPI()
    app.state.approvals_inbox = inbox
    app.include_router(approvals_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_peer_sessions] = lambda: SimpleNamespace(is_peer=False)

    async def no_peers(_open_db):
        return []
    monkeypatch.setattr(peer_items, "peer_items", no_peers)
    return TestClient(app)


def _within_limits(item: dict) -> None:
    for name, field in ApprovalItem.model_fields.items():
        limit = next((m.max_length for m in field.metadata if hasattr(m, "max_length")), None)
        if limit is not None and isinstance(item.get(name), (str, list)):
            assert len(item[name]) <= limit, name


def test_eight_long_typed_answers_park_and_the_list_still_answers_with_the_card(batch, monkeypatch):
    calls, _ = batch
    ok = ApprovalItem(id="ok", source="dialog", session_id="ses_1", kind="permission").model_dump()
    answers = [{"other": f"{i}" * 2000} for i in range(8)]
    parked = _call("session_dialog_questions_answer", {"target": "cloude_b", "questions_fingerprint": QF, "answers": answers})
    assert "pending" in str(parked) and calls == []
    reply = _client(monkeypatch, _Extra([ok]), AgentActionProvider(pending.get_store(), lambda: None)).get("/api/v1/approvals")
    assert reply.status_code == 200
    items = {i["id"]: i for i in reply.json()["items"]}
    card = next(i for i in items.values() if i["source"] == "agent_action")
    assert "ok" in items and card["summary"].endswith("...") and card["question"].endswith("...")
    _within_limits(card)


def test_fifty_long_labels_are_refused_at_the_route(batch):
    labels = ["L" * 5000] * 50
    refused = _call("session_dialog_questions_answer", {"target": "cloude_b", "questions_fingerprint": QF, "answers": [{"options": labels}]})
    assert refused.get("isError"), refused


def test_a_served_ask_with_huge_and_forged_labels_lists_bounded_and_one_line(monkeypatch):
    ask = AskQuestions("toolu_1", tuple(AskQuestion("Q" * 9000, "H", True, tuple(AskOption(f"{'L' * 5000}{n}\nFAKE\x1b") for n in range(80))) for _ in range(8)))
    served = {"id": "dlg:1", "source": "dialog", "session_id": "ses_1", "kind": "ask_user_question", "questions": ask.to_dicts()}
    reply = _client(monkeypatch, _Extra([served])).get("/api/v1/approvals")
    assert reply.status_code == 200 and len(reply.json()["items"]) == 1
    assert len(reply.text) < 250_000, len(reply.text)
    labels = [o["label"] for q in reply.json()["items"][0]["questions"] for o in q["options"]]
    assert all(len(l) <= 500 and "\n" not in l and "\x1b" not in l for l in labels)
    QuestionsAnswerRequest(questions_fingerprint=QF, answers=[{"option": labels[0]}])


def _park(text: str):
    async def run():
        return None
    return pending.get_store().create(caller_session_id="s", caller_tmux="c", target_session_id="t", target_tmux="t", action="session_send_message",
                                      args_summary="send text", execute=run, args={"text": text})


def test_an_agent_action_payload_over_the_old_body_limit_is_listed_whole_never_cut(batch, monkeypatch):
    tail = "rm -rf ~ HIDDEN_TAIL"
    _park("x" * 4500 + tail)
    reply = _client(monkeypatch, AgentActionProvider(pending.get_store(), lambda: None)).get("/api/v1/approvals")
    assert reply.status_code == 200
    card = next(i for i in reply.json()["items"] if i["source"] == "agent_action")
    assert tail in card["body"] and not card["body"].endswith("...")


def test_a_payload_over_the_shown_limit_is_refused_at_park_time(batch):
    with pytest.raises(pending.PendingLimitError, match="too long"):
        _park("x" * (pending.MAX_SHOWN_PAYLOAD_CHARS + 10))


@pytest.mark.parametrize("body", [{"option": "Blue\nFAKE ROW\x1b[31m"}, {"options": ["Cheese", "a b"]}, {"options": ["x" * 501]}])
def test_a_forged_or_overlong_label_is_refused_at_the_route(body):
    with pytest.raises(ValidationError):
        QuestionsAnswerRequest(questions_fingerprint=QF, answers=[body])


def test_the_card_never_draws_a_fake_row_from_a_label_and_the_details_stay_bounded():
    forged = {"answers": [{"option": "Blue\nFAKE ROW\x1b[31m", "other": "x\r\ny"}]}
    card = display.build("session_dialog_questions_answer", forged, "api", "s")
    rows = [r["value"] for r in card["detail"] if r["key"] == "answer"]
    assert len(rows) == 1 and not any(c in rows[0] for c in "\n\r\x1b")
    wide = {"answers": [{"options": ["w" * 500] * 50} for _ in range(8)]}
    size = sum(len(r["value"]) for r in display.build("session_dialog_questions_answer", wide, "api", "s")["detail"])
    assert size < 250_000


def test_an_item_that_is_invalid_for_another_reason_is_dropped_loudly_not_a_500(monkeypatch):
    ok = {"id": "ok", "source": "dialog", "session_id": "s", "kind": "k"}
    bad = {"id": "bad", "source": "dialog", "session_id": "s", "kind": "k", "options": 5}
    with capture_logs() as logs:
        reply = _client(monkeypatch, _Extra([ok, bad])).get("/api/v1/approvals")
    assert reply.status_code == 200 and [i["id"] for i in reply.json()["items"]] == ["ok"]
    dropped = [e for e in logs if e["event"] == "approvals_item_dropped"]
    assert len(dropped) == 1 and dropped[0]["item_id"] == "bad" and dropped[0]["fields"] == ["options"]


def test_an_item_with_an_overlong_body_is_dropped_never_cut(monkeypatch):
    ok = {"id": "ok", "source": "dialog", "session_id": "s", "kind": "k"}
    over = {"id": "over", "source": "dialog", "session_id": "s", "kind": "k", "body": "b" * (ApprovalItem.model_fields["body"].metadata[0].max_length + 1)}
    with capture_logs() as logs:
        reply = _client(monkeypatch, _Extra([ok, over])).get("/api/v1/approvals")
    assert [i["id"] for i in reply.json()["items"]] == ["ok"]
    assert [e["item_id"] for e in logs if e["event"] == "approvals_item_dropped"] == ["over"]


def test_a_stuck_invalid_item_logs_its_drop_once_not_on_every_list_build(monkeypatch):
    from src.core.approvals import bounds
    bounds._LOGGED_DROPS.clear()
    bad = {"id": "stuck", "source": "dialog", "session_id": "s", "kind": "k", "options": 5}
    client = _client(monkeypatch, _Extra([bad]))
    with capture_logs() as logs:
        for _ in range(3):
            assert client.get("/api/v1/approvals").json()["items"] == []
    assert len([e for e in logs if e["event"] == "approvals_item_dropped"]) == 1


def test_a_peer_item_with_a_huge_summary_is_bounded_and_one_with_a_huge_id_is_dropped_with_a_log(monkeypatch):
    from tests.python.approvals.test_peer_ask_items import PEER, RAW
    cut = peer_items.accept({**RAW, "summary": "s" * 5000}, PEER)
    assert cut is not None and len(cut.summary) == 1000 and cut.summary.endswith("...")
    with capture_logs() as logs:
        assert peer_items.accept({**RAW, "id": "i" * 500}, PEER) is None
    dropped = [e for e in logs if e["event"] == "peer_approval_item_dropped"]
    assert len(dropped) == 1 and dropped[0]["peer"] == "peer-a" and dropped[0]["fields"] == ["id"]


def test_the_merged_local_and_peer_list_goes_through_the_net(monkeypatch):
    ok = {"id": "ok", "source": "dialog", "session_id": "s", "kind": "k"}
    wide = {"id": "wide", "source": "dialog", "session_id": "s", "kind": "k"}
    client = _client(monkeypatch, _Extra([ok]))

    async def peers(_open_db):
        return [{**wide, "id": "r" * 500}]
    monkeypatch.setattr(peer_items, "peer_items", peers)
    reply = client.get("/api/v1/approvals")
    assert reply.status_code == 200 and [i["id"] for i in reply.json()["items"]] == ["ok"]


def test_a_startup_screen_body_is_cut_where_it_is_built():
    from tests.attention.test_startup_prompt_provider import FakeManager, FakeWatcher, NOW
    from src.core.approvals.startup_prompt_provider import STARTUP_BODY_MAX, StartupPromptProvider
    from src.core.attention.startup_screen import StartupScreen
    watcher = FakeWatcher()
    watcher.show("ses_1", StartupScreen("mcp_server", "x" * 9000, NOW, True))
    provider = StartupPromptProvider(lambda: watcher, FakeManager, on_first_seen=lambda _info: None)
    body = asyncio.run(provider.items())[0]["body"]
    assert len(body) == STARTUP_BODY_MAX and body.endswith("...")
    ApprovalItem.model_validate({**asyncio.run(provider.items())[0]})


def test_an_ask_with_more_questions_than_the_card_holds_is_served_as_a_mismatch_not_a_partial_batch():
    from src.core.approvals import ask_questions as aq
    assert aq.MAX_QUESTIONS == ApprovalItem.model_fields["questions"].metadata[0].max_length
    questions = tuple(AskQuestion(f"Pick {n}?", "H", False, (AskOption("A"),)) for n in range(aq.MAX_QUESTIONS + 1))
    dialog = SimpleNamespace(kind=aq.KIND_ASK, startup_kind=None, question="Pick 0?",
                             rows=[SimpleNamespace(role=aq.ROLE_OPTION, label="A")])
    assert aq.matching_question(dialog, AskQuestions("t", questions)) == 0
    served = aq.serve_fields(dialog, AskQuestions("t", questions), True)
    assert served["questions"] == [] and served["questions_state"] == aq.STATE_MISMATCH
    fits = aq.serve_fields(dialog, AskQuestions("t", questions[:aq.MAX_QUESTIONS]), True)
    assert fits["questions_state"] == aq.STATE_MATCHED and len(fits["questions"]) == aq.MAX_QUESTIONS


def test_bound_item_logs_every_list_it_cuts_with_the_counts():
    from src.core.approvals.bounds import bound_item
    with capture_logs() as logs:
        out = bound_item({"id": "cut-me", "options": ["o"] * 60, "rows": ["r"] * 10})
    assert len(out["options"]) == 50 and len(out["rows"]) == 10
    cut = [e for e in logs if e["event"] == "approvals_list_cut"]
    assert len(cut) == 1 and cut[0]["item_id"] == "cut-me" and cut[0]["field"] == "options"
    assert cut[0]["kept"] == 50 and cut[0]["dropped"] == 10
