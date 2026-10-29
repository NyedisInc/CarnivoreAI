
from __future__ import annotations

import re
from typing import Any

DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

STATUSES = ("stable", "beta", "deprecated", "removed")
CHANGE_TYPES = ("added", "changed", "fixed", "removed", "deprecated", "security", "internal")
MEDIA_KINDS = ("screenshot", "gif", "icon")
MEDIA_FILE_PATTERN = r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9_-]+)*\.(png|gif|svg|webp)$"

MEDIA_ITEM_FIELDS: dict[str, dict[str, Any]] = {
    "kind": {"type": "string", "required": True, "enum": MEDIA_KINDS},
    "file": {"type": "string", "required": True, "pattern": MEDIA_FILE_PATTERN},
    "caption": {"type": "string", "required": True, "min_length": 1},
    "alt": {"type": "string", "required": True, "min_length": 1},
    "theme": {"type": "string", "required": False},
    "state": {"type": "string", "required": False},
}

AREA_FIELDS: dict[str, dict[str, Any]] = {
    "id": {"type": "string", "required": True, "pattern": ID_PATTERN},
    "name": {"type": "string", "required": True},
    "blurb": {"type": "string", "required": True},
}
CATALOG_FIELDS: dict[str, dict[str, Any]] = {
    "id": {"type": "string", "required": True, "pattern": ID_PATTERN},
    "name": {"type": "string", "required": True},
    "summary": {"type": "string", "required": True},
    "description": {"type": "string", "required": False},
    "area": {"type": "string", "required": True},
    "status": {"type": "string", "required": True, "enum": STATUSES},
    "since": {"type": "string", "required": True, "format": "date"},
    "updated": {"type": "string", "required": True, "format": "date"},
    "surfaces": {"type": "array", "items": "string", "required": False},
    "api_routes": {"type": "array", "items": "string", "required": False},
    "docs": {"type": "array", "items": "string", "required": False},
    "issues": {"type": "array", "items": "integer", "required": False},
    "keywords": {"type": "array", "items": "string", "required": False},
    "where": {"type": "array", "items": "string", "required": False},
    "how_to": {"type": "array", "items": "string", "required": False},
    "examples": {"type": "array", "items": "string", "required": False},
    "media": {"type": "array", "items": "object", "item_fields": MEDIA_ITEM_FIELDS, "required": False},
    "media_exempt": {"type": "string", "required": False, "min_length": 1},
}
CHANGE_FIELDS: dict[str, dict[str, Any]] = {
    "date": {"type": "string", "required": True, "format": "date"},
    "type": {"type": "string", "required": True, "enum": CHANGE_TYPES},
    "features": {"type": "array", "items": "string", "required": True},
    "summary": {"type": "string", "required": True},
    "details": {"type": "string", "required": False},
    "issue": {"type": "integer", "required": False},
    "pr": {"type": "integer", "required": False},
    "breaking": {"type": "boolean", "required": False},
    "release": {"type": "string", "required": False},
    "landed_at": {"type": "string", "required": False},
    "media_unchanged": {"type": "boolean", "required": False},
}


def validate_record(record: dict, spec: dict[str, dict[str, Any]], where: str) -> list[str]:
    errors: list[str] = []
    for name, rule in spec.items():
        if name not in record:
            if rule.get("required"):
                errors.append(f"{where}: missing required field '{name}'")
            continue
        errors.extend(_check_field(where, name, record[name], rule))
    unknown = sorted(set(record) - set(spec))
    errors.extend(f"{where}: unknown field '{name}'" for name in unknown)
    return errors


def _check_field(where: str, name: str, value: Any, rule: dict[str, Any]) -> list[str]:
    kind = rule["type"]
    if kind == "string":
        if not isinstance(value, str):
            return [f"{where}: field '{name}' must be a string, got {type(value).__name__}"]
        errors = []
        if rule.get("format") == "date" and not DATE_RX.match(value):
            errors.append(f"{where}: field '{name}' must be YYYY-MM-DD, got {value!r}")
        if rule.get("pattern") and not re.match(rule["pattern"], value):
            errors.append(f"{where}: field '{name}' does not match {rule['pattern']!r}: {value!r}")
        if rule.get("enum") and value not in rule["enum"]:
            errors.append(f"{where}: field '{name}' must be one of {rule['enum']}, got {value!r}")
        if rule.get("min_length") and len(value.strip()) < rule["min_length"]:
            errors.append(f"{where}: field '{name}' must not be empty")
        return errors
    if kind == "array":
        if not isinstance(value, list):
            return [f"{where}: field '{name}' must be an array"]
        item_kind = rule.get("items", "string")
        errors = []
        if item_kind == "object":
            for i, item in enumerate(value):
                if not isinstance(item, dict):
                    errors.append(f"{where}: field '{name}[{i}]' must be an object")
                else:
                    errors.extend(validate_record(item, rule["item_fields"], f"{where}: {name}[{i}]"))
            return errors
        for i, item in enumerate(value):
            ok = (item_kind == "string" and isinstance(item, str)) or (
                item_kind == "integer" and isinstance(item, int) and not isinstance(item, bool)
            )
            if not ok:
                errors.append(f"{where}: field '{name}[{i}]' must be a {item_kind}")
        return errors
    if kind == "boolean" and not isinstance(value, bool):
        return [f"{where}: field '{name}' must be a boolean"]
    if kind == "integer" and value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        return [f"{where}: field '{name}' must be an integer, got {type(value).__name__}"]
    return []


def _field_schema(rule: dict[str, Any]) -> dict[str, Any]:
    kind = rule["type"]
    if kind == "string":
        schema: dict[str, Any] = {"type": "string"}
        if rule.get("format") == "date":
            schema["format"] = "date"
        if rule.get("pattern"):
            schema["pattern"] = rule["pattern"]
        if rule.get("enum"):
            schema["enum"] = list(rule["enum"])
        if rule.get("min_length"):
            schema["minLength"] = rule["min_length"]
        return schema
    if kind == "array":
        if rule.get("items") == "object":
            return {"type": "array", "items": spec_to_json_schema(rule["item_fields"], "Media item")}
        return {"type": "array", "items": {"type": rule.get("items", "string")}}
    if kind == "integer":
        return {"type": "integer"}
    return {"type": "boolean"}


def spec_to_json_schema(spec: dict[str, dict[str, Any]], title: str) -> dict[str, Any]:
    required = sorted(name for name, rule in spec.items() if rule.get("required"))
    return {
        "type": "object",
        "title": title,
        "properties": {name: _field_schema(rule) for name, rule in spec.items()},
        "required": required,
        "additionalProperties": False,
    }


def build_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://carnivore.ai/schemas/features.json",
        "title": "Cloude Code feature catalog",
        "$defs": {
            "area": spec_to_json_schema(AREA_FIELDS, "Area"),
            "catalogEntry": spec_to_json_schema(CATALOG_FIELDS, "Catalog entry"),
            "changeEntry": spec_to_json_schema(CHANGE_FIELDS, "Change entry"),
        },
    }
