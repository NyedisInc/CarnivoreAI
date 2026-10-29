
from __future__ import annotations

from dataclasses import replace
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
import structlog

from src.core.byoai import adapters, transport
from src.core.byoai.contracts import CAP_CHAT, CAP_IMAGE, PROTO_OPENAI_IMAGES, ByoaiError, Connection, ModelInfo, Preset, Unsupported
from src.core.byoai.media.openai_images import IMAGE_LISTING_BY_PRESET
from src.core.byoai.presets import enabled_capabilities, get_preset, protocol_for

logger = structlog.get_logger()

POPULAR_LIMIT = 12

Runner = Callable[[str, Callable[[Optional[str]], Awaitable[Any]]], Awaitable[Any]]


async def discover(connection: Connection, run: Runner) -> List[ModelInfo]:
    preset = get_preset(connection.preset)
    if preset.model_source == "fixed":
        return [ModelInfo(m, tuple(preset.capabilities)) for m in preset.default_models]
    if preset.model_source == "manual":
        return []
    offered = enabled_capabilities(preset, connection.options)
    if not offered:
        return []
    protocol = protocol_for(preset, connection.options, CAP_CHAT if CAP_CHAT in offered else offered[0])
    try:
        found = await run(protocol, lambda key: adapters.list_models(protocol, connection, key))
    except Unsupported:
        return []
    except ByoaiError as exc:
        if not preset.custom:
            raise
        logger.warning("byoai.custom_discovery_failed", connection=connection.id, error=type(exc).__name__)
        return []
    if preset.id in IMAGE_LISTING_BY_PRESET and CAP_IMAGE in offered:
        found = await _with_image_listing(connection, found, run)
    if preset.popular_sort or preset.popular_url:
        found = await _rank_by_provider(connection, preset, protocol, found, run)
    return found


async def _with_image_listing(connection: Connection, models: List[ModelInfo], run: Runner) -> List[ModelInfo]:
    try:
        images = await run(PROTO_OPENAI_IMAGES, lambda key: adapters.list_models(PROTO_OPENAI_IMAGES, connection, key))
    except (ByoaiError, httpx.HTTPError, ValueError) as exc:
        logger.warning("byoai.image_listing_failed", connection=connection.id, error=str(exc)[:200])
        images = []
    served = {m.id: m for m in images}
    out = [replace(m, capabilities=tuple(c for c in m.capabilities if c != CAP_IMAGE) + ((CAP_IMAGE,) if m.id in served else ()))
           for m in models]
    out = [m for m in out if m.capabilities]
    known = {m.id for m in out}
    return out + [m for i, m in served.items() if i not in known]


async def _fetch_popular_ids(connection: Connection, preset: Preset, protocol: str, run: Runner) -> List[str]:
    if preset.popular_sort:
        response = await run(protocol, lambda key: transport.request(
            connection, key, "GET", "/models", params={"sort": preset.popular_sort}))
        entries = response.json().get("data") or []
    else:
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=10.0) as client:
            response = await client.get(preset.popular_url)
            response.raise_for_status()
        entries = response.json()
    return [str(e["id"]) for e in entries if isinstance(e, dict) and e.get("id")]


async def _rank_by_provider(connection: Connection, preset: Preset, protocol: str, models: List[ModelInfo],
                            run: Runner) -> List[ModelInfo]:
    try:
        order = await _fetch_popular_ids(connection, preset, protocol, run)
    except (ByoaiError, httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("byoai.popular_failed", connection=connection.id, error=str(exc)[:200])
        return models
    known = {m.id for m in models}
    ranks = {model_id: i for i, model_id in enumerate([i for i in order if i in known][:POPULAR_LIMIT])}
    return [replace(m, meta={**m.meta, "popular_rank": ranks[m.id]}) if m.id in ranks else m for m in models]


def featured_ranks(preset: Preset, models: List[ModelInfo]) -> Dict[str, int]:
    ranks: Dict[str, int] = {}
    for rank, wanted in enumerate(preset.featured):
        ids = [m.id for m in models if m.id.removeprefix("models/").startswith(wanted)]
        exact = [i for i in ids if i.removeprefix("models/") == wanted]
        pick = exact[0] if exact else (max(ids) if ids else None)
        if pick is not None and pick not in ranks:
            ranks[pick] = rank
    return ranks


def with_overrides(connection: Connection, models: List[ModelInfo]) -> List[ModelInfo]:
    out: List[ModelInfo] = []
    seen = set()
    featured = featured_ranks(get_preset(connection.preset), models)
    for m in models:
        o = connection.models.get(m.id) or {}
        meta = {**m.meta, "enabled": False} if o.get("enabled") is False else m.meta
        if m.id in featured and "popular_rank" not in meta:
            meta = {**meta, "popular_rank": featured[m.id]}
        out.append(replace(m, capabilities=tuple(o.get("capabilities") or m.capabilities),
                           flags=tuple(o.get("flags") or m.flags), meta=meta))
        seen.add(m.id)
    for model_id, o in connection.models.items():
        if model_id not in seen:
            out.append(ModelInfo(model_id, tuple(o.get("capabilities") or ()), tuple(o.get("flags") or ()),
                                 meta={"enabled": o.get("enabled", True), "typed": True}))
    return out
