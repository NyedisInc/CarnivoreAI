
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi import HTTPException

from src.api.argent import cost as routes
from src.config import settings as app_settings
from src.core.argent import budget, cost_poller, notices, row_state, timeline, work_items
from src.core.argent.client import ArgentClient
from src.core.argent.cost_poller import LiveSession
from src.core.argent.device_login import DeviceLogin
from src.core.argent.fallback_spend import CursorStore
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.core.budget_hold.store import HoldStore
from src.core.session_token_usage.reader import SessionSubject
from src.cplugs.sdk import ports
from src.models.per_request_usage import RequestUsageRow

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "argent"
TOKEN = "FIXTURE-asicli-not-a-secret"
SERVER = "https://cp.argent.test"
SUBJECT = SessionSubject(agent_family="claude", conversation_uuid="u", working_dir="/w")


def fixture(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class Argent:

    def __init__(self) -> None:
        self.mode, self.standings, self.calls = "up", {}, []
        self.no_budget: Dict[str, bool] = {}
        self.cost = fixture("cost_by_session")

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path, dict(request.url.params), request.headers.get("authorization")))
        if self.mode == "down":
            raise httpx.ConnectError("down")
        if self.mode == "dark":
            return httpx.Response(404, json={})
        if request.url.path == "/v1/my/cost":
            return httpx.Response(200, json=self.cost)
        if request.url.path == "/v1/my/budgets/status" and request.url.params["work_item_id"] in self.no_budget:
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "no budget"}} if self.no_budget[request.url.params["work_item_id"]] else {})
        if request.url.path == "/v1/my/budgets/status":
            return httpx.Response(200, json=self.standings[request.url.params["work_item_id"]])
        if request.method == "POST":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})

    def client(self) -> ArgentClient:
        return ArgentClient(SERVER, lambda: TOKEN, transport=httpx.MockTransport(self.handler))


def standing(state: str, spent: int, cap: int = 10_000_000) -> Dict[str, Any]:
    base = fixture("budget_status_paused")
    return {**base, "state": state, "spent_micros": spent, "cap_micros": cap}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": True}}))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    app_settings.drop_auth_config_cache()
    seen: Dict[str, List[Any]] = {"warn": [], "hold": [], "lifted": []}
    monkeypatch.setattr(notices, "budget_warn", lambda *a: seen["warn"].append(a))
    monkeypatch.setattr(notices, "budget_hold", lambda *a: seen["hold"].append(a))
    monkeypatch.setattr(notices, "hold_lifted", lambda *a: seen["lifted"].append(a))
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    tokens.write("ten_1", TOKEN)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    work_items.replace_all("ten_1", fixture("work_items_page")["items"], 1)
    argent = Argent()
    holds = HoldStore(state / "argent.db")
    yield {"state": state, "seen": seen, "argent": argent, "holds": holds}
    set_runtime(None)
    ports.unregister(PORT_NAME)
    work_items._pull.transport, work_items._pull.client = None, None
    asyncio.run(cost_poller.stop())


def sessions(*names: str) -> List[LiveSession]:
    return [LiveSession(str(10 + i), name, False, SUBJECT) for i, name in enumerate(names)]


def declare(ref: str, agent: str, item: str, clock: Optional[Any] = None) -> None:
    timeline.record("ten_1", ref, agent, item, "picker", **({"clock": clock} if clock else {}))


def poll(env: Dict[str, Any], live: List[LiveSession], **kw: Any) -> float:
    kw.setdefault("read", lambda subject, since: [])
    return asyncio.run(cost_poller.poll_once(env["argent"].client(), "ten_1", live, holds=env["holds"], **kw))


def held_keys(env: Dict[str, Any], item: str) -> List[str]:
    return next((h["session_keys"] for h in env["holds"].snapshot() if h["item_id"] == item), [])


