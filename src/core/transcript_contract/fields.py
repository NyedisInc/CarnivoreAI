
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Type, TypeVar

STR: Tuple[str, ...] = ("string",)
INT: Tuple[str, ...] = ("integer",)
NUM: Tuple[str, ...] = ("number",)
BOOL: Tuple[str, ...] = ("boolean",)
OBJ: Tuple[str, ...] = ("object",)
ARR: Tuple[str, ...] = ("array",)
NULL: Tuple[str, ...] = ("null",)
ANY: Tuple[str, ...] = ()

SPEC_KEY: str = "transcript_contract"

UNKNOWN_TYPE = "unknown_type"
EXTRA_KEY = "extra_key"
TYPE_MISMATCH = "type_mismatch"
MISSING_REQUIRED = "missing_required"

_SAFE_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-:.<>]{0,63}$")

NON_TOKEN: str = "<non-token>"

Nested = Callable[[Any, str, "Report"], Any]
"""A nested parser: (value, path prefix, report) -> typed value."""


_EXACT_JSON_TYPES: Dict[type, str] = {
    type(None): "null", bool: "boolean", int: "integer", float: "number", str: "string",
    list: "array", dict: "object",
}


def json_type(value: Any) -> str:
    name = _EXACT_JSON_TYPES.get(type(value))
    if name is not None:
        return name
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def safe_token(value: Any) -> str:
    if isinstance(value, str) and _SAFE_TOKEN.match(value):
        return value
    return NON_TOKEN


@dataclass(frozen=True)
class FieldSpec:

    json: str
    types: Tuple[str, ...]
    required: bool = False
    first_seen: Optional[str] = None
    nested: Optional[Nested] = None


def jf(json_name: str, types: Tuple[str, ...], *, required: bool = False,
       first_seen: Optional[str] = None, nested: Optional[Nested] = None) -> Any:
    spec = FieldSpec(json_name, types, required, first_seen, nested)
    return field(default=None, metadata={SPEC_KEY: spec})


@dataclass(frozen=True)
class Finding:

    kind: str
    path: str
    detail: str = ""

    def key(self) -> str:
        return f"{self.kind}:{self.path}" + (f":{self.detail}" if self.detail else "")


class Report:

    def __init__(self) -> None:
        self.findings: List[Finding] = []

    def add(self, kind: str, path: str, detail: str = "") -> None:
        self.findings.append(Finding(kind, path, detail))


T = TypeVar("T")

_SPEC_CACHE: Dict[type, Tuple[Tuple[str, FieldSpec], ...]] = {}


def specs_of(cls: type) -> Tuple[Tuple[str, FieldSpec], ...]:
    cached = _SPEC_CACHE.get(cls)
    if cached is None:
        cached = tuple((f.name, f.metadata[SPEC_KEY]) for f in fields(cls) if SPEC_KEY in f.metadata)
        _SPEC_CACHE[cls] = cached
    return cached


_KEYS_CACHE: Dict[type, frozenset] = {}


def declared_keys(cls: type) -> frozenset:
    cached = _KEYS_CACHE.get(cls)
    if cached is None:
        cached = frozenset(spec.json for _name, spec in specs_of(cls))
        _KEYS_CACHE[cls] = cached
    return cached


def bind(cls: Type[T], obj: Mapping[str, Any], path: str, report: Report,
         *, ignore: frozenset = frozenset(), **extra_kwargs: Any) -> T:
    kwargs: Dict[str, Any] = dict(extra_kwargs)
    specs = specs_of(cls)
    for attr, spec in specs:
        where = path + spec.json
        if spec.json not in obj:
            if spec.required:
                report.add(MISSING_REQUIRED, where)
            continue
        value = obj[spec.json]
        kind = _EXACT_JSON_TYPES.get(type(value)) or json_type(value)
        if spec.types and kind not in spec.types:
            report.add(TYPE_MISMATCH, where, kind)
            continue
        if spec.nested is not None and value is not None:
            value = spec.nested(value, where + ".", report)
        kwargs[attr] = value
    known = declared_keys(cls)
    for key in obj:
        if key not in known and key not in ignore:
            report.add(EXTRA_KEY, path + safe_token(key))
    return cls(**kwargs)


def field_table(cls: type) -> List[Dict[str, Any]]:
    rows = []
    for attr, spec in specs_of(cls):
        rows.append({"attr": attr, "json": spec.json, "types": list(spec.types) or ["any"],
                     "required": spec.required, "first_seen": spec.first_seen})
    return rows

