
from __future__ import annotations

import math
import re
from typing import Any, List, Mapping, Optional

FIELD_KEY_RE = re.compile(r"^[a-z][a-zA-Z0-9_]{0,63}$")
LABEL_KEY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_-]+)+$")
FIELD_KINDS = ("boolean", "number", "enum", "string")
ENUM_CONTROLS = ("segmented", "select")
STRING_MAX_LENGTH = 4096


class SettingsSchemaFallbackError(ValueError):
    pass


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_value(field: Mapping[str, Any], value: Any) -> Optional[str]:
    kind = field.get("kind")
    if kind == "boolean":
        return None if isinstance(value, bool) else "setting_type"
    if kind == "number":
        if not _is_number(value):
            return "setting_type"
        if "min" in field and value < field["min"]:
            return "setting_below_min"
        if "max" in field and value > field["max"]:
            return "setting_above_max"
        return None
    if kind == "enum":
        if not isinstance(value, str):
            return "setting_type"
        return None if value in field.get("options", ()) else "setting_not_an_option"
    if kind == "string":
        if not isinstance(value, str):
            return "setting_type"
        return None if len(value) <= field.get("maxLength", 0) else "setting_too_long"
    return "setting_type"


def _check_field(key: Any, field: Any) -> None:
    where = f"settings.fields.{key}"
    if not isinstance(key, str) or not FIELD_KEY_RE.match(key):
        raise SettingsSchemaFallbackError(
            f"{where}: key must be letters, digits and underscores, starting with a lowercase letter"
        )
    if not isinstance(field, dict):
        raise SettingsSchemaFallbackError(f"{where} must be an object")
    label = field.get("labelKey")
    if not isinstance(label, str) or not LABEL_KEY_RE.match(label):
        raise SettingsSchemaFallbackError(f"{where}.labelKey must be a catalog key")
    kind = field.get("kind")
    if kind not in FIELD_KINDS:
        raise SettingsSchemaFallbackError(f"{where}.kind is not boolean, number, enum or string")
    allowed = {"kind", "labelKey", "default", "hintKey", "keywordsKey", "hidden"} | {
        "boolean": set(),
        "number": {"min", "max"},
        "enum": {"options", "control"},
        "string": {"maxLength"},
    }[kind]
    extra = set(field) - allowed
    if extra:
        raise SettingsSchemaFallbackError(f"{where} carries an unknown field: {sorted(extra)[0]}")
    if "hidden" in field and not isinstance(field["hidden"], bool):
        raise SettingsSchemaFallbackError(f"{where}.hidden must be true or false")
    hint = field.get("hintKey")
    if "hintKey" in field and (not isinstance(hint, str) or not LABEL_KEY_RE.match(hint)):
        raise SettingsSchemaFallbackError(f"{where}.hintKey must be a catalog key")
    keywords = field.get("keywordsKey")
    if "keywordsKey" in field and (not isinstance(keywords, str) or not LABEL_KEY_RE.match(keywords)):
        raise SettingsSchemaFallbackError(f"{where}.keywordsKey must be a catalog key")
    if "control" in field and field["control"] not in ENUM_CONTROLS:
        raise SettingsSchemaFallbackError(f"{where}.control is not segmented or select")
    for bound in ("min", "max"):
        if bound in field and not _is_number(field[bound]):
            raise SettingsSchemaFallbackError(f"{where}.{bound} must be a number")
    if kind == "enum":
        options = field.get("options")
        if not isinstance(options, list) or not options or not all(isinstance(o, str) for o in options):
            raise SettingsSchemaFallbackError(f"{where}.options must be a non-empty list of words")
        if len(set(options)) != len(options):
            raise SettingsSchemaFallbackError(f"{where}.options repeats a value")
    if kind == "string":
        cap = field.get("maxLength")
        if not isinstance(cap, int) or isinstance(cap, bool) or not 0 < cap <= STRING_MAX_LENGTH:
            raise SettingsSchemaFallbackError(
                f"{where}.maxLength must be a whole number from 1 to {STRING_MAX_LENGTH}"
            )
    if "default" not in field or check_value(field, field["default"]) is not None:
        raise SettingsSchemaFallbackError(f"{where}.default does not satisfy its own field")


