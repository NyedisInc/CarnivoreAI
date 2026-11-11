
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from src.config import settings as app_settings
from src.core.argent import classifier, notices, timeline, work_items
from src.core.argent.device_login import DeviceLogin
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.core.byoai.contracts import ChatResult, NotConfigured, Usage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "argent"
TOKEN = "FIXTURE-asicli-not-a-secret"
SERVER = "https://cp.argent.test"


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class World:

    def __init__(self) -> None:
        self.http: List[tuple] = []
        self.messages: List[str] = []
        self.notes: List[tuple] = []
        self.declared: List[tuple] = []
        self.reply: Dict[str, Any] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.http.append((request.method, request.url.path, body))
        if request.url.path == "/v1/my/work-items":
            return httpx.Response(200, json={"id": "wi_minted", "kind": "feature", "parent_id": body["parent_id"], "title": body["title"], "status": "open",
                                             "updated_at": "2026-11-05T13:00:00Z"})
        return httpx.Response(200, json={"ok": True})

    async def chat(self, feature: str, prompt: str, **options: Any) -> ChatResult:
        assert feature == classifier.FEATURE_ID
        self.messages.append(prompt)
        return ChatResult(text=json.dumps(self.reply), usage=Usage(input_tokens=120, output_tokens=30), raw={"model": "fixture-model"})

    def posts(self, path_part: str) -> List[Dict[str, Any]]:
        return [b for m, p, b in self.http if m == "POST" and path_part in p]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": False}}))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    app_settings.drop_auth_config_cache()
    w = World()
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    tokens.write("ten_1", TOKEN)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    page = json.loads((FIXTURES / "work_items_page.json").read_text())
    work_items.replace_all("ten_1", page["items"], 7)
    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(w.handler), None
    monkeypatch.setattr(timeline, "is_running", lambda: True)
    monkeypatch.setattr(timeline, "poke", lambda: None)
    monkeypatch.setattr(notices, "classifier_fix", lambda *a: w.notes.append(a))
    classifier._calls.clear()
    yield w
    set_runtime(None)
    work_items._pull.transport, work_items._pull.client = None, None
    classifier._calls.clear()


SIGNALS = classifier.Signals("fix/login", ("src/auth.py", "/Users/x/secret/abs.py", "../up.py"), "make login redo the token")


def run(w: World, signals: classifier.Signals = SIGNALS, **kw: Any) -> classifier.Outcome:
    return asyncio.run(classifier.classify("carnivore_api", signals, chat=kw.pop("chat", w.chat), **kw))


def current() -> List[Dict[str, str]]:
    return timeline.current("ten_1", "carnivore_api")


def test_existing_item_at_or_above_point_eight_is_declared_and_spend_reported(world: World) -> None:
    world.reply = {"scores": {"wi_story1": 0.91, "wi_feat1": 0.4}, "new_feature": None}
    out = run(world)
    assert (out.action, out.work_item_id) == ("switched", "wi_story1")
    assert [(d["work_item_id"], d["reason"]) for d in current()] == [("wi_story1", "classifier")]
    assert len(world.notes) == 1 and world.notes[0][2] == "Fixture Story"
    spend = world.posts("/usage")
    assert len(spend) == 1 and spend[0]["turns"][0]["tag"] == "carnivore-internal" and spend[0]["turns"][0]["work_item_id"] == "wi_proj1"
    assert spend[0]["turns"][0]["input_tokens"] == 120
    assert world.posts("/work-items") == []


def test_below_point_eight_is_sticky_and_a_leaky_threshold_would_fail(world: World) -> None:
    world.reply = {"scores": {"wi_story1": 0.79}, "new_feature": None}
    out = run(world)
    assert (out.action, out.reason) == ("none", "sticky") and current() == []
    world.reply = {"scores": {"wi_story1": 0.8}}
    assert run(world).action == "switched"


