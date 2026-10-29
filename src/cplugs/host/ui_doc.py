
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Collection, Dict, List, Mapping

from src.core.message_model_secrets import scan_text

MAX_NODES = 500
MAX_DEPTH = 12
MAX_BYTES = 64 * 1024
MAX_ROWS = 100
MAX_COLUMNS = 12
MAX_TEXT = 2000
MAX_LABEL = 200
MAX_PAYLOAD_BYTES = 4096
SCHEMA = 1
TONES = frozenset({"normal", "muted", "accent", "warn", "danger"})
STATUSES = frozenset({"working", "working_subagent", "question", "notice", "finished_unread", "idle", "dead", "unknown"})
_INVISIBLE = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_SCHEME = re.compile(r"(^|[\s(<\[\"'])[a-z][a-z0-9+.\-]{1,20}:(//|[^\s0-9])", re.I)
_DATA_ID = re.compile(r"(adopted|plugin|remote):[A-Za-z0-9_.:\-]{1,200}")
_POINTER = re.compile(r"(/[A-Za-z0-9_\-]{1,40}){1,8}")
_NAME = re.compile(r"^[a-z][a-z0-9_\-]{0,63}$")


class UiDocError(ValueError):

    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"{code} at {path or '/'}")
        self.code, self.path = code, path


