
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator

import structlog
from fastapi import Request

from src.api.error_response import api_error
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
    except StaleRevision as exc:
        raise api_error(409, "byoai_stale_revision", exc, extra={"revision": gateway.store.read().revision}) from None
    except NotConfigured as exc:
        raise api_error(404, "byoai_not_configured", exc) from None
    except (MissingKey, InvalidKey) as exc:
        raise api_error(400, "byoai_key_rejected", exc) from None
    except Unsupported as exc:
        raise api_error(400, "byoai_unsupported", exc) from None
    except ProviderHTTPError as exc:
        raise api_error(502, "byoai_provider_error", exc, extra={"provider_status": exc.status},
                         provider_body=exc.body) from None
    except ProviderTimeout as exc:
        raise api_error(504, "byoai_timeout", exc) from None
    except ByoaiUnreachable as exc:
        raise api_error(503, "byoai_unreachable", exc) from None
    except ByoaiError as exc:
        raise api_error(400, "byoai_invalid", exc) from None
