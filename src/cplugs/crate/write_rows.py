
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate.handle import JobHandle
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs

MAIN_NAME = "carnivore.db"


def crate_store(label: str) -> str:
    return MAIN_NAME if label == cs.MAIN_STORE else label


@dataclass
class RowsOut:

    tables: Dict[str, Dict[str, cf.TableRecord]] = field(default_factory=dict)
    paths: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[Tuple[str, str], int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def _json_values(value: Any, steps: List[str]) -> Iterator[Any]:
    if not steps:
        yield value
        return
    step, rest = steps[0], steps[1:]
    many = step.endswith("[]")
    key = step[:-2] if many else step
    inner = value.get(key) if isinstance(value, dict) else None
    if many:
        for item in inner if isinstance(inner, list) else []:
            yield from _json_values(item, rest)
    elif inner is not None:
        yield from _json_values(inner, rest)


def path_records(store: str, table: str, row: Dict[str, Any], pk: List[str], keys: List[str], fields: List[str],
                 warnings: List[str]) -> List[Dict[str, Any]]:
    key = {c: cf.canonical.encode_value(row.get(c)) for c in (pk or [k for k in keys if k in row])}
    out: List[Dict[str, Any]] = []
    for spec in fields:
        column, _, json_path = spec.partition("#")
        if column not in row:
            continue
        base = {"store": store, "table": table, "column": column, "json_path": json_path or None, "key": key}
        value = row[column]
        if not json_path:
            out.append({**base, "value": cf.canonical.encode_value(value)})
            continue
        if value is None:
            continue
        try:
            parsed = json.loads(value) if isinstance(value, (str, bytes)) else None
        except ValueError:
            parsed = None
        if parsed is None:
            out.append({**base, "value": None})
            warnings.append(f"{K.W_PATH_JSON}: {store} {table}.{column} holds JSON that does not parse")
            continue
        out += [{**base, "value": v} for v in _json_values(parsed, json_path.split("."))
                if isinstance(v, (str, int, float)) or v is None]
    return out


class _Parts:

    def __init__(self, sink: Any, store: str, table: str) -> None:
        self.sink, self.store, self.table = sink, store, table
        self.buf = bytearray()
        self.names: List[str] = []

    def _name(self, index: Optional[int]) -> str:
        suffix = "" if index is None else f".{index:04d}"
        return f"rows/{self.store}/{self.table}{suffix}.jsonl"

    def add(self, line: bytes) -> int:
        self.buf += line
        if len(self.buf) <= cf.constants.ROWS_PART_BYTES:
            return 0
        return self._flush(len(self.names))

    def _flush(self, index: Optional[int]) -> int:
        data, self.buf = bytes(self.buf), bytearray()
        self.sink.add_member(self._name(index), data)
        self.names.append(self._name(index))
        return len(data)

    def close(self) -> int:
        """Write what is left: one unnumbered part when nothing was written yet, else the next numbered one."""
        if not self.buf:
            return 0
        return self._flush(None if not self.names else len(self.names))


def _table_record(name: str, label: str, version: int, batch: Any, fields: Dict[str, List[str]], rows: int,
                  parts: List[str]) -> cf.TableRecord:
    pk_pos = {c: i + 1 for i, c in enumerate(batch.pk)}
    return cf.TableRecord(store=name, table=batch.table, inventory_label=label, schema_version=version,
                          columns=[[c, t, pk_pos.get(c, 0)] for c, t in zip(batch.columns, batch.decltypes)],
                          rows=rows, parts=parts, omitted_columns=list(batch.omitted), without_rowid=batch.without_rowid,
                          keys=list(fields["keys"]), paths=list(fields["paths"]))


def write_rows(sink: Any, plan: Any, job: JobHandle, state: Any) -> RowsOut:
    out = RowsOut()
    for label, version, batches in cs.snapshot_rows(plan.row_queries, plan.secret_columns, state_dir=state):
        name = crate_store(label)
        open_parts: Dict[str, Tuple[_Parts, Any]] = {}
        for batch in batches:
            job.check()
            if batch.table not in open_parts:
                open_parts[batch.table] = (_Parts(sink, name, batch.table), batch)
            parts = open_parts[batch.table][0]
            fields = plan.row_fields.get((label, batch.table), {"keys": [], "paths": []})
            for row in batch.rows:
                encoded = {c: cf.canonical.encode_value(v) for c, v in row.items()}
                job.add(parts.add(cf.canonical.dumps(encoded)))
                out.paths += path_records(name, batch.table, row, batch.pk, fields["keys"], fields["paths"], out.warnings)
                out.counts[(label, batch.table)] = out.counts.get((label, batch.table), 0) + 1
        for table, (parts, first) in open_parts.items():
            parts.close()
            fields = plan.row_fields.get((label, table), {"keys": [], "paths": []})
            out.tables.setdefault(name, {})[table] = _table_record(name, label, version, first, fields,
                                                                   out.counts.get((label, table), 0), parts.names)
    return out
