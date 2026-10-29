
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = structlog.get_logger()

ORDER_KEY = "swarm_node_order"
Tier = Literal["companies", "projects", "agents"]
TIERS = ("companies", "projects", "agents")
MAX_KEYS = 500
KEY_PATTERN = r"^(agent|company|project|session):[A-Za-z0-9._:-]{1,128}$"


def _unique(keys: List[str]) -> List[str]:
    if len(set(keys)) != len(keys):
        raise ValueError("a node key is listed twice")
    return keys


class NodeOrder(BaseModel):
    """Every tier's order, first node first. A tier never reordered is an empty list."""

    model_config = ConfigDict(extra="forbid")

    companies: List[str] = Field(default_factory=list, max_length=MAX_KEYS)
    projects: List[str] = Field(default_factory=list, max_length=MAX_KEYS)
    agents: List[str] = Field(default_factory=list, max_length=MAX_KEYS)

    @field_validator("companies", "projects", "agents")
    @classmethod
    def _keys(cls, value: List[str]) -> List[str]:
        import re

        for key in value:
            if not re.fullmatch(KEY_PATTERN, key):
                raise ValueError("a node key must look like agent:<id>, company:<id>, project:<id> or session:<uuid>")
        return _unique(value)


def read_block(config: Dict[str, Any]) -> NodeOrder:
    block = config.get(ORDER_KEY)
    if block is None:
        return NodeOrder()
    try:
        return NodeOrder(**block) if isinstance(block, dict) else NodeOrder()
    except (TypeError, ValidationError) as exc:
        logger.warning("invalid_swarm_node_order", reason=type(exc).__name__)
        return NodeOrder()


def read_current(config_path: Path) -> NodeOrder:
    try:
        data = json.loads(config_path.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("swarm_node_order_unreadable", error_type=type(exc).__name__)
        return NodeOrder()
    return read_block(data) if isinstance(data, dict) else NodeOrder()


def write_tier(config_path: Path, tier: str, keys: List[str]) -> NodeOrder:
    from src.core import config_writer, resource_push
    from src.core.resource_push import topics

    if tier not in TIERS:
        raise ValueError(f"tier must be one of {', '.join(TIERS)}")
    NodeOrder(**{tier: keys})

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        merged = NodeOrder(**{**read_block(doc).model_dump(), tier: keys})
        return {**doc, ORDER_KEY: merged.model_dump()}

    stored = read_block(config_writer.commit(config_path, mutate).data)
    resource_push.notify(topics.SWARM_NODE_ORDER)
    return stored
