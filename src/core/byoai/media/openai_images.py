
from __future__ import annotations

import base64
import binascii
import math
import time
from typing import Any, List, Mapping, Optional

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_IMAGE, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_OPENAI_IMAGES, ByoaiError,
    Connection, MediaItem, MediaResult, ModelInfo, Target, TestResult, Unsupported, Usage,
)

PROTOCOL = PROTO_OPENAI_IMAGES
CAPABILITIES = frozenset({CAP_IMAGE})
EXTRAS = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

_GENERATE_PATH = "/images/generations"
_PATH_BY_PRESET = {"openrouter": "/images"}
IMAGE_LISTING_BY_PRESET = {"openrouter": "/images/models"}
IMAGE_TIMEOUT_S = 300.0
_IMAGE_WORDS = ("dall-e", "gpt-image", "imagine", "image")
_FORMAT_MIMES = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}


_TEST_INPUT = {"quality": "low", "size": "1024x1024"}


def _size(value: Any) -> tuple:
    try:
        w, h = str(value).lower().split("x", 1)
        return int(w), int(h)
    except ValueError:
        return None, None


async def generate(target: Target, key: Optional[str], prompt: str,
                   input: Mapping[str, Any]) -> MediaResult:
    body: dict = {"prompt": prompt, **dict(input)}
    if target.model:
        body["model"] = target.model
    result = (await transport.request(target.connection, key, "POST",
                                      _PATH_BY_PRESET.get(target.connection.preset, _GENERATE_PATH),
                                      json=body, timeout=IMAGE_TIMEOUT_S)).json()
    width, height = _size(body.get("size"))
    mime = _FORMAT_MIMES.get(str(body.get("output_format") or "png").lower(), "image/png")
    items: List[MediaItem] = []
    for row in result.get("data") or []:
        if not isinstance(row, dict):
            continue
        if row.get("b64_json"):
            try:
                data = base64.b64decode(row["b64_json"], validate=True)
            except (binascii.Error, ValueError):
                raise ByoaiError("image server returned invalid base64") from None
            items.append(MediaItem(url="", mime=mime, width=width, height=height, data=data))
        elif row.get("url"):
            items.append(MediaItem(url=str(row["url"]), width=width, height=height))
    if not items:
        raise ByoaiError("image server returned no images")
    cost = (result.get("usage") or {}).get("cost") if isinstance(result.get("usage"), dict) else None
    usable = isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0
    usage = Usage(cost_usd=float(cost)) if usable else None
    return MediaResult(items=tuple(items), raw=result, usage=usage)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    listing = IMAGE_LISTING_BY_PRESET.get(connection.preset)
    body = (await transport.request(connection, key, "GET", listing or "/models")).json()
    return [ModelInfo(id=m["id"], capabilities=(CAP_IMAGE,), label=str(m.get("name") or ""))
            for m in body.get("data", [])
            if isinstance(m, dict) and m.get("id") and (listing or any(w in m["id"].lower() for w in _IMAGE_WORDS))]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    if capability != CAP_IMAGE:
        raise Unsupported(f"openai_images has no test for {capability}")
    started = time.monotonic()
    result = await generate(target, key, "a small red square",
                          _TEST_INPUT if "gpt-image" in (target.model or "").lower() else {})
    ms = int((time.monotonic() - started) * 1000)
    item = result.items[0]
    where = item.url or f"{len(item.data or b'')} bytes inline"
    return TestResult(ok=True, capability=capability, latency_ms=ms, model=target.model, detail=f"{item.mime or 'image'} {where}")
