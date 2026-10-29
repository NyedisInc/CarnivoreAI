from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from src.api.auth import require_auth
from src.api.stats_routes import _BoundedBodyRoute, _on, _run
from src.core.stats import insights
from src.models.stats import ImpactMetric, StatsFilters

router = APIRouter(prefix="/stats", tags=["stats"], route_class=_BoundedBodyRoute,
                   dependencies=[Depends(require_auth)])


@router.get("/conversations", response_model=None)
async def get_conversations(
    request: Request, from_: datetime = Query(alias="from"), to: datetime = Query(),
    provider: Literal["claude", "codex"] | None = None, project: str | None = None,
    model: str | None = None,
    limit: int = Query(insights.CONVERSATION_CAP, ge=1, le=insights.CONVERSATION_CAP),
) -> dict:
    """The costliest conversations of a range, at most 500: duration, cost, tokens, project and model."""
    if from_.tzinfo is None or to.tzinfo is None or from_ >= to:
        raise HTTPException(422, detail={"code": "invalid_range"})
    try:
        filters = StatsFilters.model_validate({key: val for key, val in {
            "provider": provider, "project": project, "model": model}.items() if val is not None})
    except ValidationError as exc:
        raise HTTPException(422, detail={"code": "invalid_stats_filter"}) from exc
    return await _run(insights.conversations, await _on(request), start=int(from_.timestamp()),
                      end=int(to.timestamp()), filters=filters, limit=limit)


@router.get("/impact", response_model=None)
async def get_impact(request: Request, annotation_id: UUID, metric: ImpactMetric = "estimated_cost_nano_usd",
                     days: int = Query(7, ge=1, le=30)) -> dict:
    """A per-conversation metric `days` before against `days` after one marker, with a seeded bootstrap interval."""
    return await _run(insights.impact, await _on(request), annotation_id=str(annotation_id), metric=metric, days=days)
