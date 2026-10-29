
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

LOCAL_MODELS_DEADLINE_SECONDS: float = 4.0

LOCAL_MODELS_MAX_BYTES: int = 1024 * 1024

_EMBEDDING_MARKERS = ("embed", "embedding", "bge-", "gte-", "e5-", "nomic-embed")

LOCAL_NOT_CONFIGURED = "not-configured"

LOCAL_REACHABLE = "reachable"

LOCAL_UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class LocalModels:

    state: str
    models: List[str] = field(default_factory=list)
    host: str = ""
    detail: Optional[str] = None

    @property
    def reachable(self) -> bool:
        return self.state == LOCAL_REACHABLE


def is_embedding_model(model_id: str) -> bool:
    low = (model_id or "").lower()
    return any(marker in low for marker in _EMBEDDING_MARKERS)


def _parse_models(payload: Any) -> Optional[List[str]]:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    ids: List[str] = []
    for entry in data:
        if isinstance(entry, dict):
            mid = entry.get("id")
        elif isinstance(entry, str):
            mid = entry
        else:
            continue
        if isinstance(mid, str) and mid.strip():
            ids.append(mid.strip())
    return [m for m in ids if not is_embedding_model(m)]


def fetch_local_models(
    host: str,
    *,
    deadline: float = LOCAL_MODELS_DEADLINE_SECONDS,
    max_bytes: int = LOCAL_MODELS_MAX_BYTES,
    opener=None,
) -> LocalModels:
    address = (host or "").strip()
    if not address:
        return LocalModels(
            LOCAL_NOT_CONFIGURED,
            detail=(
                "no LM Studio address is configured; set providers.local_host "
                "in config.json to host:port"
            ),
        )

    url = f"http://{address}/v1/models"
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(url, timeout=deadline) as resp:
            raw = resp.read(max_bytes + 1)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        logger.info("local_models_unreachable", host=address, error=str(exc))
        return LocalModels(
            LOCAL_UNREACHABLE, host=address, detail=f"{type(exc).__name__}: {exc}"
        )

    if len(raw) > max_bytes:
        return LocalModels(
            LOCAL_UNREACHABLE,
            host=address,
            detail=f"response larger than {max_bytes} bytes; refusing to parse it",
        )
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return LocalModels(
            LOCAL_UNREACHABLE, host=address, detail=f"response was not JSON: {exc}"
        )

    models = _parse_models(payload)
    if models is None:
        return LocalModels(
            LOCAL_UNREACHABLE,
            host=address,
            detail="answered, but not with an OpenAI-shaped model list",
        )
    return LocalModels(LOCAL_REACHABLE, models=models, host=address)


def to_payload(result: LocalModels) -> Dict[str, Any]:
    return {
        "state": result.state,
        "reachable": result.reachable,
        "host": result.host,
        "models": list(result.models),
        "detail": result.detail,
    }
