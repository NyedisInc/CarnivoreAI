import asyncio
from typing import Any

import pytest

from src.core.byoai import transport
from src.core.byoai.contracts import ByoaiError, ChatMessage, ChatRequest, Connection, Target
from src.core.byoai.wire import openai_chat


class _Reply:

    def __init__(self, body: Any) -> None:
        self._body = body

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("Expecting value")
        return self._body


def _conn() -> Connection:
    return Connection(id="custom-1", preset="custom", label="x", base_url="http://10.0.0.1/v1",
                      options={"protocol": "openai_chat", "capabilities": ["chat"], "auth": "none"})


def _serve(monkeypatch, body: Any) -> None:
    async def fake(connection, key, method, path, **kwargs):
        return _Reply(body)
    monkeypatch.setattr(transport, "request", fake)


@pytest.mark.parametrize("body", [None, ["a"], "text", 3])
def test_request_json_maps_bad_bodies(monkeypatch, body):
    _serve(monkeypatch, body)
    with pytest.raises(ByoaiError):
        asyncio.run(transport.request_json(_conn(), None, "GET", "/models"))


def test_request_json_list_ok_and_dict(monkeypatch):
    _serve(monkeypatch, ["a"])
    assert asyncio.run(transport.request_json(_conn(), None, "GET", "/m", list_ok=True)) == ["a"]
    _serve(monkeypatch, {"a": 1})
    assert asyncio.run(transport.request_json(_conn(), None, "GET", "/m")) == {"a": 1}


def test_chat_with_an_html_answer_is_a_byoai_error(monkeypatch):
    _serve(monkeypatch, None)
    request = ChatRequest(messages=(ChatMessage("user", "hi"),), max_tokens=5)
    with pytest.raises(ByoaiError):
        asyncio.run(openai_chat.chat(Target(_conn(), "m"), None, request))
