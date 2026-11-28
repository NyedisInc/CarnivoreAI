
from __future__ import annotations

import dataclasses
import platform
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from src.api.auth import require_auth
from src.config import settings
from src.core.notifications import kind_specs, types
from src.core.notify_media import store as media_store
from src.core.notifications.cards.build import build_card
from src.core.notifications.sources import toast as toast_source
from src.core.notifications.styles import effective_style

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


def _field_view(field: kind_specs.FieldSpec) -> Dict[str, Any]:
    return {"name": field.name, "type": field.type, "required": field.required, "choices": list(field.choices)}


def _type_view(row: types.NotifyType) -> Dict[str, Any]:
    d = row.defaults
    return {
        "id": row.id,
        "family": row.family,
        "label_key": row.label_key,
        "description_key": row.description_key,
        "source": row.source,
        "defaults": {
            "screen": d.screen,
            "seed": d.seed,
            "outside_locked_off": d.outside_locked_off,
            "passes_quiet_hours": d.passes_quiet_hours,
            "screen_surface": d.screen_surface,
        },
        "seed_excluded_kinds": list(row.seed_excluded_kinds),
        "hidden": row.id in types.DEV_ONLY and not settings.dev_shape_alerts,
    }


def _kind_view(spec: kind_specs.KindSpec) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": spec.id,
        "label_key": spec.label_key,
        "allow_private": spec.allow_private,
        "sms_like": spec.sms_like,
        "details_allowed": spec.details_allowed,
        "virtual": spec.virtual,
        "public_fields": [_field_view(f) for f in spec.public_fields],
        "secret_fields": [_field_view(f) for f in spec.secret_fields],
    }
    if spec.label:
        out["label"] = spec.label
    if spec.plugin_id:
        out["plugin_id"] = spec.plugin_id
    return out


@router.get("/types")
async def get_notification_types() -> Dict[str, Any]:
    """The ordered type registry and the destination kinds.

    Output: ``{"families": [...], "types": [...], "kinds": [...], "aliases": {...}}``; every list is in display order and
    ``aliases`` maps a retired type id to the row that absorbed it (a client canonicalises a toast's type through it).
    Example: GET /api/v1/notifications/types -> 200 with 37 ``types`` rows in 8 ``families`` (the groups).
    """
    families: List[Dict[str, str]] = [{"id": f, "label_key": f"notify.family.{f}"} for f in types.FAMILIES]
    return {
        "families": families,
        "types": [_type_view(t) for t in types.ordered_types()],
        "kinds": [_kind_view(k) for k in kind_specs.ordered_kinds()],
        "aliases": dict(types.ALIASES),
    }


@router.get("/cards/{toast_id}")
async def get_notification_card(toast_id: str, request: Request) -> Dict[str, Any]:
    """The card of one recorded toast, built for the owner's own screens (the web card and this computer's corner card; details on, no capability).

    Output: ``{"kind", "type", "title", "body", "sub", "lv", "snd", "acts": [[id, label]], "card": {...full card...}, "media"?}``, the same shapes
    the sealed phone payload carries (``docs/notify-cards.md``); ``test_target`` ("app" or "desktop") only on a test toast; ``media`` is the attachment descriptor (``id``, ``mime``, ``bytes``, ``w``, ``h``,
    ``dur``) the two media routes below serve, present only on a file, image or video card.
    Raises: HTTPException 404 - no toast with this id, or one that sends no notification.
    Example: GET /api/v1/notifications/cards/3f2a... -> 200 with ``kind`` "permission"
    """
    manager = request.app.state.session_manager
    event = toast_source.event_for_toast_id(manager, toast_id)
    if event is None:
        raise HTTPException(status_code=404, detail="no such notification")
    event = dataclasses.replace(event, computer=platform.node().split(".")[0][:64])
    built = await build_card(event, detail=True)
    style = effective_style(event.type_id)
    out: Dict[str, Any] = {"kind": built.kind, "type": built.type_id, "title": built.title, "body": built.body, "sub": built.sub,
                           "lv": style.level, "snd": style.sound, "acts": [list(a) for a in built.acts], "card": built.full}
    test_target = toast_source.test_target_for_toast_id(manager, toast_id)
    if test_target:
        out["test_target"] = test_target
    if built.media:
        out["media"] = built.media
    if built.item:
        out["item"] = built.item
    return out


def _serve_media(media_id: str, poster: bool) -> FileResponse:
    found = media_store.entry(media_id)
    path = (found.poster if poster else found.path) if found is not None else None
    if found is None or path is None:
        raise HTTPException(status_code=404, detail="no such media")
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    return FileResponse(path, media_type="image/png" if poster else found.mime, headers=headers, filename=media_id, content_disposition_type="attachment")


@router.get("/media/{media_id}")
async def get_notification_media(media_id: str) -> FileResponse:
    """The attachment bytes of a card (image, video or file) for the owner's own screens, with its stored mime. 404 for an unknown id."""
    return _serve_media(media_id, poster=False)


@router.get("/media/{media_id}/poster")
async def get_notification_media_poster(media_id: str) -> FileResponse:
    """The attachment's poster PNG (a video frame or a PDF first page) for the owner's own screens. 404 for an unknown id or one with no poster."""
    return _serve_media(media_id, poster=True)
