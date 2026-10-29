
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.catalog import install_report_disclosure

router = APIRouter(tags=["catalog"])


@router.get("/catalog/install-report/disclosure", dependencies=[Depends(require_auth)])
async def get_install_report_disclosure() -> Dict[str, List[str]]:
    """The field ids an install report and a first guest account send.

    Output: ``{"report": [...], "guest": [...]}``, ids whose sentences are the string catalog keys
      ``privacy.install_report.field.<id>``.
    Example: GET /catalog/install-report/disclosure -> {"report": ["item_id", "version", "account_id"], ...}
    """
    return {key: list(ids) for key, ids in install_report_disclosure.disclosure().items()}