def test_warn_once_hold_at_the_cap_and_only_an_explicit_ok_clears_it(env: Dict[str, Any]) -> None:
    argent, seen = env["argent"], env["seen"]
    declare("carnivore_api", "", "wi_story1")
    argent.standings["wi_story1"] = standing("warn", 8_200_000)
    assert poll(env, sessions("carnivore_api")) == cost_poller.FAST_SECONDS, "within 20 percent of the cap polls fast"
    poll(env, sessions("carnivore_api"))
    assert len(seen["warn"]) == 1 and not seen["hold"] and not env["holds"].any_hold(), "80 percent: one notice per crossing, no hold"
    argent.standings["wi_story1"] = standing("paused", 10_000_000)
    poll(env, sessions("carnivore_api"))
    poll(env, sessions("carnivore_api"))
    assert len(seen["hold"]) == 1 and held_keys(env, "wi_story1") == ["10"], "100 percent: hold notice once, the session is held"
    assert seen["hold"][0][0] == "wi_story1" and seen["hold"][0][2] == "Fixture Owner", "the notice names the item and the budget owner as Argent returned it"
    for mode in ("dark", "down"):
        argent.mode = mode
        poll(env, sessions("carnivore_api"))
        assert held_keys(env, "wi_story1") == ["10"], f"{mode}: the last known hold stays"
    argent.mode = "up"
    argent.standings["wi_story1"] = {"state": "mystery", "spent_micros": 0}
    poll(env, sessions("carnivore_api"))
    assert held_keys(env, "wi_story1") == ["10"], "an unknown state keeps the hold"
    argent.standings["wi_story1"] = standing("ok", 1_000_000)
    poll(env, sessions("carnivore_api"))
    assert not env["holds"].any_hold() and len(seen["lifted"]) == 1, "an explicit ok clears it and says so"
    argent.standings["wi_story1"] = standing("warn", 8_500_000)
    poll(env, sessions("carnivore_api"))
    assert len(seen["warn"]) == 2, "a new crossing notifies again"


def test_a_restart_does_not_repeat_the_notice(env: Dict[str, Any]) -> None:
    declare("carnivore_api", "", "wi_story1")
    env["argent"].standings["wi_story1"] = standing("warn", 8_200_000)
    poll(env, sessions("carnivore_api"))
    cost_poller._state.snapshot = {"state": "pending", "as_of": None, "sessions": {}, "items": {}}
    poll(env, sessions("carnivore_api"))
    assert len(env["seen"]["warn"]) == 1


def test_a_naive_clear_on_unknown_would_fail_this_suite() -> None:
    unknown = budget.parse_standing({"state": "mystery"})
    assert budget.decide(unknown, 0).held is None
    naive = lambda st: st.state != "paused"  # noqa: E731
    assert naive(unknown) is True and budget.decide(unknown, 0).held is not True


def test_a_session_is_held_when_any_active_agent_is_paused_and_not_for_a_quiet_sub_agent(env: Dict[str, Any]) -> None:
    argent = env["argent"]
    argent.standings.update({"wi_proj1": standing("ok", 1_000_000), "wi_story1": standing("paused", 10_000_000)})
    declare("carnivore_a", "", "wi_proj1")
    declare("carnivore_a", "agent_7", "wi_story1")
    declare("carnivore_b", "", "wi_proj1")
    poll(env, sessions("carnivore_a", "carnivore_b"))
    assert held_keys(env, "wi_story1") == ["10"] and held_keys(env, "wi_proj1") == [], "mixed two-item session holds, the root-only session does not"
    env["holds"].clear_hold("wi_story1")
    poll(env, sessions("carnivore_a", "carnivore_b"), clock=lambda: time.time() + cost_poller.ACTIVE_SUBAGENT_SECONDS + 5)
    assert held_keys(env, "wi_story1") == [], "a sub-agent declared over an hour ago no longer counts"


def _rows(model: str, output_tokens: int) -> Any:
    row = RequestUsageRow(request_id="r1", agent_id="", model=model, input_tokens=0, output_tokens=output_tokens, cache_creation_tokens=0,
                          cache_read_tokens=0, timestamp="2026-11-05T12:00:00Z")
    return lambda subject, since: [row]


