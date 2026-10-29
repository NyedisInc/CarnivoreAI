
import json
from typing import Dict, List, Optional, Tuple

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import ai_invoke_routes, ai_routes
from src.api.auth import require_auth
from src.core import session_change_notice
from src.core.byoai import gateway as gateway_module
from src.core.byoai import transport
from src.core.byoai.calllog import CallLog
from src.core.byoai.gateway import Gateway
from src.core.byoai.keys import KeyStore
from src.core.byoai.store import ByoaiStore

SECRET = "q" * 20 + "WXYZ"


class FakeKeychain:

    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}
        self.locked = False

    def state(self, service: str, account: str) -> str:
        if self.locked:
            return "unavailable"
        return "ok" if (service, account) in self.items else "absent"

    def read(self, service: str, account: str) -> Optional[str]:
        return self.items.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


def _sse(*frames: str) -> bytes:
    return "".join(frames).encode()


def provider(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content) if request.content else {}
    host, path = request.url.host, request.url.path
    if host == "down.test":
        raise httpx.ConnectError("refused", request=request)
    if host == "anth.test":
        assert request.headers["x-api-key"] == SECRET and request.headers["anthropic-version"]
    else:
        assert request.headers["authorization"] == f"Bearer {SECRET}"
    if body.get("model") == "bad":
        return httpx.Response(401, text=f"invalid key {SECRET}")
    stream = bool(body.get("stream"))
    if path == "/v1/chat/completions":
        if stream:
            return httpx.Response(200, content=_sse(
                'data: {"choices":[{"delta":{"content":"po"}}]}\n\n',
                'data: {"choices":[{"delta":{"content":"ng"}}]}\n\n',
                'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n', "data: [DONE]\n\n"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
    if path == "/v1/responses":
        if stream:
            return httpx.Response(200, content=_sse(
                'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"po"}\n\n',
                'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"ng"}\n\n',
                'event: response.completed\ndata: {"type":"response.completed","response":'
                '{"usage":{"input_tokens":3,"output_tokens":2}}}\n\n'))
        return httpx.Response(200, json={"status": "completed", "usage": {"input_tokens": 3, "output_tokens": 2},
                                         "output": [{"type": "reasoning"}, {"type": "message", "content": [
                                             {"type": "output_text", "text": "pong"}]}]})
    if path == "/v1/messages":
        if stream:
            return httpx.Response(200, content=_sse(
                'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":3}}}\n\n',
                'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
                '"delta":{"type":"text_delta","text":"po"}}\n\n',
                'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
                '"delta":{"type":"text_delta","text":"ng"}}\n\n',
                'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":2}}\n\n'))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "pong"}], "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 3, "output_tokens": 2}})
    return httpx.Response(404, text="no such route")


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    keychain = FakeKeychain()
    keys = KeyStore(backend=keychain)
    gateway_module.set_gateway(Gateway(ByoaiStore(config, keys=keys), CallLog(tmp_path), keys))
    real = httpx.AsyncClient
    monkeypatch.setattr(transport.httpx, "AsyncClient",
                        lambda **kw: real(**{**kw, "transport": httpx.MockTransport(provider)}))
    frames: List[dict] = []
    monkeypatch.setattr(session_change_notice, "publish", lambda _state, frame: frames.append(frame) or 0)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: True
    app.include_router(ai_routes.router, prefix="/api/v1")
    app.include_router(ai_invoke_routes.router, prefix="/api/v1")
    yield TestClient(app), config, tmp_path, frames
    gateway_module.set_gateway(None)


WIRES = [
    ("openai_chat", "https://openai.test/v1", "bearer"),
    ("openai_responses", "https://resp.test/v1", "bearer"),
    ("anthropic_messages", "https://anth.test", "x-api-key"),
]


