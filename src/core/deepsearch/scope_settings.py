
from __future__ import annotations

from typing import Any

import structlog

from src.core.deepsearch import index_scope

logger = structlog.get_logger()


def wake_pipeline() -> bool:
    from src.core.pipeline import runtime as pipeline_runtime  # noqa: PLC0415

    engine = pipeline_runtime.current()
    if engine is None:
        return False
    try:
        engine.rescan()
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("deepsearch_scope_rescan_failed", error_type=type(exc).__name__, error=str(exc)[:300])
        return False
    return True


def save(store: Any, scope: str) -> Any:
    result = store.update({index_scope.PREFERENCE_FIELD: scope})
    if result.status == "committed":
        wake_pipeline()
    return result
