
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

FIELD_KEY_RE = re.compile(r"^[a-z][a-zA-Z0-9_]{0,63}$")

LABEL_KEY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_-]+)+$")

FIELD_KINDS = ("boolean", "number", "enum", "string")

ENUM_CONTROLS = ("segmented", "select")

STRING_MAX_LENGTH = 4096

SETTING_UNKNOWN = "setting_unknown"
SETTING_TYPE = "setting_type"
SETTING_BELOW_MIN = "setting_below_min"
SETTING_ABOVE_MAX = "setting_above_max"
SETTING_NOT_AN_OPTION = "setting_not_an_option"
SETTING_TOO_LONG = "setting_too_long"

VALUE_REFUSALS = (
    SETTING_UNKNOWN,
    SETTING_TYPE,
    SETTING_BELOW_MIN,
    SETTING_ABOVE_MAX,
    SETTING_NOT_AN_OPTION,
    SETTING_TOO_LONG,
)


class SettingsSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class SettingsSchema:

    version: int
    fields: Mapping[str, Mapping[str, Any]]
    groups: Optional[Tuple[Mapping[str, Any], ...]] = None

    def as_wire(self) -> Dict[str, Any]:
        wire: Dict[str, Any] = {"version": self.version, "fields": {k: dict(v) for k, v in self.fields.items()}}
        if self.groups is not None:
            wire["groups"] = [_group_wire(g) for g in self.groups]
        return wire


def _group_wire(group: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"labelKey": group["labelKey"], "fields": list(group["fields"])}
    if "matrix" in group:
        matrix = group["matrix"]
        out["matrix"] = {"columns": list(matrix["columns"]), "rows": [dict(r) for r in matrix["rows"]]}
    return out


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_field(key: str, field: Any) -> None:
    where = f"settings.fields.{key}"
    if not FIELD_KEY_RE.match(key):
        raise SettingsSchemaError(f"{where}: key must be letters, digits and underscores, starting with a lowercase letter")
    if not isinstance(field, dict):
        raise SettingsSchemaError(f"{where} must be an object")
    label = field.get("labelKey")
    if not isinstance(label, str) or not LABEL_KEY_RE.match(label):
        raise SettingsSchemaError(f"{where}.labelKey must be a catalog key")
    kind = field.get("kind")
    if kind not in FIELD_KINDS:
        raise SettingsSchemaError(f"{where}.kind is not boolean, number, enum or string")
    allowed = {"kind", "labelKey", "default", "hintKey", "keywordsKey"} | {
        "boolean": set(), "number": {"min", "max"}, "enum": {"options", "control"}, "string": {"maxLength"},
    }[kind]
    extra = set(field) - allowed
    if extra:
        raise SettingsSchemaError(f"{where} carries an unknown field: {sorted(extra)[0]}")
    hint = field.get("hintKey")
    if "hintKey" in field and (not isinstance(hint, str) or not LABEL_KEY_RE.match(hint)):
        raise SettingsSchemaError(f"{where}.hintKey must be a catalog key")
    keywords = field.get("keywordsKey")
    if "keywordsKey" in field and (not isinstance(keywords, str) or not LABEL_KEY_RE.match(keywords)):
        raise SettingsSchemaError(f"{where}.keywordsKey must be a catalog key")
    if "control" in field and field["control"] not in ENUM_CONTROLS:
        raise SettingsSchemaError(f"{where}.control is not segmented or select")
    for bound in ("min", "max"):
        if bound in field and not _is_number(field[bound]):
            raise SettingsSchemaError(f"{where}.{bound} must be a number")
    if kind == "enum":
        options = field.get("options")
        if (not isinstance(options, list) or not options
                or not all(isinstance(o, str) for o in options)):
            raise SettingsSchemaError(f"{where}.options must be a non-empty list of words")
        if len(set(options)) != len(options):
            raise SettingsSchemaError(f"{where}.options repeats a value")
    if kind == "string":
        cap = field.get("maxLength")
        if not isinstance(cap, int) or isinstance(cap, bool) or not 0 < cap <= STRING_MAX_LENGTH:
            raise SettingsSchemaError(f"{where}.maxLength must be a whole number from 1 to {STRING_MAX_LENGTH}")
    if "default" not in field or check_value(field, field["default"]) is not None:
        raise SettingsSchemaError(f"{where}.default does not satisfy its own field")


def parse_schema(raw: Any) -> SettingsSchema:
    if not isinstance(raw, dict) or set(raw) - {"version", "fields", "groups"}:
        raise SettingsSchemaError("settings must be an object with version, fields and groups only")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SettingsSchemaError("settings.version must be a whole number from 1")
    fields = raw.get("fields")
    if not isinstance(fields, dict):
        raise SettingsSchemaError("settings.fields must be an object")
    for key, field in fields.items():
        _check_field(key, field)
    groups = _check_groups(raw["groups"], fields) if "groups" in raw else None
    return SettingsSchema(version=version, fields={k: dict(v) for k, v in fields.items()}, groups=groups)