def _check_matrix(raw: Any, keys: List[str], fields: Mapping[str, Any], where: str) -> None:
    at = f"{where}.matrix"
    if not isinstance(raw, dict) or set(raw) != {"columns", "rows"}:
        raise SettingsSchemaFallbackError(f"{at} must be an object with columns and rows only")
    columns = raw["columns"]
    if (
        not isinstance(columns, list)
        or len(columns) < 2
        or not all(isinstance(c, str) and LABEL_KEY_RE.match(c) for c in columns)
    ):
        raise SettingsSchemaFallbackError(f"{at}.columns must be at least two catalog keys")
    rows = raw["rows"]
    if not isinstance(rows, list) or not rows:
        raise SettingsSchemaFallbackError(f"{at}.rows must be a non-empty list")
    cells: List[str] = []
    for n, row in enumerate(rows):
        here = f"{at}.rows[{n}]"
        if not isinstance(row, dict) or "labelKey" not in row:
            raise SettingsSchemaFallbackError(f"{here} must be an object with a labelKey")
        locked = row.get("locked") is True
        allowed = {"labelKey", "hintKey", "locked"} if locked else {"labelKey", "hintKey", "fields", "confirm"}
        if set(row) - allowed or ("locked" in row and not locked):
            raise SettingsSchemaFallbackError(
                f"{here} is a locked row (labelKey, hintKey, locked: true) or a row of cells (labelKey, hintKey, fields, confirm)"
            )
        for name in ("labelKey", "hintKey"):
            if name in row and (not isinstance(row[name], str) or not LABEL_KEY_RE.match(row[name])):
                raise SettingsSchemaFallbackError(f"{here}.{name} must be a catalog key")
        if not locked:
            cell_keys = row.get("fields")
            if (
                not isinstance(cell_keys, list)
                or len(cell_keys) != len(columns)
                or not all(
                    isinstance(k, str) and k in keys and fields[k].get("kind") == "boolean"
                    for k in cell_keys
                )
            ):
                raise SettingsSchemaFallbackError(f"{here}.fields must name one boolean field of this group per column")
            cells.extend(cell_keys)
            confirm = row.get("confirm", {})
            if (
                not isinstance(confirm, dict)
                or ("confirm" in row and not confirm)
                or not all(
                    k in cell_keys and isinstance(v, str) and LABEL_KEY_RE.match(v)
                    for k, v in confirm.items()
                )
            ):
                raise SettingsSchemaFallbackError(f"{here}.confirm must map cells of this row to catalog keys")
    if cells != list(keys):
        raise SettingsSchemaFallbackError(f"{at}.rows must name the group's fields exactly once, in order")


def _check_groups(raw: Any, fields: Mapping[str, Any]) -> None:
    if not isinstance(raw, list) or not raw:
        raise SettingsSchemaFallbackError("settings.groups must be a non-empty list")
    seen: List[str] = []
    for at, group in enumerate(raw):
        where = f"settings.groups[{at}]"
        if (
            not isinstance(group, dict)
            or not {"labelKey", "fields"} <= set(group)
            or set(group) - {"labelKey", "fields", "matrix"}
        ):
            raise SettingsSchemaFallbackError(
                f"{where} must be an object with labelKey, fields and an optional matrix only"
            )
        label = group["labelKey"]
        if not isinstance(label, str) or not LABEL_KEY_RE.match(label):
            raise SettingsSchemaFallbackError(f"{where}.labelKey must be a catalog key")
        keys = group["fields"]
        if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and k in fields for k in keys):
            raise SettingsSchemaFallbackError(f"{where}.fields must list declared fields")
        seen.extend(keys)
        if "matrix" in group:
            _check_matrix(group["matrix"], keys, fields, where)
    if len(seen) != len(set(seen)) or set(seen) != set(fields):
        raise SettingsSchemaFallbackError("settings.groups must name every field exactly once")


def parse_schema_fallback(raw: Any) -> None:
    if not isinstance(raw, dict) or set(raw) - {"version", "fields", "groups"}:
        raise SettingsSchemaFallbackError("settings must be an object with version, fields and groups only")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SettingsSchemaFallbackError("settings.version must be a whole number from 1")
    fields = raw.get("fields")
    if not isinstance(fields, dict):
        raise SettingsSchemaFallbackError("settings.fields must be an object")
    for key, field in fields.items():
        _check_field(key, field)
    if "groups" in raw:
        _check_groups(raw["groups"], fields)