def test_local_unreported_spend_counts_for_an_untethered_session_only(env: Dict[str, Any]) -> None:
    argent = env["argent"]
    argent.standings["wi_story1"] = standing("ok", 8_000_000)
    declare("carnivore_api", "", "wi_story1")
    poll(env, sessions("carnivore_api"), read=_rows("fixture-model", 200_000))
    assert held_keys(env, "wi_story1") == ["10"], "untethered: its unreported local tokens are priced and added"
    env["holds"].clear_hold("wi_story1")
    row_state.record_launch("ten_1", "carnivore_api", working_dir="/w", tethered=True, reason="", key_id="k1")
    row_state.confirm("ten_1", "carnivore_api")
    poll(env, sessions("carnivore_api"), read=_rows("fixture-model", 200_000))
    assert held_keys(env, "wi_story1") == [], "a tethered session's tokens are Argent's own, never counted twice"
    row_state.clear("ten_1", "carnivore_api")
    poll(env, sessions("carnivore_api"), read=lambda subject, since: [])
    assert held_keys(env, "wi_story1") == [], "no local tokens: nothing added"


def test_an_unpriced_local_total_keeps_the_last_hold_and_sets_none(env: Dict[str, Any]) -> None:
    argent = env["argent"]
    argent.standings["wi_story1"] = standing("ok", 8_000_000)
    declare("carnivore_api", "", "wi_story1")
    env["holds"].set_hold("wi_story1", "Fixture Story One", ["10"], "ten_1")
    poll(env, sessions("carnivore_api"), read=_rows("a-model-with-no-price", 10))
    assert held_keys(env, "wi_story1") == ["10"], "unpriced: the last hold stays even though Argent says ok"
    env["holds"].clear_hold("wi_story1")
    poll(env, sessions("carnivore_api"), read=_rows("a-model-with-no-price", 10))
    assert held_keys(env, "wi_story1") == [], "unpriced: no new hold either"


def test_money_and_price_rounding() -> None:
    assert [budget.money(v) for v in (None, 0, 1, 20_000, 999_999, 1_234_500, 1_234_567_890)] == ["-", "$0.00", "$0.0001", "$0.02", "$1.00", "$1.23", "$1,234.57"]
    table = fixture("cost_by_session")["price_per_mtok"]
    assert budget.price_micros(table, "fixture-model", 1000, 0, 0, 0) == 3000 and budget.price_micros(table, "other", 1, 0, 0, 0) is None
    assert budget.price_micros(table, "fixture-model", 1, 0, 0, 0) == 3, "rounded up, never undercounted"


def test_the_snapshot_carries_cost_budget_and_never_the_token(env: Dict[str, Any]) -> None:
    env["argent"].standings["wi_story1"] = standing("warn", 8_200_000)
    declare("ses_fixture1", "", "wi_story1")
    poll(env, sessions("ses_fixture1"))
    snap = cost_poller.snapshot()
    assert snap["sessions"]["10"]["cost"]["cost_micros"] == 1_234_500 and snap["items"]["wi_story1"]["budget"]["effective_spent_micros"] == 8_200_000
    assert TOKEN not in json.dumps(snap) and all(call[3] == f"Bearer {TOKEN}" for call in env["argent"].calls)
    env["argent"].mode = "down"
    poll(env, sessions("ses_fixture1"))
    assert cost_poller.snapshot()["sessions"]["10"]["cost"]["cost_micros"] == 1_234_500, "a failed cost call keeps the last cost, never zero"
    assert cost_poller.snapshot()["items"]["wi_story1"]["budget"] is None, "an unmeasured budget is null, not zero"


def test_switch_off_polls_nothing_and_routes_refuse(env: Dict[str, Any], tmp_path: Path) -> None:
    argent = env["argent"]
    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(argent.handler), None
    Path(app_settings.auth_config_file).write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": False}}))
    app_settings.drop_auth_config_cache()
    declare("carnivore_api", "", "wi_story1")
    assert asyncio.run(cost_poller.pass_once()) == cost_poller.SLOW_SECONDS and argent.calls == [], "tether switch off: no call"
    assert not cost_poller.is_running(), "no task exists until the feature starts it"
    assert asyncio.run(routes.get_cost()) == {"enabled": False, "state": "off", "as_of": None, "sessions": {}, "items": {}}
    for call in (routes.request_budget(routes.BudgetRequest(item_id="wi_story1")),
                 routes.lift_budget(routes.BudgetLift(item_id="wi_story1"))):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(call)
        assert refused.value.status_code == 409 and refused.value.detail["code"] == "feature_off"
    assert argent.calls == []


