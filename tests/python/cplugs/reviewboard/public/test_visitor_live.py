
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any, Dict, Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.app_alerts import service as alert_service
from src.plugins.reviewboard import public_port
from src.plugins.reviewboard.public import announce
from src.plugins.sdk.visible_text import keep_visible
from src.plugins.host import runtime, state as owner_state
from src.plugins.sdk import ports
from tests.python.cplugs.reviewboard.public.read_harness import edge, get, mint_token
from tests.python.cplugs.reviewboard.boards import SIDECAR

SLUG = "20261013-bottom-bar"
BASE = "/api/v1/cplugs/reviewboard/public/visitors"
TOPIC = f"cplug.reviewboard.visitors:{SLUG}"
ALERT = f"cplug.reviewboard.visitors.{SLUG}"


class Alerts:

    def __init__(self) -> None:
        self.raised: List[Dict[str, Any]] = []
        self.resolved: List[str] = []

    def raise_alert(self, key: str, **kw: Any) -> Dict[str, Any]:
        self.raised.append({"key": key, **kw})
        return {"id": len(self.raised), "key": key}

    def resolve(self, key: str, **kw: Any) -> List[Dict[str, Any]]:
        self.resolved.append(key)
        return []


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> Alerts:
    spy = Alerts()
    monkeypatch.setattr(alert_service, "raise_alert", spy.raise_alert)
    monkeypatch.setattr(alert_service, "resolve", spy.resolve)
    return spy


class ReplyPort:

    async def post_visitors(self, item_id: int, text: str, ref: Dict[str, Any]) -> Dict[str, Any]:
        return {"posted": True, "message_id": 77}


@pytest.fixture
def task_port(monkeypatch: pytest.MonkeyPatch) -> Iterator[ReplyPort]:
    monkeypatch.setattr(public_port, "local_computer", lambda: SIDECAR["task"]["computer"])
    port, previous = ReplyPort(), ports.get("huddle.board")
    ports.register("huddle.board", port)
    yield port
    ports.register("huddle.board", previous) if previous is not None else ports.unregister("huddle.board")


@pytest.fixture
def owner(read_env: Any) -> Iterator[TestClient]:
    read_env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(read_env.app) as client:
        yield client
    read_env.app.dependency_overrides.clear()


def visit(token: str, body: Dict[str, Any], post_id: str = "") -> int:
    payload = json.dumps({"client_post_id": post_id or uuid.uuid4().hex, **body}).encode()
    return get(edge(), "/api/comments", token, method="POST", body=payload).status


def named(read_env: Any) -> int:
    return read_env.published.count(TOPIC)


def test_posts_name_the_board_topic_and_keep_one_alert_per_board(read_env, store, alerts) -> None:
    token, same = mint_token(store), uuid.uuid4().hex
    assert visit(token, {"text": "too close\nto the edge, " + "w" * 200}, same) == 201
    assert visit(token, {"text": "second"}) == 201
    assert named(read_env) == 2
    assert [a["key"] for a in alerts.raised] == [ALERT, ALERT]
    first, second = (a["params"] for a in alerts.raised)
    assert alerts.raised[0]["source"] == "cplug.reviewboard" and alerts.raised[0]["severity"] == "info"
    assert alerts.raised[0]["title_key"] == announce.ALERT_TITLE_KEY and alerts.raised[0]["detail_key"] == announce.ALERT_DETAIL_KEY
    assert (first["count"], second["count"]) == (1, 2) and first["board"] == SIDECAR["board"]["title"]
    assert first["preview"].startswith("too close to the edge, w") and len(first["preview"]) <= announce.PREVIEW_MAX and second["preview"] == "second"
    assert visit(token, {"text": "second again"}, same) == 200
    assert (named(read_env), len(alerts.raised)) == (2, 2)


def test_forward_and_deletes_name_the_topic_and_settle_the_alert(read_env, store, owner, task_port, alerts) -> None:
    token = mint_token(store)
    assert visit(token, {"text": "one"}) == 201 and visit(token, {"text": "two"}) == 201
    ids = [r["id"] for r in owner.get(BASE, params={"board": SLUG}).json()["responses"]]
    before = named(read_env)
    assert owner.post(f"{BASE}/forward", json={"board": SLUG, "ids": ids[:1]}).status_code == 200
    assert named(read_env) == before + 1 and alerts.raised[-1]["params"]["count"] == 1 and alerts.resolved == []
    assert [a.get("only_if_open", False) for a in alerts.raised] == [False, False, True]
    assert owner.delete(f"{BASE}/{ids[1]}").status_code == 200
    assert named(read_env) == before + 2 and alerts.resolved == [ALERT]
    assert owner.delete(BASE, params={"board": SLUG}).status_code == 200
    assert named(read_env) == before + 3


def test_the_alert_closes_without_the_notify_grant(read_env, store, owner, task_port, alerts) -> None:
    token = mint_token(store)
    assert visit(token, {"text": "one"}) == 201 and len(alerts.raised) == 1
    manifest = runtime.find("reviewboard").manifest
    owner_state.update(read_env.host.state_dir, manifest, None, lambda st: replace(st, grants=("agent_writes",)))
    ids = [r["id"] for r in owner.get(BASE, params={"board": SLUG}).json()["responses"]]
    assert owner.post(f"{BASE}/forward", json={"board": SLUG, "ids": ids}).status_code == 200
    assert alerts.resolved == [ALERT] and len(alerts.raised) == 1


def test_the_board_label_goes_through_the_text_rule() -> None:
    assert announce.label("bottom\u202e bar\u200b\x1b[31m\n  nav" + "x" * 200) == ("bottom bar nav" + "x" * 200)[:announce.TITLE_MAX]


def test_a_cut_preview_leaves_no_dangling_joiner() -> None:
    text = "x" * 55 + "\U0001F44D\u200d" + "\U0001F44D" * 10
    cut = announce.preview({"text": text})
    assert cut.endswith(announce.CUT) and "\u200d" not in cut and cut == keep_visible(cut)


@pytest.mark.parametrize(("body", "expected"), [
    ({"text": "a​b‮c  \n\n d"}, "abc d"),
    ({"answers": [{"prompt": "p", "options": ["b"]}, {"prompt": "q", "text": "nice", "note": "x"}]}, "nice"),
    ({"answers": [{"prompt": "p", "options": ["b"]}]}, ""),
    ({"payload": {"values": {"a": 3}, "notes": {"a": "left"}}}, "left"),
])
def test_the_preview_is_short_plain_cleaned_text(body: Dict[str, Any], expected: str) -> None:
    assert announce.preview(body) == expected


def test_the_preview_is_capped() -> None:
    cut: Tuple[str, int] = (announce.preview({"text": "x" * 500}), announce.PREVIEW_MAX)
    assert len(cut[0]) == cut[1] and cut[0].endswith("...")
