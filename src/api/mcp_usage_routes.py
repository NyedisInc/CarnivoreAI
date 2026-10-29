
from __future__ import annotations

import sqlite3
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.core.db import DatastoreError
from src.core.mcp import tools
from src.core.mcp_usage import report, rollup

logger = structlog.get_logger()

router = APIRouter(tags=["mcp-usage"], dependencies=[Depends(require_auth)])


def _answer(days: int) -> Dict[str, Any]:
    try:
        rollup.run()
    except (sqlite3.Error, DatastoreError, OSError) as exc:
        logger.warning("mcp_usage_rollup_failed", error_type=type(exc).__name__, error=str(exc))
    return report.build(days, tools.tool_names())


@router.get("/mcp-usage")
async def get_mcp_usage(days: int = Query(report.DEFAULT_DAYS, ge=1, le=report.MAX_DAYS)) -> Dict[str, Any]:
    """Calls per registered tool over the last ``days`` UTC days, by caller kind and outcome.

    Inputs: days (1 to 90, default 30). Output: window, one row per tool (every registered tool, hidden ones included,
    plus any retired name counted in the window with ``registered: false``), and the tools nobody called.
    Description: 503 when the usage file cannot be read.
    """
    try:
        return await run_in_threadpool(_answer, days)
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        raise api_error(503, "datastore_unavailable", exc, step="mcp_usage") from exc
