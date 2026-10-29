
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core.blobcodec.chunking import ChunkRef
from src.core.crate_format.constants import MAX_CHUNK_LENGTH
from src.core.crate_format.errors import CrateMalformed
from src.core.crate_format.model import ANY, BOOL, DICT, INT, LIST, STR, F, check_sha, merged, parse_fields
from src.core.crate_format.names import check_rel, check_token


def parse_chunks(rows: Any, what: str) -> Tuple[ChunkRef, ...]:
    refs = []
    for row in rows:
        if (not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
                or not isinstance(row[1], int) or isinstance(row[1], bool)):
            raise CrateMalformed([f"{what} has a chunk that is not [sha256, length]"])
        check_sha(row[0], f"{what} chunk")
        if not 0 < row[1] <= MAX_CHUNK_LENGTH:
            raise CrateMalformed([f"{what} has a chunk length outside 1..{MAX_CHUNK_LENGTH}"])
        refs.append(ChunkRef(row[0], row[1]))
    return tuple(refs)


@dataclass(frozen=True)
class FileRecord:

    role: str
    home: str
    home_index: int
    rel: str
    source_path: Optional[str]
    conversation_id: Optional[str]
    family: Optional[str]
    enc_folder: Optional[str]
    length: int
    content_sha256: str
    chain_sha256: str
    chunks: Tuple[ChunkRef, ...]
    line_mode: bool
    lines: Optional[int]
    ends_with_newline: bool
    mode: int
    mtime_ns: Optional[int]
    origin: str
    vault_signature: Any
    redactions: Any
    extra: Dict[str, Any] = field(default_factory=dict, compare=False)

    SPECS = (F("role", STR), F("home", STR), F("home_index", INT), F("rel", STR), F("source_path", STR, True),
             F("conversation_id", STR, True), F("family", STR, True), F("enc_folder", STR, True), F("length", INT),
             F("content_sha256", STR), F("chain_sha256", STR), F("chunks", LIST), F("line_mode", BOOL),
             F("lines", INT, True), F("ends_with_newline", BOOL), F("mode", INT), F("mtime_ns", INT, True),
             F("origin", STR), F("vault_signature", ANY, True), F("redactions", ANY, True))

    @classmethod
    def from_json(cls, obj: Any) -> "FileRecord":
        values, extra = parse_fields(obj, cls.SPECS, "a files.jsonl record")
        check_rel(values["rel"])
        check_token(values["home"], "home kind")
        check_token(values["role"], "role")
        if values["home_index"] < 0 or values["length"] < 0:
            raise CrateMalformed([f"file {values['rel']!r} has a negative index or length"])
        check_sha(values["content_sha256"], f"file {values['rel']!r} content_sha256")
        check_sha(values["chain_sha256"], f"file {values['rel']!r} chain_sha256")
        values["chunks"] = parse_chunks(values["chunks"], f"file {values['rel']!r}")
        return cls(extra=extra, **values)

    def as_json(self) -> Dict[str, Any]:
        known = {spec.key: getattr(self, spec.key) for spec in self.SPECS}
        known["chunks"] = [[c.sha256, c.length] for c in self.chunks]
        return merged(self.extra, known)

    @property
    def sort_key(self) -> Tuple[str, int, str]:
        return (self.home, self.home_index, self.rel)

    @property
    def place(self) -> str:
        return f"{self.home}{'' if self.home_index == 0 else f'-{self.home_index}'}/{self.rel}"


@dataclass(frozen=True)
class LinesRecord:

    source: str
    home_index: int
    name: str

    @classmethod
    def from_name(cls, name: str) -> "LinesRecord":
        stem = name[len("lines/"):-len(".jsonl")]
        source, _, index = stem.rpartition("-")
        return cls(source, int(index), name)


@dataclass(frozen=True)
class TableRecord:

    store: str
    table: str
    inventory_label: str
    schema_version: Optional[int]
    columns: List[List[Any]]
    rows: int
    parts: List[str]
    omitted_columns: List[str]
    without_rowid: bool
    keys: List[str]
    paths: List[str]
    extra: Dict[str, Any] = field(default_factory=dict, compare=False)

    SPECS = (F("columns", LIST), F("rows", INT), F("parts", LIST), F("omitted_columns", LIST),
             F("without_rowid", BOOL), F("keys", LIST), F("paths", LIST))

    def as_json(self) -> Dict[str, Any]:
        return merged(self.extra, {spec.key: getattr(self, spec.key) for spec in self.SPECS})


def parse_schema(obj: Any) -> Dict[str, Dict[str, TableRecord]]:
    top, _ = parse_fields(obj, (F("stores", DICT),), "rows/schema.json")
    out: Dict[str, Dict[str, TableRecord]] = {}
    for store, body in top["stores"].items():
        head, _ = parse_fields(body, (F("inventory_label", STR), F("schema_version", INT, True), F("tables", DICT)),
                               f"store {store!r}")
        tables: Dict[str, TableRecord] = {}
        for table, spec in head["tables"].items():
            values, extra = parse_fields(spec, TableRecord.SPECS, f"table {store}.{table}")
            if values["rows"] < 0 or not all(isinstance(p, str) for p in values["parts"]):
                raise CrateMalformed([f"table {store}.{table} has a bad row count or part list"])
            tables[table] = TableRecord(store=store, table=table, inventory_label=head["inventory_label"],
                                        schema_version=head["schema_version"], extra=extra, **values)
        out[store] = tables
    return out


def schema_json(tables: Dict[str, Dict[str, TableRecord]]) -> Dict[str, Any]:
    stores: Dict[str, Any] = {}
    for store, by_name in tables.items():
        first = next(iter(by_name.values()), None)
        stores[store] = {"inventory_label": first.inventory_label if first else store,
                         "schema_version": first.schema_version if first else None,
                         "tables": {name: rec.as_json() for name, rec in by_name.items()}}
    return {"stores": stores}
