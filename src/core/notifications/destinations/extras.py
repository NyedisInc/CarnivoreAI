
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from src.core.notifications import doc_model, kind_specs
from src.core.notifications.destinations.validate import BAD_VALUE, InvalidDestination
from src.core.notifications.settings_doc import view
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore
from src.core.notifications.settings_doc.ticks import SCOPE_GLOBAL, SCOPE_LOCAL, UnknownDestination, write_value

_HHMM = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
MAX_PROJECTS = 50
MAX_PROJECT_LEN = 256
MAX_REMINDER_MINUTES = 1440

PATCH_KEYS = {"away": "away", "quiet": "quiet", "reminder_minutes": "reminder", "projects": "projects", "details": "details"}


class DetailsNotAllowed(ValueError):
    pass


def _kind_of(doc: Doc, dest_id: str) -> Optional[str]:
    if kind_specs.is_push_destination_id(dest_id):
        return kind_specs.virtual_kind_of(dest_id)
    record = view.dest_record(doc, dest_id) if kind_specs.is_destination_id(dest_id) else None
    return record["kind"] if record else None


def check_value(name: str, value: Any) -> Any:
    bad = InvalidDestination({name: BAD_VALUE})
    if name in ("away", "details"):
        if not isinstance(value, bool):
            raise bad
        return value
    if name == "quiet":
        if value is None:
            return None
        if not (isinstance(value, Mapping) and set(value) == {"start", "end"}
                and all(isinstance(value[k], str) and _HHMM.fullmatch(value[k]) for k in value)):
            raise bad
        return {"start": value["start"], "end": value["end"]}
    if name == "reminder_minutes":
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_REMINDER_MINUTES:
            raise bad
        return value
    if name == "projects":
        if not isinstance(value, (list, tuple)) or len(value) > MAX_PROJECTS or not all(
            isinstance(p, str) and 0 < len(p.strip()) <= MAX_PROJECT_LEN for p in value
        ):
            raise bad
        return sorted({p.strip() for p in value})
    raise InvalidDestination({name: "unknown"})


def set_extras(store: SettingsDocStore, dest_id: str, patch: Mapping[str, Any], scope: Optional[str] = None) -> Dict[str, Any]:
    if scope not in (None, SCOPE_GLOBAL, SCOPE_LOCAL):
        raise ValueError("scope must be global or local")
    checked = {PATCH_KEYS[k]: check_value(k, v) for k, v in patch.items() if k in PATCH_KEYS}
    unknown = {k: "unknown" for k in patch if k not in PATCH_KEYS}
    if unknown:
        raise InvalidDestination(unknown)

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        kind = _kind_of(doc, dest_id)
        if kind is None:
            raise UnknownDestination(dest_id)
        spec = kind_specs.get_kind(kind)
        if checked.get("details") and (spec is None or spec.sms_like or not spec.details_allowed):
            raise DetailsNotAllowed(kind)
        always_local = kind in (kind_specs.KIND_WEBPUSH, kind_specs.KIND_APNS) or view.dest_scope(doc, dest_id) == view.SRC_LOCAL
        for extra, value in checked.items():
            doc = write_value(doc, me, doc_model.extra_path(dest_id, extra), value, scope, always_local)
        return doc

    return view.extras(store.update(mutate), dest_id)
