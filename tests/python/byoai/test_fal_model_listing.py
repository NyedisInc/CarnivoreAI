
import asyncio
import json

import httpx

from src.core.byoai.contracts import CAP_AUDIO, CAP_IMAGE, CAP_VIDEO, Connection
from src.core.byoai.media import fal
from src.core.byoai.model_catalog import discover

_PAGES = {
    ("text-to-image", None): {"models": [
        {"endpoint_id": "fal-ai/flux/schnell", "metadata": {"display_name": "FLUX.1 [schnell]", "status": "active"}},
        {"endpoint_id": "fal-ai/old-model", "metadata": {"display_name": "Old", "status": "deprecated"}}],
        "next_cursor": "Mg", "has_more": True},
    ("text-to-image", "Mg"): {"models": [
        {"endpoint_id": "fal-ai/nano-banana-pro", "metadata": {"display_name": "Nano Banana Pro", "status": "active"}}],
        "next_cursor": None, "has_more": False},
    ("image-to-video", None): {"models": [
        {"endpoint_id": "fal-ai/wan/v2.2/image-to-video", "metadata": {"status": "active"}}],
        "next_cursor": None, "has_more": False},
    ("text-to-speech", None): {"models": [
        {"endpoint_id": "fal-ai/kokoro", "metadata": {"status": "active"}}], "next_cursor": None, "has_more": False},
}


def test_discover_lists_fal_models_by_capability(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        q = request.url.params
        return httpx.Response(200, content=json.dumps(
            _PAGES.get((q["category"], q.get("cursor")), {"models": [], "has_more": False})))

    real = httpx.AsyncClient
    monkeypatch.setattr(fal.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    conn = Connection(id="fal1", preset="fal", base_url="https://queue.fal.run", key_host="https://queue.fal.run")

    async def run_call(protocol, call):
        return await call("sekret")

    models = asyncio.run(discover(conn, run_call))
    caps = {m.id: m.capabilities for m in models}
    assert caps == {"fal-ai/flux/schnell": (CAP_IMAGE,), "fal-ai/nano-banana-pro": (CAP_IMAGE,),
                    "fal-ai/wan/v2.2/image-to-video": (CAP_VIDEO,), "fal-ai/kokoro": (CAP_AUDIO,)}
    assert set(seen) == {"Key sekret"}
