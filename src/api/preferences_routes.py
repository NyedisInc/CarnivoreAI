
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core import ui_preferences_store
from src.core.preferences_push.broadcast import broadcast_changed

logger = structlog.get_logger()

router = APIRouter(tags=["preferences"])

class PreferencesUpdateRequest(BaseModel):
    """A partial preference update, with the revision it expects.

    Attributes:
      changes (dict): field name to new value, ONLY what the user
        changed. ``null`` for a known field unsets it, returning that
        preference to the client's own default.
      expected_revision (int|None): the revision the client last read.
        ``null`` DECLINES the check rather than passing it, which is
        correct for a first write and for a client with nothing to race;
        it is spelled as an explicit null so a client that means to check
        cannot omit the field by accident and get a silent overwrite.
      client_id (str|None): an opaque per-browser id echoed back in the
        broadcast, so the client that made the change can recognise its
        own event and not re-apply it. It is not identity and is not
        trusted for anything.
    """

    model_config = ConfigDict(extra="forbid")

    changes: Dict[str, Any]
    expected_revision: Optional[int] = Field(default=None, ge=0)
    client_id: Optional[str] = Field(default=None, max_length=64)


def _store(request: Request) -> ui_preferences_store.UiPreferencesStore:
    store = getattr(request.app.state, "ui_preferences_store", None)
    if store is None:
        raise HTTPException(
            status_code=503, detail="preferences are not available yet"
        )
    return store


@router.get("/preferences", dependencies=[Depends(require_auth)])
async def get_preferences(request: Request) -> Dict[str, Any]:
    """The whole block: schema version, revision and every stored value.

    Description: THE AUTHORITATIVE REFRESH. A client calls this on
      startup before it initialises any preference-dependent control,
      and again on reconnect, because events are an optimisation and the
      server is the source of truth.
    Inputs: request (Request).
    Output: dict - ``{"status", "schema_version", "revision", "values"}``.
      ``status`` reads ``unchanged`` because a read moved nothing; GET
      and PATCH share one body shape rather than two.
    """
    return _store(request).as_result().as_payload()


@router.patch("/preferences", dependencies=[Depends(require_auth)])
async def update_preferences(
    request: Request, body: PreferencesUpdateRequest
) -> Dict[str, Any]:
    """Apply a partial update, and tell every other client what moved.

    Description: validates, takes the config write lock, re-reads
      config.json inside it, checks the expected revision against THAT
      read, merges and commits. On success it broadcasts
      ``preferences.changed`` carrying the new revision and the fields
      that actually moved.
    Inputs: request (Request); body (PreferencesUpdateRequest).
    Output: dict - the committed values and the revision, so the client
      confirms persistence from the response rather than assuming it.
    Raises:
      HTTPException 400: a field failed validation. The detail is a
        plain sentence and never quotes a refused value.
      HTTPException 409: the expected revision is stale. The body
        carries the CURRENT revision and values to reconcile against.
      HTTPException 500: config.json is missing or unreadable.

    Example:
        PATCH {"changes": {"sidebar_density": "compact"},
               "expected_revision": 4}
    """
    store = _store(request)

    try:
        result = store.update(body.changes, body.expected_revision)
    except FileNotFoundError as exc:
        logger.error("preferences_config_missing", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Configuration not found. Run setup_auth.py first."
        )

    if result.status == ui_preferences_store.REJECTED_INVALID:
        raise HTTPException(status_code=400, detail=result.detail)

    if result.status == ui_preferences_store.STALE_REVISION:
        raise HTTPException(status_code=409, detail=result.as_payload())

    if result.status == ui_preferences_store.COMMITTED:
        await broadcast_changed(request.app.state, result, body.client_id)

    return result.as_payload()
