
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.crate_format.errors import CrateMalformed

STR, INT, BOOL, LIST, DICT, ANY = "str", "int", "bool", "list", "dict", "any"
_SHA = re.compile(r"[0-9a-f]{64}")

MAP_FIELDS: Dict[str, Tuple[str, ...]] = {
    "crate.json": ("counts.rows", "secrets.by_detector", "redaction.findings"),
    "rows/schema.json": ("stores", "stores.*.tables"),
    "secrets.json": ("by_file", "by_file.*", "by_detector"),
}
OPAQUE_FIELDS: Dict[str, Tuple[str, ...]] = {
    "entries.json": ("entries[].value", "entries[].slice[].value"),
}


@dataclass(frozen=True)
class F:

    key: str
    kind: str
    nullable: bool = False


def _kind_ok(value: Any, kind: str) -> bool:
    if kind == ANY:
        return True
    if kind == INT:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, {STR: str, BOOL: bool, LIST: list, DICT: dict}[kind])


def parse_fields(obj: Any, specs: Sequence[F], what: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(obj, dict):
        raise CrateMalformed([f"{what} is not a JSON object"])
    values: Dict[str, Any] = {}
    problems: List[str] = []
    for spec in specs:
        if spec.key not in obj:
            problems.append(f"{what} lacks {spec.key!r}")
            continue
        value = obj[spec.key]
        if value is None and spec.nullable:
            values[spec.key] = None
        elif value is None or not _kind_ok(value, spec.kind):
            problems.append(f"{what} field {spec.key!r} is not {'a nullable ' if spec.nullable else 'a '}{spec.kind}")
        else:
            values[spec.key] = value
    if problems:
        raise CrateMalformed(problems)
    known = {spec.key for spec in specs}
    return values, {k: v for k, v in obj.items() if k not in known}


def check_sha(value: str, what: str) -> str:
    if not _SHA.fullmatch(value):
        raise CrateMalformed([f"{what} is not a sha256 hex digest"])
    return value


def merged(extra: Mapping[str, Any], known: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(extra)
    out.update(known)
    return out


@dataclass(frozen=True)
class MemberRecord:

    name: str
    size: int
    sha256: str
    extra: Dict[str, Any] = field(default_factory=dict, compare=False)

    SPECS = (F("name", STR), F("size", INT), F("sha256", STR))

    @classmethod
    def from_json(cls, obj: Any) -> "MemberRecord":
        values, extra = parse_fields(obj, cls.SPECS, "a member record")
        check_sha(values["sha256"], f"member {values['name']!r} sha256")
        if values["size"] < 0:
            raise CrateMalformed([f"member {values['name']!r} has a negative size"])
        return cls(extra=extra, **values)

    def as_json(self) -> Dict[str, Any]:
        return merged(self.extra, {"name": self.name, "size": self.size, "sha256": self.sha256})


@dataclass(frozen=True)
class HomeRecord:

    kind: str
    index: int
    path: Optional[str]
    extra: Dict[str, Any] = field(default_factory=dict, compare=False)

    SPECS = (F("kind", STR), F("index", INT), F("path", STR, True))

    @classmethod
    def from_json(cls, obj: Any) -> "HomeRecord":
        values, extra = parse_fields(obj, cls.SPECS, "a home record")
        return cls(extra=extra, **values)

    def as_json(self) -> Dict[str, Any]:
        return merged(self.extra, {"kind": self.kind, "index": self.index, "path": self.path})


@dataclass(frozen=True)
class ConversationRecord:

    id: str
    family: str
    title: Optional[str]
    session_uuid: Optional[str]
    working_dir: Optional[str]
    main_rel: Optional[str]
    enc_folder: Optional[str]
    harness_versions: List[str]
    resume: str
    origin: str
    orphan: bool = False
    extra: Dict[str, Any] = field(default_factory=dict, compare=False)

    SPECS = (F("id", STR), F("family", STR), F("title", STR, True), F("session_uuid", STR, True),
             F("working_dir", STR, True), F("main_rel", STR, True), F("enc_folder", STR, True),
             F("harness_versions", LIST), F("resume", STR), F("origin", STR))

    @classmethod
    def from_json(cls, obj: Any) -> "ConversationRecord":
        values, extra = parse_fields(obj, cls.SPECS, "a conversation record")
        orphan = extra.pop("orphan", False)
        if not isinstance(orphan, bool):
            raise CrateMalformed(["a conversation record field 'orphan' is not a bool"])
        if not all(isinstance(v, str) for v in values["harness_versions"]):
            raise CrateMalformed(["a conversation record's harness_versions are not all strings"])
        return cls(orphan=orphan, extra=extra, **values)

    def as_json(self) -> Dict[str, Any]:
        known = {spec.key: getattr(self, spec.key) for spec in self.SPECS}
        if self.orphan:
            known["orphan"] = True
        return merged(self.extra, known)


@dataclass(frozen=True)
class CrateManifest:

    format: str
    format_version: Tuple[int, int]
    variant: str
    byte_exact: bool
    resume: str
    complete: bool
    bundle_id: str
    label: Optional[str]
    created_at: str
    created_epoch: int
    writer: Dict[str, Any]
    source: Dict[str, Any]
    scope: Dict[str, Any]
    homes: List[HomeRecord]
    conversations: List[ConversationRecord]
    members: List[MemberRecord]
    blobs: Dict[str, Any]
    content_id: str
    counts: Dict[str, Any]
    excluded: List[Any]
    warnings: List[Any]
    secrets: Dict[str, Any]
    redaction: Optional[Dict[str, Any]]
    extra: Dict[str, Any] = field(default_factory=dict, compare=False)

    SPECS = (F("format", STR), F("format_version", LIST), F("variant", STR), F("byte_exact", BOOL), F("resume", STR),
             F("complete", BOOL), F("bundle_id", STR), F("label", STR, True), F("created_at", STR),
             F("created_epoch", INT), F("writer", DICT), F("source", DICT), F("scope", DICT), F("homes", LIST),
             F("conversations", LIST), F("members", LIST), F("blobs", DICT), F("content_id", STR), F("counts", DICT),
             F("excluded", LIST), F("warnings", LIST), F("secrets", DICT), F("redaction", DICT, True))
    _NESTED = {"homes": HomeRecord, "conversations": ConversationRecord, "members": MemberRecord}

    @classmethod
    def from_json(cls, obj: Any) -> "CrateManifest":
        values, extra = parse_fields(obj, cls.SPECS, "crate.json")
        for key, record in cls._NESTED.items():
            values[key] = [record.from_json(item) for item in values[key]]
        values["format_version"] = tuple(values["format_version"])
        check_sha(values["content_id"], "content_id")
        blobs, _ = parse_fields(values["blobs"], (F("count", INT), F("set_sha256", STR), F("codecs", LIST)), "blobs")
        check_sha(blobs["set_sha256"], "blobs.set_sha256")
        names = [m.name for m in values["members"]]
        if len(set(names)) != len(names):
            raise CrateMalformed(["crate.json lists a member twice"])
        ids = [c.id for c in values["conversations"]]
        if len(set(ids)) != len(ids):
            raise CrateMalformed(["crate.json lists a conversation twice"])
        return cls(extra=extra, **values)

    def as_json(self) -> Dict[str, Any]:
        known: Dict[str, Any] = {spec.key: getattr(self, spec.key) for spec in self.SPECS}
        known["format_version"] = list(self.format_version)
        for key in self._NESTED:
            known[key] = [item.as_json() for item in known[key]]
        return merged(self.extra, known)

    def conversation(self, conversation_id: str) -> Optional[ConversationRecord]:
        return next((c for c in self.conversations if c.id == conversation_id), None)
