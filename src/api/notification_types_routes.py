
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.notifications import kind_specs, types

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
    }


def _kind_view(spec: kind_specs.KindSpec) -> Dict[str, Any]:
    return {
        "id": spec.id,
        "label_key": spec.label_key,
        "allow_private": spec.allow_private,
        "sms_like": spec.sms_like,
        "details_allowed": spec.details_allowed,
        "virtual": spec.virtual,
        "public_fields": [_field_view(f) for f in spec.public_fields],
        "secret_fields": [_field_view(f) for f in spec.secret_fields],
    }


@router.get("/types")
async def get_notification_types() -> Dict[str, Any]:
    """The ordered type registry and the destination kinds.

    Output: ``{"families": [...], "types": [...], "kinds": [...]}``; every list is in display order.
    Example: GET /api/v1/notifications/types -> 200 with 29 ``types`` rows.
    """
    families: List[Dict[str, str]] = [{"id": f, "label_key": f"notify.family.{f}"} for f in types.FAMILIES]
    return {
        "families": families,
        "types": [_type_view(t) for t in types.ordered_types()],
        "kinds": [_kind_view(k) for k in kind_specs.ordered_kinds()],
    }
