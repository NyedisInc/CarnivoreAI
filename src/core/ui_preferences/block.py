
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from pydantic import ValidationError

from src.core.widget_placement.retired_widgets import migrate_retired_placements
from src.core.ui_preferences.constants import MAX_KEY_LENGTH, MAX_UNKNOWN_FIELDS, MAX_UNKNOWN_VALUE_BYTES, RETIRED_FIELDS, SCHEMA_VERSION, UI_PREFERENCES_KEY
from src.core.ui_preferences.values import UiPreferenceValues


_SECRET_KEY_NAMES = frozenset(
    {"claude_tunnel_token", "claude_refresh_token", "provider_accounts"}
)
_SECRET_KEY_SHAPE = re.compile(r"(token|secret|password|passphrase|api[_-]?key)", re.I)

def known_fields() -> frozenset:
    return frozenset(UiPreferenceValues.model_fields.keys())


def is_secret_name(name: str) -> bool:
    return name in _SECRET_KEY_NAMES or bool(_SECRET_KEY_SHAPE.search(name))


def empty_block() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "revision": 0, "values": {}}


def read_block(config: Dict[str, Any]) -> Dict[str, Any]:
    block = config.get(UI_PREFERENCES_KEY)
    if not isinstance(block, dict):
        return empty_block()

    revision = block.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        revision = 0

    version = block.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        version = SCHEMA_VERSION

    values = block.get("values")
    if not isinstance(values, dict):
        values = {}

    return {
        "schema_version": version,
        "revision": revision,
        "values": migrate_retired_placements({k: v for k, v in values.items() if k not in RETIRED_FIELDS}),
    }


def revision_of(config: Dict[str, Any]) -> int:
    return read_block(config)["revision"]


def validate_changes(changes: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(changes, dict):
        raise ValueError("preferences must be sent as an object of field names")
    if not changes:
        raise ValueError("no preference fields were sent")

    known = known_fields()
    typed: Dict[str, Any] = {}
    unknown: Dict[str, Any] = {}

    for name, value in changes.items():
        if not isinstance(name, str) or not name:
            raise ValueError("a preference name must be a non-empty string")
        if is_secret_name(name):
            raise ValueError("that preference name is reserved and cannot be stored")
        if name in RETIRED_FIELDS:
            continue
        if name in known:
            typed[name] = value
        else:
            if len(name) > MAX_KEY_LENGTH:
                raise ValueError("a preference name may be at most 128 characters")
            unknown[name] = value

    if len(unknown) > MAX_UNKNOWN_FIELDS:
        raise ValueError(f"at most {MAX_UNKNOWN_FIELDS} unrecognised preferences at once")

    normalised: Dict[str, Any] = {}
    typed = migrate_retired_placements(typed)
    if typed:
        try:
            model = UiPreferenceValues(**typed)
        except ValidationError as exc:
            raise ValueError(_plain_validation_message(exc)) from exc
        dumped = model.model_dump(mode="json")
        for name in typed:
            normalised[name] = dumped[name]
        _forget_absent_carried(typed, normalised)

    for name, value in unknown.items():
        _refuse_oversized_unknown(name, value)
        normalised[name] = value

    return normalised


_CARRIED_DRAWER_KEYS = ("mobile", "sections")
CARRIED_DRAWER_KEYS = _CARRIED_DRAWER_KEYS


def _forget_absent_carried(typed: Dict[str, Any], normalised: Dict[str, Any]) -> None:
    raw = typed.get("drawer_arrangement")
    value = normalised.get("drawer_arrangement")
    if isinstance(raw, dict) and isinstance(value, dict):
        for key in _CARRIED_DRAWER_KEYS:
            if key not in raw:
                value.pop(key, None)


def _plain_validation_message(exc: ValidationError) -> str:
    parts: List[str] = []
    seen: set = set()
    for error in exc.errors():
        loc = error.get("loc") or ()
        field = str(loc[0]) if loc else "value"
        if field in seen:
            continue
        seen.add(field)
        message = str(error.get("msg") or "invalid value")
        prefix = "Value error, "
        if message.startswith(prefix):
            message = message[len(prefix):]
        parts.append(f"{field}: {message}")
    return "; ".join(parts) if parts else "one or more settings were invalid"


def _refuse_oversized_unknown(name: str, value: Any) -> None:
    import json

    try:
        encoded = json.dumps(value)
    except (TypeError, ValueError):
        raise ValueError(f"preference '{name}' is not a storable value")
    if len(encoded.encode("utf-8")) > MAX_UNKNOWN_VALUE_BYTES:
        raise ValueError(f"preference '{name}' is too large to store")


def apply_changes(
    config: Dict[str, Any], changes: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    block = read_block(config)
    values = dict(block["values"])
    moved: Dict[str, Any] = {}

    for name, value in changes.items():
        if value is None:
            if name in values:
                values.pop(name)
                moved[name] = None
            continue
        value = _carry_absent(values.get(name), name, value)
        if values.get(name, _MISSING) != value:
            values[name] = value
            moved[name] = value

    if not moved:
        return config, block, {}

    new_block = {
        "schema_version": SCHEMA_VERSION,
        "revision": block["revision"] + 1,
        "values": values,
    }
    new_config = dict(config)
    new_config[UI_PREFERENCES_KEY] = new_block
    return new_config, new_block, moved


def _carry_absent(stored: Any, name: str, incoming: Any) -> Any:
    if name != "drawer_arrangement" or not isinstance(incoming, dict) or not isinstance(stored, dict):
        return incoming
    carried = {
        key: stored[key]
        for key in _CARRIED_DRAWER_KEYS
        if key not in incoming and stored.get(key) is not None
    }
    return {**incoming, **carried} if carried else incoming


class _Missing:

    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()
