
import asyncio
import base64
import json

import httpx

from src.core.byoai import transport
from src.core.byoai.contracts import CAP_IMAGE, Connection, Target
from src.core.byoai.media import openai_images
from src.core.byoai.presets import get_preset

PNG = b"\x89PNG-test-bytes"
KEY = "k" * 12 + "OR01"


def _run(preset: str, base: str):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}],
                                          "usage": {"cost": 0.042}})

    real = httpx.AsyncClient
    transport.httpx.AsyncClient = lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    try:
        conn = Connection(id="c1", preset=preset, base_url=base, key_host=base.split("/", 3)[0] + "//" + base.split("/")[2])
        result = asyncio.run(openai_images.generate(Target(conn, "openai/gpt-image-2"), KEY, "a cat", {"n": 1}))
    finally:
        transport.httpx.AsyncClient = real
    return seen, result


def test_openrouter_posts_to_images_and_decodes_bytes_and_cost():
    assert CAP_IMAGE in get_preset("openrouter").capabilities
    seen, result = _run("openrouter", "https://openrouter.ai/api/v1")
    assert seen == [("/api/v1/images", {"prompt": "a cat", "n": 1, "model": "openai/gpt-image-2"})]
    assert result.items[0].data == PNG and not result.items[0].url
    assert result.usage.cost_usd == 0.042


def test_openai_keeps_images_generations():
    seen, _ = _run("openai", "https://api.openai.com/v1")
    assert seen[0][0] == "/v1/images/generations"


def test_bad_cost_values_are_ignored():
    import pytest
    for bad in (True, -1, float("nan"), float("inf")):
        def handler(request, bad=bad):
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}], "usage": {"cost": bad}})
        real = httpx.AsyncClient
        transport.httpx.AsyncClient = lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
        try:
            conn = Connection(id="c1", preset="openrouter", base_url="https://openrouter.ai/api/v1", key_host="https://openrouter.ai")
            r = asyncio.run(openai_images.generate(Target(conn, "openai/gpt-image-2"), KEY, "a cat", {}))
        finally:
            transport.httpx.AsyncClient = real
        assert r.usage is None


def test_card_art_request_fields_pin_quality_and_size():
    from src.core.skill_manager import card_art
    assert card_art._request_fields("openai/gpt-image-2") == {"n": 1, "quality": "medium", "size": "1536x864"}
    assert card_art._request_fields("dall-e-3") == {"n": 1}
