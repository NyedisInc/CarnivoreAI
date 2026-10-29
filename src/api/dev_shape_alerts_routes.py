
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.config import settings
from src.core.attention import registry_contract, transcript_contract
from src.core.subagents import contract as subagent_contract
from src.core.subagents import shape_alert
from src.core.timers import contract as timer_contract

router = APIRouter(prefix="/dev", tags=["dev"])


def contract_catalog() -> Dict[str, int]:
    catalog: Dict[str, int] = {}
    for module in (registry_contract, transcript_contract, subagent_contract, timer_contract):
        catalog.update(module.contract_versions())
    return catalog


@router.get("/shape-alerts", dependencies=[Depends(require_auth)])
async def get_shape_alerts() -> Dict[str, Any]:
    """The recorded mismatches, the switch, and the contract catalog.

    Output: dict - see the module docstring.
    """
    return {
        "enabled": bool(settings.dev_shape_alerts),
        "contracts": contract_catalog(),
        "alerts": shape_alert.recorded(),
    }
