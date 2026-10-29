
from __future__ import annotations

import asyncio
import mimetypes
import time
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote, urlsplit

import httpx
import structlog

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_AUDIO, CAP_IMAGE, CAP_VIDEO, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_FAL,
    ByoaiError, Connection, MediaItem, MediaResult, ModelInfo, NotConfigured,
    ProviderTimeout, Target, TestResult, Unsupported,
)

log = structlog.get_logger(__name__)

PROTOCOL = PROTO_FAL
CAPABILITIES = frozenset({CAP_IMAGE, CAP_VIDEO, CAP_AUDIO})
EXTRAS = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

TEST_MODEL = "fal-ai/flux/schnell"

POLL_START_S = 0.5
POLL_FACTOR = 1.5
POLL_MAX_S = 5.0
DEFAULT_TIMEOUT_S = 600.0

_FAILED = frozenset({"FAILED", "ERROR", "CANCELLED", "CANCELED"})

LISTING_URL = "https://api.fal.ai/v1/models"
_CATEGORIES = {
    CAP_IMAGE: ("text-to-image", "image-to-image"),
    CAP_VIDEO: ("text-to-video", "image-to-video", "video-to-video"),
    CAP_AUDIO: ("text-to-audio", "text-to-speech", "audio-to-audio"),
}
_PAGE_LIMIT = 100
_MAX_PAGES = 10


def _path_on_host(connection: Connection, url: str) -> str:
    parts = urlsplit(url)
    if transport.host_of(url) != transport.host_of(connection.base_url):
        raise ByoaiError("fal returned a URL on another host; refusing to send the key there")
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _timeout_s(connection: Connection) -> float:
    value = connection.options.get("timeout_s")
    return float(value) if isinstance(value, (int, float)) and value > 0 else DEFAULT_TIMEOUT_S


def _failure(payload: Mapping[str, Any], key: Optional[str]) -> Optional[str]:
    status = str(payload.get("status") or "").upper()
    error = payload.get("error")
    if status in _FAILED or (status == "COMPLETED" and error):
        return transport.scrub(f"fal job {status.lower() or 'failed'}: {error or payload.get('detail') or ''}", key)
    return None


async def _wait_completed(connection: Connection, key: Optional[str], status_path: str,
                          cancel_path: Optional[str]) -> None:
    deadline = time.monotonic() + _timeout_s(connection)
    wait = POLL_START_S
    while True:
        status = (await transport.request(connection, key, "GET", status_path)).json()
        failed = _failure(status, key)
        if failed:
            raise ByoaiError(failed)
        if str(status.get("status") or "").upper() == "COMPLETED":
            return
        if time.monotonic() + wait > deadline:
            if cancel_path:
                try:
                    await transport.raw(connection, key, "PUT", cancel_path)
                except ByoaiError as exc:
                    log.warning("byoai_fal_cancel_failed", error=str(exc))
            raise ProviderTimeout("fal job did not finish before the timeout")
        await asyncio.sleep(wait)
        wait = min(wait * POLL_FACTOR, POLL_MAX_S)


def _as_dicts(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    rows = value if isinstance(value, list) else [value]
    out: List[Dict[str, Any]] = []
    for row in rows:
        if isinstance(row, str):
            out.append({"url": row})
        elif isinstance(row, dict) and isinstance(row.get("url"), str):
            out.append(row)
    return out


def _num(value: Any, kind: type) -> Any:
    return kind(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def map_items(result: Mapping[str, Any]) -> tuple:
    items: List[MediaItem] = []
    for field in ("images", "image", "video", "videos", "audio", "audio_file", "audio_url"):
        for row in _as_dicts(result.get(field)):
            mime = row.get("content_type") or mimetypes.guess_type(urlsplit(row["url"]).path)[0] or ""
            items.append(MediaItem(url=row["url"], mime=str(mime), width=_num(row.get("width"), int),
                                   height=_num(row.get("height"), int),
                                   duration_s=_num(row.get("duration", row.get("duration_s")), float)))
    return tuple(items)


async def generate(target: Target, key: Optional[str], prompt: str,
                   input: Mapping[str, Any]) -> MediaResult:
    if not target.model:
        raise NotConfigured("fal needs a model id such as fal-ai/flux/schnell")
    conn = target.connection
    path = "/" + "/".join(quote(seg, safe="") for seg in target.model.strip("/").split("/"))
    submitted = (await transport.request(conn, key, "POST", path,
                                         json={"prompt": prompt, **dict(input)})).json()
    status_url, response_url = submitted.get("status_url"), submitted.get("response_url")
    if not (isinstance(status_url, str) and isinstance(response_url, str)):
        raise ByoaiError("fal did not return status and response urls")
    cancel_url = submitted.get("cancel_url")
    await _wait_completed(conn, key, _path_on_host(conn, status_url),
                          _path_on_host(conn, cancel_url) if isinstance(cancel_url, str) else None)
    result = (await transport.request(conn, key, "GET", _path_on_host(conn, response_url))).json()
    failed = _failure(result, key) if isinstance(result, dict) else None
    if failed:
        raise ByoaiError(failed)
    return MediaResult(items=map_items(result), raw=result)


async def _category_models(client: httpx.AsyncClient, category: str, cap: str) -> List[ModelInfo]:
    out: List[ModelInfo] = []
    cursor: Optional[str] = None
    for _ in range(_MAX_PAGES):
        params = {"category": category, "limit": _PAGE_LIMIT, **({"cursor": cursor} if cursor else {})}
        response = await client.get(LISTING_URL, params=params)
        response.raise_for_status()
        body = response.json()
        for entry in body.get("models") or []:
            meta = entry.get("metadata") or {}
            if entry.get("endpoint_id") and meta.get("status", "active") == "active":
                out.append(ModelInfo(id=entry["endpoint_id"], capabilities=(cap,),
                                     label=meta.get("display_name") or entry["endpoint_id"],
                                     meta={"category": category}))
        cursor = body.get("next_cursor")
        if not (body.get("has_more") and cursor):
            break
    return out


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    on_fal = transport.host_of(connection.key_host or connection.base_url) == "queue.fal.run"
    headers = transport.auth_headers(connection, key) if on_fal else {}
    try:
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=15.0,
                                     headers=headers) as client:
            found = [m for cap, cats in _CATEGORIES.items() for cat in cats
                     for m in await _category_models(client, cat, cap)]
    except httpx.TimeoutException as exc:
        raise ProviderTimeout("fal's model listing timed out") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ByoaiError(f"fal's model listing failed: {type(exc).__name__}") from exc
    return list({m.id: m for m in found}.values())


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    if capability != CAP_IMAGE:
        raise Unsupported(f"fal has no cheap test for {capability}")
    model = target.model or TEST_MODEL
    started = time.monotonic()
    result = await generate(Target(target.connection, model), key, "a small red square",
                            {"image_size": "square", "num_images": 1})
    ms = int((time.monotonic() - started) * 1000)
    first = result.items[0] if result.items else None
    return TestResult(ok=first is not None, capability=capability, latency_ms=ms, model=model,
                      detail=f"{first.mime or 'image'} {first.width}x{first.height} {first.url}" if first
                      else "the job finished with no image")
