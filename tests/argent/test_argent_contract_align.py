
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx

from src.core.argent import health, outage, row_state
from src.core.argent.delegate import Delegates
from src.core.argent.mint import MintedKey, _epoch
from src.core.argent.pair_credential import CAP_CREDENTIAL, CredentialSender
from src.core.argent.store import ArgentStore

GW, SERVER = "https://gw.argent.test", "https://cp.argent.test"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "argent" / "health_ready_ok.json"


def probe(body: Dict[str, Any]) -> health.HealthReport:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    return asyncio.run(health.probe(GW, SERVER, transport=transport))


def test_the_settled_ready_body_is_up_and_accepts_mints() -> None:
    body = json.loads(FIXTURE.read_text())
    assert set(body) == {"body_cap_bytes", "upstream_chain"}
    report = probe(body)
    assert report.state == health.UP and report.mints_accepted is True
    assert health.switch_on_refusal(report, server_url=SERVER, gateway_url=GW, logged_in=True, login_expired=False) is None


def test_explicit_false_still_refuses_and_the_other_rules_stay() -> None:
    assert probe({"ok": False, "upstream_chain": True}).state == health.DOWN
    refused = probe({"mints_accepted": False, "upstream_chain": True})
    assert health.switch_on_refusal(refused, server_url=SERVER, gateway_url=GW, logged_in=True, login_expired=False) == "mints_refused"
    assert probe({"body_cap_bytes": 1048576, "upstream_chain": True}).state == health.CAP_TOO_LOW
    no_chain = probe({"upstream_chain": False})
    assert health.switch_on_refusal(no_chain, server_url=SERVER, gateway_url=GW, logged_in=True, login_expired=False) == "no_upstream_chain"


def test_a_key_expiry_comes_from_the_mint_answer_not_a_fixed_ttl(tmp_path: Path) -> None:
    assert _epoch("1970-01-01T00:01:00Z") == 60.0 and _epoch(None) == 0.0 and _epoch("junk") == 0.0
    now = 2_000_000.0
    row_state.record_launch("t", "short", working_dir="/w", tethered=True, reason="", key_id="k1", key_expires_at=now + 600, state_dir=tmp_path, clock=lambda: now)
    row_state.record_launch("t", "long", working_dir="/w", tethered=True, reason="", key_id="k2", key_expires_at=now + 7 * 86400, state_dir=tmp_path, clock=lambda: now)
    row_state.record_launch("t", "unknown", working_dir="/w", tethered=True, reason="", key_id="k3", state_dir=tmp_path, clock=lambda: now - 86400)
    for ref in ("short", "long", "unknown"):
        row_state.confirm("t", ref, state_dir=tmp_path, clock=lambda: now)
    assert outage.expiring_refs("t", now, state_dir=tmp_path) == {"short", "unknown"}
    assert MintedKey("x").expires_at == 0.0


class Tokens:
    def read(self, _tenant: str) -> str:
        return "FIXTURE-not-a-secret-token-0001"


def test_the_argent_token_goes_only_to_a_computer_the_main_owner_approved(tmp_path: Path) -> None:
    store = ArgentStore(tmp_path, clock=lambda: 1000.0)
    store.set_login("ten_1", "id_1", "Owner", 7200, source="own")
    posts: List[str] = []
    bodies: List[str] = []

    def peer(iid: str) -> Any:
        async def post(method: str, path: str, body: Any) -> Any:
            posts.append(iid)
            bodies.append(json.dumps(body))
            return 200, {}
        return post, [CAP_CREDENTIAL]

    minted: List[str] = []

    def argent(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        assert request.method == "POST" and request.url.path == "/v1/my/cli/delegate"
        minted.append(request.headers["authorization"])
        return httpx.Response(201, json={"id": "dlg-1", "access_token": "FIXTURE-delegate-token-0001", "expires_in": 3600})

    cfg = SimpleNamespace(server_url=SERVER, ca_path="")

    def sender(approved: Any) -> CredentialSender:
        delegates = Delegates(store, Tokens(), read_settings=lambda: cfg, transport=httpx.MockTransport(argent), clock=lambda: 1000.0)
        return CredentialSender(store=store, tokens=Tokens(), peer=peer, candidates=lambda: ["yes", "no"], allows=lambda iid: True,
                                read_settings=lambda: cfg, approved=approved, clock=lambda: 1000.0, delegates=delegates)

    assert asyncio.run(sender(lambda iid: iid == "yes").push()) == ["yes"] and posts == ["yes"]
    assert len(minted) == 1 and "FIXTURE-delegate-token-0001" in bodies[0] and "FIXTURE-not-a-secret-token-0001" not in bodies[0], "a delegate travels, never the owner token"
    posts.clear()
    assert asyncio.run(sender(None).push()) == [] and posts == []
