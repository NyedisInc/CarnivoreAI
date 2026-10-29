
import httpx
import pytest

from tests.phone_link.pairing_helpers import pair_device
from fastapi import Depends, FastAPI, Request

from src.api import auth as auth_module
from src.api.agent_auth import require_agent
from src.api.host_guard import HostGuardMiddleware
from src.core.phone_link import gate as g
from src.core.phone_link.pairing import PairingStore

HOST = "abcdefghijklmnopqrstuvwxyz.link.carnivore.ai"


def build(tmp_path, client_ip):
    app = FastAPI()

    @app.get("/who")
    async def who(request: Request):
        return {"host": request.client.host, "via_link": bool(request.scope.get("via_link")),
                "limiter_key": auth_module._rate_limit_key(request)}

    @app.get("/agent")
    async def agent(caller=Depends(require_agent)):
        return {"ok": True}

    app.add_middleware(HostGuardMiddleware)
    pairing = PairingStore(path=tmp_path / "p.db")
    cookie = pair_device(pairing, "203.0.113.5")
    streams = g.StreamTable()
    streams.add(40001, g.LinkStream(stream_id=1, client_ip=client_ip, client_port=5555))
    gate = g.LinkGate(app, hostname=HOST, streams=streams, pairing=pairing, send_trust=lambda sid: None)
    transport = httpx.ASGITransport(app=gate, client=("127.0.0.1", 40001))
    return httpx.AsyncClient(transport=transport, base_url=f"https://{HOST}", headers={
        "cookie": f"{g.COOKIE_NAME}={cookie}"}), pairing


@pytest.mark.asyncio
async def test_a_link_request_never_appears_as_loopback_and_the_limiter_keys_on_the_real_ip(tmp_path):
    client, pairing = build(tmp_path, "203.0.113.77")
    async with client:
        body = (await client.get("/who")).json()
    assert body == {"host": "203.0.113.77", "via_link": True, "limiter_key": "203.0.113.77"}
    assert body["host"] not in ("127.0.0.1", "::1")
    pairing.close()


@pytest.mark.asyncio
async def test_require_agent_refuses_via_link_even_when_the_real_address_is_loopback(tmp_path):
    client, pairing = build(tmp_path, "127.0.0.1")
    async with client:
        resp = await client.get("/agent")
    assert resp.status_code == 403 and resp.json()["detail"] == "loopback only"
    pairing.close()


@pytest.mark.asyncio
async def test_the_host_guard_admits_only_the_exact_link_name_on_the_link(tmp_path):
    client, pairing = build(tmp_path, "203.0.113.77")
    async with client:
        assert (await client.get("/who")).status_code == 200
    plain = FastAPI()
    plain.add_middleware(HostGuardMiddleware)

    @plain.get("/who")
    async def who2():
        return {}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=plain), base_url=f"https://{HOST}") as c:
        assert (await c.get("/who")).status_code == 400
    pairing.close()