def test_lift_never_calls_argent_and_returns_the_noc_url(env: Dict[str, Any]) -> None:
    argent = env["argent"]
    work_items._pull.transport, work_items._pull.client = httpx.MockTransport(argent.handler), None
    ports.register(PORT_NAME, {"on": True})
    env["holds"].set_hold("wi_story1", "Fixture Story One", ["10"], "ten_1")
    reply = asyncio.run(routes.lift_budget(routes.BudgetLift(item_id="wi_gov 1")))
    assert reply == {"lift_in_argent": True, "url": f"{SERVER}/work/items?sel=wi_gov%201"}
    assert argent.calls == [], "the route makes no request to Argent: no raise, no overage, nothing the shared client's 401 handler could act on"
    assert cost_poller.get_runtime().store.get_login() is not None and not cost_poller.get_runtime().store.login_expired(), "the login stays valid"
    assert held_keys(env, "wi_story1") == ["10"], "no local release: the hold ends on an ok poll"
    assert not any(r.path.endswith("/lift") for r in routes.router.routes if hasattr(r, "path") and r.methods and "DELETE" in r.methods), "no release route"
    assert budget.noc_budget_url("", "wi_1") is None and budget.noc_budget_url(SERVER + "/", "wi_1") == f"{SERVER}/work/items?sel=wi_1"


def test_non_owner_status_shape_is_read_and_a_paused_governing_item_holds(env: Dict[str, Any]) -> None:
    assert budget.viewer_is_owner("Fixture Owner", " fixture owner ") is True and budget.viewer_is_owner("Fixture Owner", "Fixture Person") is False
    assert budget.viewer_is_owner("", "Fixture Person") is None, "an unknown owner is never guessed to be the viewer"
    owned = budget.parse_standing(fixture("budget_status_owned"))
    assert (owned.state, owned.spent_micros, owned.cap_micros, owned.owner_name, owned.resets_at) == ("ok", 3_200_000, 5_000_000, "g-owner", None)
    assert (owned.governing_item_id, owned.governing_item_title) == ("wi_owned1", "Checkout revamp")
    other = budget.parse_standing(fixture("budget_status_governed"))
    assert (other.state, other.spent_micros, other.cap_micros, other.owner_name) == ("ok", None, None, "")
    assert (other.governing_item_id, other.governing_item_title) == ("wi_gov1", "Platform migration")
    env["argent"].standings["wi_story1"] = fixture("budget_status_governed_paused")
    declare("ses_fixture1", "", "wi_story1")
    poll(env, sessions("ses_fixture1"))
    assert held_keys(env, "wi_story1") == ["10"]
    shown = cost_poller.snapshot()["items"]["wi_story1"]["budget"]
    assert shown["governing_item_id"] == "wi_gov1" and shown["governing_item_title"] == "Platform migration" and shown["owner_name"] == "" and shown["viewer_is_owner"] is None
    assert env["seen"]["hold"][-1][2] == "Platform migration", "the notice names what governs the hold when no owner is named"
    actions, _ = notices.hold_actions("wi_story1", "Story", "Fixture Owner", "$10.00", "$10.00")
    assert [a["id"] for a in actions] == ["argent_request_budget", "argent_open_budget"] and all(a.get("route") != "/argent/budget/lift" for a in actions)


def test_status_not_found_clears_the_hold_quietly_and_a_bare_404_keeps_it(env: Dict[str, Any]) -> None:
    argent = env["argent"]
    argent.standings["wi_story1"] = standing("paused", 10_000_000)
    declare("ses_fixture1", "", "wi_story1")
    poll(env, sessions("ses_fixture1"))
    assert held_keys(env, "wi_story1") == ["10"]
    argent.no_budget["wi_story1"] = False
    poll(env, sessions("ses_fixture1"))
    assert held_keys(env, "wi_story1") == ["10"]
    argent.no_budget["wi_story1"] = True
    before = len(env["seen"]["hold"]), len(env["seen"]["warn"])
    poll(env, sessions("ses_fixture1"))
    assert held_keys(env, "wi_story1") == [] and env["seen"]["lifted"] == [], "cleared, and no hold-lifted notice"
    assert (len(env["seen"]["hold"]), len(env["seen"]["warn"])) == before, "no new notice"
    assert cost_poller.snapshot()["items"]["wi_story1"]["budget"] is None and cost_poller.snapshot()["items"]["wi_story1"]["held"] is False