@pytest.mark.parametrize("protocol,base,auth", WIRES)
def test_wire_round_trip_never_leaks_the_key(env, protocol, base, auth):
    client, config, tmp_path, frames = env
    made = client.post("/api/v1/ai/connections", json={
        "preset": "custom", "base_url": base, "key": SECRET,
        "options": {"protocol": protocol, "auth": auth, "capabilities": ["chat"]}})
    assert made.status_code == 201
    view = made.json()["connection"]
    assert view["has_key"] is True and view["key_hint"] == "WXYZ" and view["key_host"]
    cid = view["id"]
    seen = [made.text]

    tested = client.post(f"/api/v1/ai/connections/{cid}/test", json={"capability": "chat", "model": "m-1"})
    seen.append(tested.text)
    assert tested.json()["ok"] is True and "pong" in tested.json()["detail"]

    chat = client.post("/api/v1/ai/chat", json={"connection": cid, "model": "m-1", "prompt": "ping"})
    seen.append(chat.text)
    assert chat.status_code == 200 and chat.json()["text"] == "pong"
    assert chat.json()["usage"]["input_tokens"] == 3 and chat.json()["usage"]["output_tokens"] == 2

    streamed = client.post("/api/v1/ai/chat", json={"connection": cid, "model": "m-1", "prompt": "ping", "stream": True})
    seen.append(streamed.text)
    assert streamed.headers["content-type"].startswith("text/event-stream")
    deltas = [json.loads(line[6:]) for line in streamed.text.splitlines() if line.startswith("data: ")]
    assert "".join(d["text"] for d in deltas) == "pong" and deltas[-1]["done"] is True
    assert deltas[-1]["usage"]["output_tokens"] == 2

    refused = client.post("/api/v1/ai/chat", json={"connection": cid, "model": "bad", "prompt": "ping"})
    seen.append(refused.text)
    assert refused.status_code == 502 and refused.json()["detail"]["provider_status"] == 401
    assert "***" in refused.json()["detail"]["detail"]

    calls = client.get("/api/v1/ai/calls").json()["calls"]
    seen.append(json.dumps(calls))
    assert [c["ok"] for c in calls] == [0, 1, 1, 1] and calls[0]["error"].startswith("401")
    seen.append(client.get("/api/v1/ai/connections").text)
    seen.append(config.read_text())
    seen.append((tmp_path / "byoai.db").read_bytes().decode("latin-1"))
    assert not [s for s in seen if SECRET in s]
    assert frames and all(set(f) == {"type", "revision"} for f in frames)


def test_stale_revision_is_409_and_a_host_change_drops_the_key(env):
    client, config, _tmp, _frames = env
    made = client.post("/api/v1/ai/connections", json={
        "preset": "custom", "base_url": "https://openai.test/v1", "key": SECRET,
        "options": {"protocol": "openai_chat", "capabilities": ["chat"]}}).json()
    cid, revision = made["connection"]["id"], made["revision"]
    stale = client.patch(f"/api/v1/ai/connections/{cid}", json={"label": "x", "expected_revision": revision - 1})
    assert stale.status_code == 409 and stale.json()["detail"]["revision"] == revision
    assert SECRET not in stale.text
    moved = client.patch(f"/api/v1/ai/connections/{cid}",
                         json={"base_url": "https://elsewhere.test/v1", "expected_revision": revision})
    assert moved.status_code == 200 and moved.json()["connection"]["has_key"] is False
    assert client.put(f"/api/v1/ai/connections/{cid}/key", json={"key": SECRET}).json()["connection"]["key_hint"] == "WXYZ"
    assert client.delete(f"/api/v1/ai/connections/{cid}/key").json()["connection"]["has_key"] is False
    assert SECRET not in config.read_text()


def test_refused_connection_is_503_unreachable(env):
    client, _config, _tmp, _frames = env
    made = client.post("/api/v1/ai/connections", json={
        "preset": "custom", "base_url": "https://down.test/v1", "key": SECRET,
        "options": {"protocol": "openai_chat", "auth": "bearer", "capabilities": ["chat"]}})
    cid = made.json()["connection"]["id"]
    res = client.post("/api/v1/ai/chat", json={"connection": cid, "model": "m-1", "prompt": "ping"})
    assert res.status_code == 503 and res.json()["detail"]["error"] == "unreachable"
    assert SECRET not in res.text
