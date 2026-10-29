
import asyncio
import json
from typing import Any, Dict, List

import pytest

from src.config.byoai_extra_body import EXTRA_BODY_OPTION, ExtraBodyError, parse_extra_body
from src.core.byoai import model_catalog
from src.core.byoai.contracts import (
    ByoaiError, ChatMessage, ChatRequest, Connection, ProviderHTTPError, Target,
)
from src.core.byoai.keys import KeyStore
from src.core.byoai.store import ByoaiStore
from src.core.byoai.wire import openai_chat

THINKING_OFF = '{"chat_template_kwargs": {"enable_thinking": false}}'

VLLM_MODELS = {"object": "list", "data": [{
    "id": "nemotron-3-super", "object": "model", "created": 1791152973, "owned_by": "vllm",
    "root": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4", "parent": None, "max_model_len": 98304,
    "permission": [{"id": "modelperm-1", "object": "model_permission", "allow_sampling": True}]}]}


class _NoKeychain:

    def state(self, service: str, account: str) -> str:
        return "absent"

    def read(self, service: str, account: str):
        return None

    def write(self, service: str, account: str, secret: str) -> None:
        raise AssertionError("no key is written in these tests")

    def delete(self, service: str, account: str) -> bool:
        return False


class _Response:

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def json(self) -> Dict[str, Any]:
        return self._data


def _spark(options: Dict[str, Any]) -> Connection:
    return Connection(id="custom-5a57", preset="custom", label="spark", base_url="http://10.0.0.8:8080/v1",
                      options={"protocol": "openai_chat", "capabilities": ["chat"], "auth": "none", **options})


@pytest.fixture
def store(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"config_version": 7, "other_block": {"keep": True}}))
    return config, ByoaiStore(config, keys=KeyStore(backend=_NoKeychain()))


def test_extra_fields_are_merged_into_every_chat_request(monkeypatch):
    sent: List[Dict[str, Any]] = []

    async def fake_request(connection, key, method, path, **kwargs):
        sent.append(kwargs["json"])
        return _Response({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(openai_chat.transport, "request", fake_request)
    target = Target(_spark({EXTRA_BODY_OPTION: THINKING_OFF}), "nemotron-3-super")
    request = ChatRequest(messages=(ChatMessage("user", "label this"),), max_tokens=20)
    result = asyncio.run(openai_chat.chat(target, None, request))

    assert result.text == "ok"
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent[0]["model"] == "nemotron-3-super" and sent[0]["max_tokens"] == 20

    body = openai_chat.build_body("m", ChatRequest(messages=(ChatMessage("user", "x"),),
                                                   extra={"chat_template_kwargs": {"enable_thinking": True}}),
                                  stream=True, connection_fields=openai_chat.connection_extra(target.connection))
    assert body["chat_template_kwargs"] == {"enable_thinking": True} and body["stream"] is True

    plain = openai_chat.build_body("m", request, connection_fields=openai_chat.connection_extra(_spark({})))
    assert "chat_template_kwargs" not in plain


@pytest.mark.parametrize("text", [
    '{"authorization": "x"}', '{"api_key": "x"}', '{"Api-Key": "x"}', '{"x-api-key": "x"}',
    '{"headers": {"Authorization": "x"}}', '{"extra": [{"access_token": "x"}]}', '{"password": "x"}',
    '{"note": "Bearer abcdefghijklmnop"}',
])
def test_secret_keys_and_values_are_refused(store, text):
    config, s = store
    with pytest.raises(ExtraBodyError):
        parse_extra_body(text)
    with pytest.raises(ByoaiError):
        s.add_connection(preset="custom", base_url="http://10.0.0.8:8080/v1",
                         options={"protocol": "openai_chat", "capabilities": ["chat"], "auth": "none",
                                  EXTRA_BODY_OPTION: text})
    assert "byoai" not in json.loads(config.read_text())


@pytest.mark.parametrize("text", ['[1]', '"x"', '{not json', '{"model": "other"}', '{"messages": []}'])
def test_non_objects_and_reserved_fields_are_refused(text):
    with pytest.raises(ExtraBodyError):
        parse_extra_body(text)


def test_ordinary_names_with_secret_lookalike_parts_pass():
    fields = parse_extra_body('{"max_tokens": 5, "top_k": 20, "skip_special_tokens": false}')
    assert fields == {"max_tokens": 5, "top_k": 20, "skip_special_tokens": False}
    assert parse_extra_body("") == {} and parse_extra_body(None) == {}


def test_storing_the_setting_bumps_no_config_version(store):
    config, s = store
    conn = s.add_connection(preset="custom", base_url="http://10.0.0.8:8080/v1",
                            options={"protocol": "openai_chat", "capabilities": ["chat"], "auth": "none"})
    s.update_connection(conn.id, options={"protocol": "openai_chat", "capabilities": ["chat"], "auth": "none",
                                          EXTRA_BODY_OPTION: THINKING_OFF})
    data = json.loads(config.read_text())
    assert data["config_version"] == 7 and data["other_block"] == {"keep": True}
    saved = data["byoai"]["connections"][0]
    assert saved["options"][EXTRA_BODY_OPTION] == THINKING_OFF
    assert set(saved) == {"id", "preset", "label", "base_url", "options", "enabled", "key_host", "key_hint",
                          "models", "created_at", "updated_at"}


def test_the_model_list_parses_the_vllm_response(monkeypatch):
    async def fake_request(connection, key, method, path, **kwargs):
        assert (method, path) == ("GET", "/models")
        return _Response(VLLM_MODELS)

    monkeypatch.setattr(openai_chat.transport, "request", fake_request)

    async def run(protocol, call):
        return await call(None)

    found = asyncio.run(model_catalog.discover(_spark({}), run))
    assert [m.id for m in found] == ["nemotron-3-super"]
    assert found[0].capabilities == ("chat",) and found[0].context_length == 98304


def test_a_custom_server_without_a_model_list_fails_soft(monkeypatch):
    async def run(protocol, call):
        raise ProviderHTTPError(404, "not found")

    assert asyncio.run(model_catalog.discover(_spark({}), run)) == []
