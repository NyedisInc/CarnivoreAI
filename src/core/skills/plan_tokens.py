
from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.sessions.ports import Clock
from src.core.skills.sweeper import MAX_CONCURRENT_STAGING

logger = structlog.get_logger()

PLAN_TOKEN_TTL_SECONDS: float = 600.0

MAX_OUTSTANDING_TOKENS = MAX_CONCURRENT_STAGING - 2


@dataclass(frozen=True)
class StagedPlan:

    token: str
    staging: Path
    staged: Any
    item_id: str
    version: str
    scope: str
    project_path: Optional[str]
    created: float


class StagedPlanStore:

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock
        self._plans: Dict[str, StagedPlan] = {}

    def put(
        self,
        *,
        staging: Path,
        staged: Any,
        item_id: str,
        version: str,
        scope: str,
        project_path: Optional[str],
    ) -> tuple[StagedPlan, List[StagedPlan]]:
        dropped = self.sweep()
        plan = StagedPlan(
            token=secrets.token_urlsafe(16),
            staging=staging,
            staged=staged,
            item_id=item_id,
            version=version,
            scope=scope,
            project_path=project_path,
            created=self._clock.monotonic(),
        )
        while len(self._plans) >= MAX_OUTSTANDING_TOKENS:
            oldest = min(self._plans.values(), key=lambda entry: entry.created)
            dropped.append(self._plans.pop(oldest.token))
            logger.info("skill_plan_token_evicted", token_count=len(self._plans))
        self._plans[plan.token] = plan
        return plan, dropped

    def take(self, token: Optional[str]) -> tuple[Optional[StagedPlan], List[StagedPlan]]:
        expired = self.sweep()
        if not token:
            return None, expired
        claimed = self._plans.pop(token, None)
        return claimed, expired

    def sweep(self) -> List[StagedPlan]:
        cutoff = self._clock.monotonic() - PLAN_TOKEN_TTL_SECONDS
        expired = [
            entry for entry in self._plans.values() if entry.created <= cutoff
        ]
        for entry in expired:
            self._plans.pop(entry.token, None)
        if expired:
            logger.info("skill_plan_tokens_expired", count=len(expired))
        return expired

    def outstanding(self) -> int:
        return len(self._plans)