class _Walk:

    def __init__(self, routes: Collection[str], tools: Collection[str]) -> None:
        self.routes, self.tools, self.nodes = frozenset(routes), frozenset(tools), 0


    @staticmethod
    def string(value: Any, path: str, limit: int, scheme: bool = True) -> str:
        if not isinstance(value, str) or len(value) > limit:
            raise UiDocError("bad_string", path)
        if any(unicodedata.category(c) in _INVISIBLE for c in value):
            raise UiDocError("invisible_character", path)
        if _SCHEME.search(value) and (scheme or not _DATA_ID.fullmatch(value)):
            raise UiDocError("link_not_allowed", path)
        if scan_text(value):
            raise UiDocError("secret_shape", path)
        return value

    def scalar(self, value: Any, path: str, limit: int = MAX_TEXT) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            if isinstance(value, float) and value != value or value in (float("inf"), float("-inf")):
                raise UiDocError("bad_number", path)
            return value
        if isinstance(value, dict):
            pointer = value.get("bind")
            if set(value) != {"bind"} or not isinstance(pointer, str) or not _POINTER.fullmatch(pointer):
                raise UiDocError("bad_bind", path)
            return {"bind": pointer}
        return self.string(value, path, limit)

    def tone(self, raw: Mapping[str, Any], path: str) -> Dict[str, Any]:
        if "tone" not in raw:
            return {}
        if not isinstance(raw["tone"], str) or raw["tone"] not in TONES:
            raise UiDocError("bad_tone", f"{path}/tone")
        return {"tone": raw["tone"]}


    def action(self, raw: Any, path: str) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise UiDocError("bad_action", path)
        call = raw.get("call")
        if call not in ("route", "tool"):
            raise UiDocError("action_not_supported", f"{path}/call")
        field, declared = ("route", self.routes) if call == "route" else ("name", self.tools)
        if set(raw) - {"call", field, "payload"} or not isinstance(raw.get(field), str) or raw[field] not in declared:
            raise UiDocError("action_not_declared", f"{path}/{field}")
        out: Dict[str, Any] = {"call": call, field: raw[field]}
        if "payload" in raw:
            out["payload"] = self.payload(raw["payload"], f"{path}/payload")
        return out

    def payload(self, value: Any, path: str) -> Dict[str, Any]:
        if not isinstance(value, dict) or len(json.dumps(value, default=str)) > MAX_PAYLOAD_BYTES:
            raise UiDocError("bad_payload", path)
        return self.json_value(value, path, 0)

    def json_value(self, value: Any, path: str, depth: int, scheme: bool = True) -> Any:
        if depth > 6:
            raise UiDocError("too_deep", path)
        if isinstance(value, dict):
            return {self.string(k, path, MAX_LABEL, scheme): self.json_value(v, f"{path}/{k[:20]}", depth + 1, scheme) for k, v in value.items()}
        if isinstance(value, list):
            return [self.json_value(v, f"{path}/{i}", depth + 1, scheme) for i, v in enumerate(value[:100])]
        if isinstance(value, str):
            return self.string(value, path, MAX_TEXT, scheme)
        if value is None or isinstance(value, (bool, int, float)):
            return self.scalar(value, path)
        raise UiDocError("bad_value", path)


    def node(self, raw: Any, path: str, depth: int) -> Dict[str, Any]:
        if depth > MAX_DEPTH:
            raise UiDocError("too_deep", path)
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise UiDocError("too_many_nodes", path)
        if not isinstance(raw, dict):
            raise UiDocError("bad_node", path)
        kind = raw.get("type")
        build = getattr(self, f"n_{kind}") if isinstance(kind, str) and kind in _FIELDS else None
        if build is None:
            raise UiDocError("unknown_node", f"{path}/type")
        allowed = _FIELDS[kind] | {"type"}
        extra = set(raw) - allowed
        if extra:
            raise UiDocError("unknown_field", f"{path}/{sorted(map(str, extra))[0][:30]}")
        return {"type": kind, **build(raw, path, depth)}

    def kids(self, raw: Mapping[str, Any], key: str, path: str, depth: int) -> List[Dict[str, Any]]:
        items = raw.get(key, [])
        if not isinstance(items, list):
            raise UiDocError("bad_children", f"{path}/{key}")
        return [self.node(c, f"{path}/{key}/{i}", depth + 1) for i, c in enumerate(items)]

    def n_section(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        out: Dict[str, Any] = {"children": self.kids(raw, "children", path, depth)}
        if "title" in raw:
            out["title"] = self.string(raw["title"], f"{path}/title", MAX_LABEL)
        return out

    def _layout(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        out: Dict[str, Any] = {"children": self.kids(raw, "children", path, depth)}
        if "gap" in raw:
            if isinstance(raw["gap"], bool) or not isinstance(raw["gap"], int) or not 0 <= raw["gap"] <= 8:
                raise UiDocError("bad_gap", f"{path}/gap")
            out["gap"] = raw["gap"]
        if "wrap" in raw:
            if not isinstance(raw["wrap"], bool):
                raise UiDocError("bad_wrap", f"{path}/wrap")
            out["wrap"] = raw["wrap"]
        return out

    n_row = n_column = _layout

    def n_text(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "value" not in raw:
            raise UiDocError("missing_value", path)
        return {"value": self.scalar(raw["value"], f"{path}/value"), **self.tone(raw, path)}

    def n_badge(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if ("status" in raw) == ("text" in raw):
            raise UiDocError("badge_needs_status_or_text", path)
        out: Dict[str, Any] = self.tone(raw, path)
        if "status" in raw:
            if not isinstance(raw["status"], str) or raw["status"] not in STATUSES:
                raise UiDocError("bad_status", f"{path}/status")
            out["status"] = raw["status"]
        else:
            out["text"] = self.string(raw["text"], f"{path}/text", MAX_LABEL)
        return out

    def n_stat(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "value" not in raw or "label" not in raw:
            raise UiDocError("missing_value", path)
        out = {"label": self.string(raw["label"], f"{path}/label", MAX_LABEL), "value": self.scalar(raw["value"], f"{path}/value", MAX_LABEL),
               **self.tone(raw, path)}
        for key in ("unit", "delta"):
            if key in raw:
                out[key] = self.string(raw[key], f"{path}/{key}", MAX_LABEL)
        return out

    def n_list(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        out: Dict[str, Any] = {"items": self.kids(raw, "items", path, depth)}
        if "empty" in raw:
            out["empty"] = self.string(raw["empty"], f"{path}/empty", MAX_LABEL)
        return out

    def n_table(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        cols, rows = raw.get("columns"), raw.get("rows", [])
        if not isinstance(cols, list) or not 1 <= len(cols) <= MAX_COLUMNS or not isinstance(rows, list):
            raise UiDocError("bad_table", path)
        if len(rows) > MAX_ROWS:
            raise UiDocError("too_many_rows", f"{path}/rows")
        out_rows = []
        for i, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(cols):
                raise UiDocError("bad_row", f"{path}/rows/{i}")
            out_rows.append([self.scalar(cell, f"{path}/rows/{i}/{j}", MAX_LABEL) for j, cell in enumerate(row)])
        return {"columns": [self.string(c, f"{path}/columns/{j}", MAX_LABEL) for j, c in enumerate(cols)], "rows": out_rows}

    def n_button(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "label" not in raw or "action" not in raw:
            raise UiDocError("missing_value", path)
        out = {"label": self.string(raw["label"], f"{path}/label", MAX_LABEL), "action": self.action(raw["action"], f"{path}/action"),
               **self.tone(raw, path)}
        if "confirm" in raw:
            out["confirm"] = self.string(raw["confirm"], f"{path}/confirm", MAX_LABEL)
        return out

    def n_meter(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if not {"value", "max", "label"} <= set(raw):
            raise UiDocError("missing_value", path)
        out = {"label": self.string(raw["label"], f"{path}/label", MAX_LABEL), "value": self.scalar(raw["value"], f"{path}/value"),
               "max": self.scalar(raw["max"], f"{path}/max")}
        if "thresholds" in raw:
            t = raw["thresholds"]
            if not isinstance(t, list) or len(t) > 8 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in t):
                raise UiDocError("bad_thresholds", f"{path}/thresholds")
            out["thresholds"] = t
        return out


_FIELDS: Dict[str, frozenset] = {
    "section": frozenset({"title", "children"}), "row": frozenset({"children", "gap", "wrap"}), "column": frozenset({"children", "gap", "wrap"}),
    "text": frozenset({"value", "tone"}), "badge": frozenset({"status", "text", "tone"}),
    "stat": frozenset({"label", "value", "unit", "delta", "tone"}), "list": frozenset({"items", "empty"}),
    "table": frozenset({"columns", "rows"}), "button": frozenset({"label", "action", "confirm", "tone"}),
    "meter": frozenset({"value", "max", "label", "thresholds"}),
}
NODE_TYPES = frozenset(_FIELDS)


def validate(document: Any, *, routes: Collection[str], tools: Collection[str]) -> Dict[str, Any]:
    if not isinstance(document, dict) or set(document) - {"schema", "root", "data"}:
        raise UiDocError("bad_document", "")
    if type(document.get("schema")) is not int or document["schema"] != SCHEMA:
        raise UiDocError("bad_schema", "/schema")
    try:
        size = len(json.dumps(document, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise UiDocError("not_json", "") from exc
    if size > MAX_BYTES:
        raise UiDocError("too_large", "")
    walk = _Walk(routes, tools)
    out: Dict[str, Any] = {"schema": SCHEMA, "root": walk.node(document.get("root"), "/root", 0)}
    if "data" in document:
        if not isinstance(document["data"], dict):
            raise UiDocError("bad_data", "/data")
        out["data"] = walk.json_value(document["data"], "/data", 0, scheme=False)
    return out