def _check_groups(raw: Any, fields: Mapping[str, Any]) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(raw, list) or not raw:
        raise SettingsSchemaError("settings.groups must be a non-empty list")
    seen: List[str] = []
    out: List[Mapping[str, Any]] = []
    for at, group in enumerate(raw):
        where = f"settings.groups[{at}]"
        if not isinstance(group, dict) or not {"labelKey", "fields"} <= set(group) or set(group) - {"labelKey", "fields", "matrix"}:
            raise SettingsSchemaError(f"{where} must be an object with labelKey, fields and an optional matrix only")
        label = group["labelKey"]
        if not isinstance(label, str) or not LABEL_KEY_RE.match(label):
            raise SettingsSchemaError(f"{where}.labelKey must be a catalog key")
        keys = group["fields"]
        if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and k in fields for k in keys):
            raise SettingsSchemaError(f"{where}.fields must list declared fields")
        seen.extend(keys)
        checked: Dict[str, Any] = {"labelKey": label, "fields": list(keys)}
        if "matrix" in group:
            checked["matrix"] = _check_matrix(group["matrix"], keys, fields, where)
        out.append(checked)
    if len(seen) != len(set(seen)) or set(seen) != set(fields):
        raise SettingsSchemaError("settings.groups must name every field exactly once")
    return tuple(out)


def _check_matrix(raw: Any, keys: List[str], fields: Mapping[str, Any], where: str) -> Dict[str, Any]:
    at = f"{where}.matrix"
    if not isinstance(raw, dict) or set(raw) != {"columns", "rows"}:
        raise SettingsSchemaError(f"{at} must be an object with columns and rows only")
    columns = raw["columns"]
    if (not isinstance(columns, list) or len(columns) < 2
            or not all(isinstance(c, str) and LABEL_KEY_RE.match(c) for c in columns)):
        raise SettingsSchemaError(f"{at}.columns must be at least two catalog keys")
    rows = raw["rows"]
    if not isinstance(rows, list) or not rows:
        raise SettingsSchemaError(f"{at}.rows must be a non-empty list")
    cells: List[str] = []
    out: List[Dict[str, Any]] = []
    for n, row in enumerate(rows):
        here = f"{at}.rows[{n}]"
        if not isinstance(row, dict) or "labelKey" not in row:
            raise SettingsSchemaError(f"{here} must be an object with a labelKey")
        locked = row.get("locked") is True
        allowed = {"labelKey", "hintKey", "locked"} if locked else {"labelKey", "hintKey", "fields", "confirm"}
        if set(row) - allowed or ("locked" in row and not locked):
            raise SettingsSchemaError(f"{here} is a locked row (labelKey, hintKey, locked: true) or a row of cells (labelKey, hintKey, fields, "
                                      "confirm)")
        for name in ("labelKey", "hintKey"):
            if name in row and (not isinstance(row[name], str) or not LABEL_KEY_RE.match(row[name])):
                raise SettingsSchemaError(f"{here}.{name} must be a catalog key")
        if not locked:
            cell_keys = row.get("fields")
            if (not isinstance(cell_keys, list) or len(cell_keys) != len(columns)
                    or not all(isinstance(k, str) and k in keys and fields[k].get("kind") == "boolean" for k in cell_keys)):
                raise SettingsSchemaError(f"{here}.fields must name one boolean field of this group per column")
            cells.extend(cell_keys)
            confirm = row.get("confirm", {})
            if (not isinstance(confirm, dict) or ("confirm" in row and not confirm)
                    or not all(k in cell_keys and isinstance(v, str) and LABEL_KEY_RE.match(v) for k, v in confirm.items())):
                raise SettingsSchemaError(f"{here}.confirm must map cells of this row to catalog keys")
        out.append({**row, "confirm": dict(row["confirm"])} if "confirm" in row else dict(row))
    if cells != list(keys):
        raise SettingsSchemaError(f"{at}.rows must name the group's fields exactly once, in order")
    return {"columns": list(columns), "rows": out}


def check_value(field: Mapping[str, Any], value: Any) -> Optional[str]:
    kind = field.get("kind")
    if kind == "boolean":
        return None if isinstance(value, bool) else SETTING_TYPE
    if kind == "number":
        if not _is_number(value):
            return SETTING_TYPE
        if "min" in field and value < field["min"]:
            return SETTING_BELOW_MIN
        if "max" in field and value > field["max"]:
            return SETTING_ABOVE_MAX
        return None
    if kind == "enum":
        if not isinstance(value, str):
            return SETTING_TYPE
        return None if value in field.get("options", ()) else SETTING_NOT_AN_OPTION
    if kind == "string":
        if not isinstance(value, str):
            return SETTING_TYPE
        return None if len(value) <= field.get("maxLength", 0) else SETTING_TOO_LONG
    return SETTING_TYPE


def check_key(schema: Optional[SettingsSchema], key: str, value: Any) -> Optional[str]:
    field = schema.fields.get(key) if schema is not None else None
    if field is None:
        return SETTING_UNKNOWN
    return check_value(field, value)


Migration = Callable[[Dict[str, Any]], Dict[str, Any]]

MIGRATIONS: Dict[Tuple[str, str, int], Migration] = {}


def migrate(
    kind: str, item_id: str, stored_version: Optional[int], schema: Optional[SettingsSchema],
    values: Mapping[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    current = dict(values)
    if schema is not None and stored_version is not None:
        version = stored_version
        while version < schema.version:
            step = MIGRATIONS.get((kind, item_id, version))
            if step is not None:
                current = dict(step(dict(current)))
            version += 1
    kept: Dict[str, Any] = {}
    dropped: List[str] = []
    for key, value in current.items():
        if check_key(schema, key, value) is None:
            kept[key] = value
        else:
            dropped.append(key)
    return kept, sorted(dropped)
