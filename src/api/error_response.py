
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Optional

import structlog
from fastapi import HTTPException

from src.core.notifications.catalog_lines import read_prefixed

logger = structlog.get_logger()

CATALOG_PREFIX = "api.error."

_STATUS_FALLBACK_CODES: Dict[int, str] = {
    400: "invalid_request", 404: "not_found", 409: "conflict", 422: "invalid_request",
    502: "upstream_failed", 503: "service_unavailable",
}
GENERIC_CODE = "internal_error"


@lru_cache(maxsize=1)
def error_sentences() -> Dict[str, str]:
    return {key[len(CATALOG_PREFIX):]: text for key, text in read_prefixed((CATALOG_PREFIX,)).items()}


def sentence_for(code: str, status: int) -> str:
    sentences = error_sentences()
    if code in sentences:
        return sentences[code]
    return sentences[_STATUS_FALLBACK_CODES.get(status, GENERIC_CODE)]


def log_failure(status: int, code: str, exc: Optional[BaseException], **context: Any) -> None:
    emit = logger.error if status >= 500 else logger.warning
    fields: Dict[str, Any] = {
        "status": status, "code": code,
        "error": str(exc) if exc is not None else None,
        "error_type": type(exc).__name__ if exc is not None else None,
    }
    fields.update(context)
    emit("api_request_failed", **fields)


def soft_failure(code: str, exc: Optional[BaseException] = None, *, status: int = 503, **context: Any) -> str:
    log_failure(status, code, exc, **context)
    return sentence_for(code, status)


def sentence_of(detail: object) -> str:
    if isinstance(detail, dict):
        return str(detail.get("detail") or detail.get("code") or "")
    return str(detail)


def refusal_error(exc: Any, *, status: Optional[int] = None, extra: Optional[Dict[str, Any]] = None,
                  headers: Optional[Dict[str, str]] = None, **context: Any) -> HTTPException:
    return api_error(status if status is not None else exc.status, exc.code, exc, extra=extra, headers=headers, **context)


def api_error(status: int, code: str, exc: Optional[BaseException] = None, *,
              extra: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
              **context: Any) -> HTTPException:
    log_failure(status, code, exc, **context)
    detail: Dict[str, Any] = {"code": code, "detail": sentence_for(code, status)}
    detail.update(extra or {})
    return HTTPException(status_code=status, detail=detail, headers=headers)
