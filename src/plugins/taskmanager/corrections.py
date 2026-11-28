
from __future__ import annotations

import json
from typing import Any, Dict, Optional

KIND = "correction"
KEY = "retracts"
COMPLETION_WITHDRAWN = "completion withdrawn"
CANCELLATION_WITHDRAWN = "cancellation withdrawn"
TASK_CANCELLED = "task cancelled"


def build(outcome: str, closure_id: Optional[int], closed_at: Optional[float], closed_by: Optional[str], restored_state: str = "") -> str:
    return json.dumps({KEY: {"outcome": outcome, "closure_id": closure_id, "closed_at": closed_at, "closed_by": closed_by, "restored_state": restored_state}}, sort_keys=True)


def wire(raw: str) -> Optional[Dict[str, Any]]:
    if not raw or KEY not in raw:
        return None
    try:
        found = json.loads(raw).get(KEY)
    except (ValueError, AttributeError):
        return None
    return found if isinstance(found, dict) else None
