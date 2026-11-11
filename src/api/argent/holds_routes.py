
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.budget_hold.gate import switch_on
from src.core.budget_hold.store import STORE

router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


@router.get("/holds")
async def list_holds() -> Dict[str, Any]:
    """Every current hold. Output: {enabled: bool, holds: [{item_id, item_name, session_keys}]}; with the feature off the list is empty."""
    on = switch_on()
    holds: List[dict] = STORE.snapshot() if on else []
    return {"enabled": on, "holds": holds}
