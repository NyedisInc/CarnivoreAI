
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from src.core.crate_import.keyrules import NULL_FOREIGN, rule_for
from src.core.crate_import.provenance import Provenance
from src.core.inventory.identity import SAFE_CONVERSATION
from src.core.project_move.paths import PathMapping

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,63}$")
MAX_VALUE_BYTES = 4 * 1024 * 1024
FAMILIES = ("claude", "codex")
UUID_COLUMNS: Dict[str, Tuple[str, ...]] = {"sessions": ("claude_session_uuid",)}
CONVERSATION_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "sessions": ("session_uuid",),
    "session_conversations": ("conversation_id", "parent_conversation_id"),
    "conversation_index": ("conversation_id",),
    "conversation_milestones": ("conversation_id",),
}
LAUNCH_DROPPED = ("launch_record", "extra_env")

SKIP_MISSING_REQUIRED = "missing_required"
SKIP_TOO_LARGE = "value_too_large"
SKIP_UNKNOWN_TABLE = "unknown_table"
SKIP_REMOTE = "remote_session"
SKIP_COMPANION = "companion_session"


@dataclass(frozen=True)
class TableShape:

    columns: Tuple[str, ...]
    required: Tuple[str, ...]
    blanks: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class RowVerdict:

    row: Optional[Dict[str, Any]] = None
    skipped: str = ""
    dropped: Dict[str, str] = field(default_factory=dict)
    rewrites: List[Tuple[str, str, str]] = field(default_factory=list)
    outside: List[str] = field(default_factory=list)
    bad_identifier: List[str] = field(default_factory=list)
    path_blocks: List[str] = field(default_factory=list)


def live_shape(conn: sqlite3.Connection, table: str) -> Optional[TableShape]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        return None
    columns = tuple(r[1] for r in rows)
    required = tuple(r[1] for r in rows if r[3] and r[4] is None and not (r[5] == 1 and (r[2] or "").upper() == "INTEGER"))
    numeric = ("INT", "REAL", "NUM", "FLOA", "DOUB")
    blanks = {r[1]: (0 if any(t in (r[2] or "").upper() for t in numeric) else "") for r in rows if r[3]}
    return TableShape(columns, required, blanks)


def _walk(node: Any, parts: List[str], fn: Callable[[Any], Any]) -> Any:
    if not parts:
        return fn(node)
    head, rest = parts[0], parts[1:]
    many = head.endswith("[]")
    key = head[:-2] if many else head
    if not isinstance(node, dict) or (key and key not in node):
        return node
    target = node[key] if key else node
    if many:
        if isinstance(target, list):
            node[key] = [_walk(item, rest, fn) for item in target]
    else:
        node[key] = _walk(target, rest, fn)
    return node


def map_path_value(value: Any, mapping: PathMapping) -> Tuple[Any, Optional[str]]:
    if not isinstance(value, str) or not value.startswith("/"):
        return value, None
    mapped = mapping.apply(value)
    return (value, "outside") if mapped is None else (mapped, None)


def _map_column(row: Dict[str, Any], spec: str, mapping: PathMapping, verdict: RowVerdict, foreign: bool,
                shape: Optional[TableShape] = None) -> None:
    import json

    column, _, jpath = spec.partition("#")
    value = row.get(column)
    if value is None or (isinstance(value, str) and not value.strip()):
        return
    if not jpath and not (isinstance(value, str) and value[:1] in "[{"):
        new, state = map_path_value(value, mapping)
        if state == "outside":
            verdict.outside.append(column)
            if column == "working_dir":
                verdict.path_blocks.append(column)
            elif foreign:
                row[column] = None
        elif new != value:
            verdict.rewrites.append((column, value, new))
            row[column] = new
        return
    try:
        tree = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        verdict.dropped[column] = "json_unreadable"
        row[column] = shape.blanks.get(column) if shape is not None and column in shape.blanks else None
        return
    changed: List[Tuple[str, str]] = []

    def leaf(item: Any) -> Any:
        new, state = map_path_value(item, mapping)
        if state == "outside":
            verdict.outside.append(column)
            return None if foreign else item
        if new != item:
            changed.append((item, new))
        return new

    if jpath:
        tree = _walk(tree, jpath.split("."), leaf)
    elif isinstance(tree, list):
        tree = [leaf(item) for item in tree]
    if changed:
        verdict.rewrites.append((column, changed[0][0], changed[0][1]))
    row[column] = json.dumps(tree, separators=(",", ":")) if isinstance(value, str) else tree


def _family_of(row: Mapping[str, Any]) -> str:
    for key in ("agent_family", "agent_type"):
        value = str(row.get(key) or "")
        if value in FAMILIES or value.startswith("codex"):
            return "codex" if value.startswith("codex") else value
    return "claude"


def _foreign_session(row: Dict[str, Any], verdict: RowVerdict) -> None:
    for column in LAUNCH_DROPPED:
        if row.get(column) is not None:
            verdict.dropped[column] = "foreign_launch"
        row.pop(column, None)
    row["agent_type"] = _family_of(row)
    model = row.get("model")
    if model is not None and not (isinstance(model, str) and MODEL_RE.match(model)):
        verdict.dropped["model"] = "not_a_model_name"
        row["model"] = None
    row["host_key"] = "local"


def sanitize_row(table: str, row: Mapping[str, Any], *, shape: Optional[TableShape], secret_columns: Tuple[str, ...],
                 path_columns: Tuple[str, ...], mapping: PathMapping, provenance: Provenance, store: str = "cloude.db") -> RowVerdict:
    verdict = RowVerdict()
    if table == "sessions":
        if row.get("host_key") not in (None, "", "local"):
            verdict.skipped = SKIP_REMOTE
            return verdict
        if row.get("companion_of") is not None:
            verdict.skipped = SKIP_COMPANION
            return verdict
    out: Dict[str, Any] = dict(row)
    for column in list(out):
        if column in secret_columns:
            verdict.dropped[column] = "secret"
            del out[column]
        elif shape is not None and column not in shape.columns:
            verdict.dropped[column] = "unknown_column"
            del out[column]
    for column, value in out.items():
        if isinstance(value, (str, bytes)) and len(value) > MAX_VALUE_BYTES:
            verdict.skipped = SKIP_TOO_LARGE
            return verdict
    for shape_re, by_table in ((UUID_RE, UUID_COLUMNS), (SAFE_CONVERSATION, CONVERSATION_COLUMNS)):
        for column in by_table.get(table, ()):
            value = out.get(column)
            if value is not None and not (isinstance(value, str) and shape_re.match(value)):
                verdict.bad_identifier.append(column)
    if verdict.bad_identifier:
        return verdict
    for column in list(out):
        rule = rule_for(store, table, column)
        if rule is not None and rule.kind == NULL_FOREIGN and column != "host_key":
            out[column] = shape.blanks.get(column) if shape is not None and column in shape.blanks else None
    if table == "sessions":
        if not provenance.own:
            _foreign_session(out, verdict)
        else:
            out["host_key"] = "local"
    for spec in path_columns:
        _map_column(out, spec, mapping, verdict, foreign=not provenance.own, shape=shape)
    if shape is not None:
        missing = [c for c in shape.required if out.get(c) is None]
        if missing:
            verdict.skipped = SKIP_MISSING_REQUIRED
            verdict.dropped.update({c: "missing_required" for c in missing})
            return verdict
    verdict.row = out
    return verdict
