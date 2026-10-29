
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core import item_settings_store as store
from src.core import resource_push, session_change_notice
from src.core.resource_push import topics as resource_topics
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.item_catalog import ItemCatalogError
from src.core.item_settings_schema import SettingsSchemaError
from src.models.item_settings import ItemSettingsPatch
from src.models.websocket import WSMessageType

logger = structlog.get_logger()

router = APIRouter(tags=["item-settings"])

UNAVAILABLE = "item_settings_unavailable"


def _db_path():
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def _error(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    body: Dict[str, Any] = {"code": code, "detail": detail}
    body.update(extra)
    return HTTPException(status_code=status, detail=body)


def _run(operation: Callable, *args: Any, **kwargs: Any) -> Any:
    with closing(connect(_db_path(), create=False)) as conn:
        return operation(conn, *args, **kwargs)


async def _call(operation: Callable, *args: Any, **kwargs: Any) -> Any:
    if not _db_path().exists():
        raise _error(503, UNAVAILABLE, "datastore has not been created yet")
    try:
        return await run_in_threadpool(_run, operation, *args, **kwargs)
    except store.ItemUnknown as exc:
        raise _error(404, exc.code, str(exc))
    except store.SettingRefused as exc:
        raise _error(400, exc.code, str(exc), key=exc.key)
    except (store.EnabledNotSupported, store.EmptyPatch) as exc:
        raise _error(400, exc.code, str(exc))
    except store.ItemStale as exc:
        raise _error(409, exc.code, str(exc), current=exc.current.as_payload())
    except (ItemCatalogError, SettingsSchemaError) as exc:
        logger.error("item_catalog_unreadable", error=str(exc))
        raise _error(500, "item_catalog_unreadable", "the declared item list could not be read")
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        logger.warning("item_settings_unavailable", error=str(exc))
        raise _error(503, UNAVAILABLE, str(exc))


@router.get("/item-settings", dependencies=[Depends(require_auth)])
async def get_item_settings() -> Dict[str, Any]:
    """The whole settings object: only what someone chose.

    Output: dict - ``{"status": "ok", "revision": int, "items": {...}}``.
    Raises: HTTPException 503.
    Example: GET /api/v1/item-settings
    """
    document = await _call(store.read_document)
    return {"status": "ok", **document}


@router.get("/item-settings/{kind}/{item_id}", dependencies=[Depends(require_auth)])
async def get_item(kind: str, item_id: str) -> Dict[str, Any]:
    """One item: stored choices, dropped keys, schema, revision.

    Inputs: kind (str) - ``widget`` or ``plugin``; item_id (str).
    Output: dict - ``ItemState.as_payload()``.
    Raises: HTTPException 404, 503.
    Example: GET /api/v1/item-settings/widget/core.activity-log
    """
    state = await _call(store.read_item, kind, item_id)
    return state.as_payload()


@router.patch("/item-settings/{kind}/{item_id}", dependencies=[Depends(require_auth)])
async def patch_item(
    request: Request, kind: str, item_id: str, body: ItemSettingsPatch
) -> Dict[str, Any]:
    """Change some of one item's settings and/or its on/off choice.

    Description: every key is validated against the item's declared
      schema before anything is written; the first refusal aborts the
      whole patch with that key's code. Answers the item AS NOW STORED,
      plus ``status`` (``committed`` or ``unchanged``).
    Inputs: request; kind (str); item_id (str); body (ItemSettingsPatch).
    Output: dict.
    Raises: HTTPException 400, 404, 409, 503; 422 bad body.
    Example: PATCH /api/v1/item-settings/widget/core.activity-log {"values": {"showSystem": false}}
    """
    result: store.WriteResult = await _call(
        store.write_item, kind, item_id, body.values, body.enabled, body.expected_revision
    )
    if result.status == store.COMMITTED:
        session_change_notice.publish(
            request.app.state,
            {"type": WSMessageType.ITEM_SETTINGS_CHANGED, "revision": result.document_revision},
        )
        resource_push.notify(resource_topics.ITEM_SETTINGS)
    return {"status": result.status, **result.item.as_payload()}


@router.get("/widgets", dependencies=[Depends(require_auth)])
async def list_widgets() -> Dict[str, Any]:
    """Every widget this build declares, with its effective on/off state.

    Description: a singleton nobody switched off reads ``true``; a
      per-target kind (terminal, browser) reads ``null``, meaning it has no
      switch. Settings themselves are read through ``/item-settings``.
    Output: dict - ``{"widgets": [{id, instancing, enabled, has_settings}]}``.
    Raises: HTTPException 503.
    Example: GET /api/v1/widgets
    """
    return {"widgets": await _call(store.widget_rows)}