def test_mints_only_when_nothing_scores_point_five_and_model_is_sure(world: World) -> None:
    world.reply = {"scores": {"wi_story1": 0.55}, "new_feature": {"title": "token redo", "confidence": 0.95}}
    assert world.posts("/work-items") == [] and run(world).reason == "sticky" and world.posts("/work-items") == []
    world.reply = {"scores": {"wi_story1": 0.2}, "new_feature": {"title": "token redo", "confidence": 0.6}}
    assert run(world).reason == "sticky" and world.posts("/work-items") == []
    world.reply = {"scores": {"wi_story1": 0.2}, "new_feature": {"title": "token redo", "confidence": 0.9}}
    out = run(world)
    assert out.action == "minted_and_switched" and out.work_item_id == "wi_minted"
    assert world.posts("/work-items") == [{"kind": "feature", "parent_id": "wi_proj1", "title": "token redo"}]
    assert current()[0]["work_item_id"] == "wi_minted"


def test_a_name_differing_by_case_dash_or_dot_joins_instead_of_minting(world: World) -> None:
    world.reply = {"scores": {"wi_story1": 0.1}, "new_feature": {"title": "fixture-feature.", "confidence": 0.9}}
    out = run(world)
    assert out.work_item_id == "wi_feat1" and world.posts("/work-items") == []
    assert classifier.normalize("Fixture Feature") == classifier.normalize("fixture-feature.")
    assert classifier.normalize("fixture feature 2") != classifier.normalize("fixture feature")


def test_seventh_call_in_an_hour_never_reaches_the_model(world: World) -> None:
    world.reply = {"scores": {"wi_story1": 0.1}}
    for i in range(6):
        assert run(world, now=1000.0 + i).reason == "sticky"
    assert len(world.messages) == 6
    assert run(world, now=1100.0).reason == "rate_limited" and len(world.messages) == 6
    assert run(world, now=1000.0 + 3600.0).reason == "sticky" and len(world.messages) == 7


def test_a_secret_blocks_the_send_and_an_absolute_path_is_never_sent(world: World) -> None:
    world.reply = {"scores": {"wi_story1": 0.1}}
    leaky = classifier.Signals("main", ("src/a.py",), "use key sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3)
    out = run(world, leaky)
    assert out.reason == "blocked_secret" and world.messages == []
    run(world)
    sent = world.messages[0]
    assert "src/auth.py" in sent and "/Users/x" not in sent and "../up.py" not in sent

    def assert_clean(message: str) -> None:
        assert "sk-ant-api03-" not in message

    assert_clean(sent)
    with pytest.raises(AssertionError):
        assert_clean("key sk-ant-api03-xyz")


def test_off_no_connection_and_no_login_make_no_call(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timeline, "is_running", lambda: False)
    assert run(world).reason == "feature_off" and world.messages == [] and world.http == []
    monkeypatch.setattr(timeline, "is_running", lambda: True)

    async def no_connection(*a: Any, **k: Any) -> Any:
        raise NotConfigured("none")

    assert run(world, chat=no_connection).reason == "no_ai_connection"
    assert world.http == [] and not classifier._calls["carnivore_api"]
    set_runtime(Runtime(store=ArgentStore(Path(app_settings.state_dir_override)), tokens=TokenStore(Keychain()), login=None))
    assert run(world).reason == "login_required" and world.messages == []


def test_ask_every_time_suggests_and_changes_nothing(world: World) -> None:
    classifier.set_ask_every_time(True)
    world.reply = {"scores": {"wi_story1": 0.95}}
    out = run(world)
    assert out.action == "asked" and current() == [] and world.notes[0][4] is True
    classifier.set_ask_every_time(False)
    assert run(world).action == "switched" and current()[0]["work_item_id"] == "wi_story1"


def test_a_model_inventing_an_id_is_ignored(world: World) -> None:
    world.reply = {"scores": {"wi_not_real": 1.0}}
    assert run(world).reason == "ai_output_invalid" and current() == []
