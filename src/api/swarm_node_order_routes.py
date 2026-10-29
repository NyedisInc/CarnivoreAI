
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.auth import require_auth
from src.core.swarm import node_order
from src.core.swarm.node_order import Tier

logger = structlog.get_logger()

router = APIRouter(prefix="/swarm", tags=["swarm"], dependencies=[Depends(require_auth)])


class NodeOrderBody(BaseModel):
    """``GET`` and ``PUT``'s answer: every tier's node keys, first first."""

    companies: List[str]
    projects: List[str]
    agents: List[str]


class NodeOrderWrite(BaseModel):
    """``PUT /swarm/node-order``: one tier and its new order."""

    model_config = ConfigDict(extra="forbid")

    tier: Tier
    keys: List[str] = Field(max_length=node_order.MAX_KEYS)


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


@router.get("/node-order", response_model=NodeOrderBody)
async def get_node_order() -> Dict[str, Any]:
    """Every tier's hand-set order (empty lists when never set). Output: NodeOrderBody."""
    return (await asyncio.to_thread(node_order.read_current, _config_path())).model_dump()


@router.put("/node-order", response_model=NodeOrderBody)
async def put_node_order(payload: NodeOrderWrite) -> Dict[str, Any]:
    """Replace one tier's order. Raises: 422 ``invalid_node_order`` (a bad or repeated key), 500 ``config_unreadable``.

    Output: NodeOrderBody, the whole order as stored.
    """
    try:
        node_order.NodeOrder(**{payload.tier: payload.keys})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_node_order", "message": "each key once, shaped "
                                                     "agent:<id>, company:<id>, project:<id> or session:<uuid>"}) from exc
    try:
        stored = await asyncio.to_thread(node_order.write_tier, _config_path(), payload.tier, payload.keys)
    except (OSError, ValueError) as exc:
        logger.warning("swarm_node_order_write_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail={"code": "config_unreadable", "message": "config.json could not be used"}) from exc
    return stored.model_dump()
