from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.api.stats_routes import _BoundedBodyRoute, _run, _store
from src.core.stats import tripwires
from src.models.stats import TripwireWrite

router = APIRouter(prefix="/stats/tripwires", tags=["stats"], route_class=_BoundedBodyRoute,
                   dependencies=[Depends(require_auth)])


@router.get("", response_model=None)
async def list_tripwires(request: Request) -> list[dict]:
    """Return every tripwire with its current state."""
    return await _run(tripwires.list_tripwires, _store(request))


@router.post("", response_model=None, status_code=201)
async def post_tripwire(request: Request, value: TripwireWrite) -> dict:
    """Create a tripwire (422 at the 64 limit or on an invalid query)."""
    return await _run(tripwires.create_tripwire, _store(request), value)


@router.get("/{tripwire_id}", response_model=None)
async def get_tripwire(request: Request, tripwire_id: UUID) -> dict:
    """Return one tripwire."""
    return await _run(tripwires.get_tripwire, _store(request), str(tripwire_id))


@router.put("/{tripwire_id}", response_model=None)
async def put_tripwire(request: Request, tripwire_id: UUID, value: TripwireWrite) -> dict:
    """Replace a tripwire; its state resets to unknown."""
    return await _run(tripwires.replace_tripwire, _store(request), str(tripwire_id), value)


@router.delete("/{tripwire_id}", response_model=None, status_code=204)
async def delete_tripwire(request: Request, tripwire_id: UUID) -> None:
    """Delete a tripwire."""
    await _run(tripwires.delete_tripwire, _store(request), str(tripwire_id))
