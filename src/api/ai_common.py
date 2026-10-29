
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator

import structlog
from fastapi import HTTPException, Request

from src.config.byoai import ConnectionConfig
from src.core import session_change_notice
from src.core.byoai.contracts import (
    ByoaiError, ByoaiUnreachable, InvalidKey, MissingKey, NotConfigured, ProviderHTTPError, ProviderTimeout,
    StaleRevision, Unsupported,
)
from src.core.byoai.gateway import Gateway
from src.models import WSMessageType

logger = structlog.get_logger()


def connection_view(item: ConnectionConfig) -> Dict[str, Any]:
    data = item.model_dump(mode="json")
    data["has_key"] = data["key_host"] is not None
    return data


def publish_changed(request: Request, revision: int) -> None:
    session_change_notice.publish(request.app.state, {"type": WSMessageType.AI_CONFIG_CHANGED, "revision": revision})


@contextmanager
def api_errors(gateway: Gateway) -> Iterator[None]:
    try:
        yield
    except StaleRevision:
        raise HTTPException(409, {"error": "stale_revision", "revision": gateway.store.read().revision,
                                  "detail": "the AI settings changed; reload and try again"}) from None
    except NotConfigured as exc:
        raise HTTPException(404, {"error": "not_configured", "detail": str(exc)}) from None
    except (MissingKey, InvalidKey) as exc:
        raise HTTPException(400, {"error": "key", "detail": str(exc)}) from None
    except Unsupported as exc:
        raise HTTPException(400, {"error": "unsupported", "detail": str(exc)}) from None
    except ProviderHTTPError as exc:
        raise HTTPException(502, {"error": "provider_error", "provider_status": exc.status,
                                  "detail": exc.body}) from None
    except ProviderTimeout as exc:
        raise HTTPException(504, {"error": "timeout", "detail": str(exc)}) from None
    except ByoaiUnreachable as exc:
        raise HTTPException(503, {"error": "unreachable", "detail": str(exc)}) from None
    except ByoaiError as exc:
        raise HTTPException(400, {"error": "invalid", "detail": str(exc)}) from None
