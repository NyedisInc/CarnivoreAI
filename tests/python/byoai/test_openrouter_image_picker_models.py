
import asyncio

import httpx

from src.core.byoai import transport
from src.core.byoai.contracts import CAP_CHAT, CAP_IMAGE, Connection
from src.core.byoai.model_catalog import discover

CHAT = {"id": "openai/gpt-5.4-image-2", "architecture": {"input_modalities": ["text", "image"],
                                                       "output_modalities": ["image", "text"]}}
PLAIN = {"id": "openai/gpt-4o-mini", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}


def _discover():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/models"):
            return httpx.Response(200, json={"data": [{"id": "openai/gpt-image-2", "name": "ZARWICK Ashvale 2"}]})
        return httpx.Response(200, json={"data": [CHAT, PLAIN]})

    real = httpx.AsyncClient
    transport.httpx.AsyncClient = lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    try:
        conn = Connection(id="c1", preset="openrouter", base_url="https://openrouter.ai/api/v1", key_host="https://openrouter.ai")

        async def run(protocol, call):
            return await call("k" * 12)
        return asyncio.run(discover(conn, run))
    finally:
        transport.httpx.AsyncClient = real


def test_image_picker_lists_served_models_and_not_chat_image_models():
    caps = {m.id: m.capabilities for m in _discover()}
    assert CAP_IMAGE in caps["openai/gpt-image-2"]
    assert caps["openai/gpt-5.4-image-2"] == (CAP_CHAT,)
    assert CAP_IMAGE not in caps["openai/gpt-4o-mini"]
