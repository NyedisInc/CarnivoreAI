
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Collection, Dict, List, Mapping
from urllib.parse import urlparse

from src.core.message_model_secrets import scan_text
from src.models.activity_status import ACTIVITY_STATUSES
from src.plugins.host.ui_doc_markdown import check_markdown_safe_violation

MAX_NODES = 500
MAX_DEPTH = 12
MAX_BYTES = 64 * 1024
MAX_ROWS = 100
MAX_COLUMNS = 12
MAX_TEXT = 2000
MAX_LABEL = 200
MAX_PAYLOAD_BYTES = 4096
SCHEMA = 2
SUPPORTED_SCHEMAS = frozenset({1, 2})
TONES = frozenset({"normal", "muted", "accent", "warn", "danger"})
INPUT_TYPES = frozenset({"text", "number", "email", "url", "search"})
V1_NODE_TYPES = frozenset({"section", "row", "column", "text", "badge", "stat", "list", "table", "button", "meter"})
STATUSES = ACTIVITY_STATUSES
_INVISIBLE = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_SCHEME = re.compile(
    r"(^|[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff(<\[\"'])"
    r"[A-Za-z][A-Za-z0-9+.\-]{1,20}:(//|[^\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff0-9])"
)
_DATA_ID = re.compile(r"(adopted|plugin|remote):[A-Za-z0-9_.:\-]{1,200}")
_WIDGET_ID = re.compile(
    r"^(?:core\.[a-z0-9][a-z0-9-]*|(?!core\.)[a-z][a-z0-9-]{1,23}\.[a-z][a-z0-9-]{0,31}:[a-z0-9][a-z0-9:_-]{0,63})$"
)
_POINTER = re.compile(r"(/[A-Za-z0-9_\-]{1,40}){1,8}")
_NAME = re.compile(r"^[a-z][a-z0-9_\-]{0,63}$")
_FORM_CONTROL_TYPES = frozenset({"input", "textarea", "select", "toggle"})
_SAFE_URLS = frozenset({"http", "https"})
_SLOT_ENTRY_KEYS = frozenset({
    "id", "label", "title", "subtitle", "description", "tooltip", "icon",
    "shortcut", "chord", "route", "tool", "macro", "command", "action",
    "confirm", "tone", "badge", "status", "payload", "position", "order",
    "priority", "group", "category", "when", "href", "document", "surface",
    "view", "panel", "width", "height", "props", "data", "popout",
    "disabled", "variant", "kind", "widget", "tab",
})
_SLOT_LABEL_KEYS = (
    "id", "label", "title", "subtitle", "tooltip", "icon", "shortcut", "chord",
    "confirm", "badge", "command", "surface", "view", "panel", "position",
    "group", "category", "variant", "kind", "tab",
)


class UiDocError(ValueError):

    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"{code} at {path or '/'}")
        self.code, self.path = code, path


class _Walk:

    def __init__(self, routes: Collection[str], tools: Collection[str], schema: int = SCHEMA) -> None:
        self.routes, self.tools, self.schema, self.nodes = frozenset(routes), frozenset(tools), schema, 0


    @staticmethod
    def string(value: Any, path: str, limit: int, scheme: bool = True, allow_newlines: bool = False) -> str:
        if not isinstance(value, str) or len(value) > limit:
            raise UiDocError("bad_string", path)
        if any(unicodedata.category(c) in _INVISIBLE and not (allow_newlines and c == "\n") for c in value):
            raise UiDocError("invisible_character", path)
        if _SCHEME.search(value) and (scheme or not _DATA_ID.fullmatch(value)):
            raise UiDocError("link_not_allowed", path)
        if scan_text(value):
            raise UiDocError("secret_shape", path)
        return value

    def scalar(self, value: Any, path: str, limit: int = MAX_TEXT, allow_newlines: bool = False) -> Any:
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
        return self.string(value, path, limit, allow_newlines=allow_newlines)

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
        build = getattr(self, f"n_{kind}", None) if isinstance(kind, str) and kind in _FIELDS else None
        if build is None or (self.schema == 1 and kind not in V1_NODE_TYPES):
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

    def _field_name(self, value: Any, path: str) -> str:
        if not isinstance(value, str) or not _NAME.fullmatch(value):
            raise UiDocError("bad_name", path)
        return value

    def _bool_opt(self, raw: Mapping[str, Any], key: str, path: str, out: Dict[str, Any], code: str = "bad_value") -> None:
        if key in raw:
            if not isinstance(raw[key], bool):
                raise UiDocError(code, f"{path}/{key}")
            out[key] = raw[key]

    def n_input(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "name" not in raw or "label" not in raw:
            raise UiDocError("missing_value", path)
        out: Dict[str, Any] = {
            "name": self._field_name(raw["name"], f"{path}/name"),
            "label": self.string(raw["label"], f"{path}/label", MAX_LABEL),
        }
        if "value" in raw:
            out["value"] = self.scalar(raw["value"], f"{path}/value", MAX_TEXT)
        if "placeholder" in raw:
            out["placeholder"] = self.string(raw["placeholder"], f"{path}/placeholder", MAX_LABEL)
        if "input_type" in raw:
            if not isinstance(raw["input_type"], str) or raw["input_type"] not in INPUT_TYPES:
                raise UiDocError("bad_input_type", f"{path}/input_type")
            out["input_type"] = raw["input_type"]
        self._bool_opt(raw, "required", path, out)
        self._bool_opt(raw, "disabled", path, out)
        return out

    def n_textarea(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "name" not in raw or "label" not in raw:
            raise UiDocError("missing_value", path)
        out: Dict[str, Any] = {
            "name": self._field_name(raw["name"], f"{path}/name"),
            "label": self.string(raw["label"], f"{path}/label", MAX_LABEL),
        }
        if "value" in raw:
            out["value"] = self.scalar(raw["value"], f"{path}/value", MAX_TEXT)
        if "placeholder" in raw:
            out["placeholder"] = self.string(raw["placeholder"], f"{path}/placeholder", MAX_LABEL)
        if "rows" in raw:
            if isinstance(raw["rows"], bool) or not isinstance(raw["rows"], int) or not 1 <= raw["rows"] <= 20:
                raise UiDocError("bad_rows", f"{path}/rows")
            out["rows"] = raw["rows"]
        self._bool_opt(raw, "required", path, out)
        self._bool_opt(raw, "disabled", path, out)
        return out

    def n_select(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "name" not in raw or "label" not in raw or "options" not in raw:
            raise UiDocError("missing_value", path)
        opts = raw["options"]
        if not isinstance(opts, list) or not 1 <= len(opts) <= MAX_ROWS:
            raise UiDocError("bad_options", f"{path}/options")
        out_opts: List[Any] = []
        for idx, opt in enumerate(opts):
            if isinstance(opt, str):
                out_opts.append(self.string(opt, f"{path}/options/{idx}", MAX_LABEL))
            elif isinstance(opt, dict) and set(opt) == {"value", "label"}:
                out_opts.append({
                    "value": self.string(opt["value"], f"{path}/options/{idx}/value", MAX_LABEL),
                    "label": self.string(opt["label"], f"{path}/options/{idx}/label", MAX_LABEL),
                })
            else:
                raise UiDocError("bad_options", f"{path}/options/{idx}")
        out: Dict[str, Any] = {
            "name": self._field_name(raw["name"], f"{path}/name"),
            "label": self.string(raw["label"], f"{path}/label", MAX_LABEL),
            "options": out_opts,
        }
        if "value" in raw:
            out["value"] = self.scalar(raw["value"], f"{path}/value", MAX_LABEL)
        self._bool_opt(raw, "required", path, out)
        self._bool_opt(raw, "disabled", path, out)
        return out

    def n_toggle(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "name" not in raw or "label" not in raw:
            raise UiDocError("missing_value", path)
        out: Dict[str, Any] = {
            "name": self._field_name(raw["name"], f"{path}/name"),
            "label": self.string(raw["label"], f"{path}/label", MAX_LABEL),
            **self.tone(raw, path),
        }
        if "checked" in raw:
            val = raw["checked"]
            if not isinstance(val, (bool, dict)):
                raise UiDocError("bad_value", f"{path}/checked")
            out["checked"] = self.scalar(val, f"{path}/checked")
        self._bool_opt(raw, "disabled", path, out)
        return out

    def n_tabs(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        items = raw.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            raise UiDocError("bad_tabs", f"{path}/items")
        out_items: List[Dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict) or set(item) - {"id", "label", "content", "children"}:
                raise UiDocError("bad_tabs", f"{path}/items/{idx}")
            if "id" not in item or "label" not in item or ("content" not in item and "children" not in item):
                raise UiDocError("bad_tabs", f"{path}/items/{idx}")
            rebuilt: Dict[str, Any] = {
                "id": self._field_name(item["id"], f"{path}/items/{idx}/id"),
                "label": self.string(item["label"], f"{path}/items/{idx}/label", MAX_LABEL),
            }
            if "content" in item:
                rebuilt["content"] = self.node(item["content"], f"{path}/items/{idx}/content", depth + 1)
            if "children" in item:
                rebuilt["children"] = self.kids(item, "children", f"{path}/items/{idx}", depth)
            out_items.append(rebuilt)
        out: Dict[str, Any] = {"items": out_items}
        if "active" in raw:
            out["active"] = self._field_name(raw["active"], f"{path}/active")
        return out

    def _check_form_node(self, child: Dict[str, Any], node_path: str, seen: set[str]) -> None:
        kind = child.get("type")
        if kind in _FORM_CONTROL_TYPES:
            name = child["name"]
            if name in seen:
                raise UiDocError("duplicate_field_name", f"{node_path}/name")
            seen.add(name)
            return
        if kind == "form":
            return
        if "children" in child and isinstance(child["children"], list):
            self._check_form_list(child["children"], f"{node_path}/children", seen)
        if "items" in child and isinstance(child["items"], list):
            if kind == "tabs":
                for idx, item in enumerate(child["items"]):
                    if isinstance(item, dict):
                        if "content" in item and isinstance(item["content"], dict):
                            self._check_form_node(item["content"], f"{node_path}/items/{idx}/content", seen)
                        if "children" in item and isinstance(item["children"], list):
                            self._check_form_list(item["children"], f"{node_path}/items/{idx}/children", seen)
            else:
                self._check_form_list(child["items"], f"{node_path}/items", seen)

    def _check_form_list(self, nodes: List[Dict[str, Any]], list_path: str, seen: set[str]) -> None:
        for idx, child in enumerate(nodes):
            self._check_form_node(child, f"{list_path}/{idx}", seen)

    def n_form(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "action" not in raw:
            raise UiDocError("missing_value", path)
        children = self.kids(raw, "children", path, depth)
        self._check_form_list(children, f"{path}/children", set())
        out: Dict[str, Any] = {
            "children": children,
            "action": self.action(raw["action"], f"{path}/action"),
            **self.tone(raw, path),
        }
        if "submit_label" in raw:
            out["submit_label"] = self.string(raw["submit_label"], f"{path}/submit_label", MAX_LABEL)
        return out

    def n_code(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "value" not in raw:
            raise UiDocError("missing_value", path)
        out: Dict[str, Any] = {"value": self.scalar(raw["value"], f"{path}/value", MAX_TEXT)}
        if "language" in raw:
            out["language"] = self.string(raw["language"], f"{path}/language", 40)
        return out

    def n_markdown_safe(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "value" not in raw:
            raise UiDocError("missing_value", path)
        val = self.scalar(raw["value"], f"{path}/value", MAX_TEXT, allow_newlines=True)
        if isinstance(val, str):
            code = check_markdown_safe_violation(val)
            if code is not None:
                raise UiDocError(code, f"{path}/value")
        return {"value": val}

    def n_progress(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "label" not in raw:
            raise UiDocError("missing_value", path)
        indeterminate = raw.get("indeterminate", False)
        if not isinstance(indeterminate, bool):
            raise UiDocError("bad_value", f"{path}/indeterminate")
        if "value" not in raw and not indeterminate:
            raise UiDocError("missing_value", path)
        out: Dict[str, Any] = {"label": self.string(raw["label"], f"{path}/label", MAX_LABEL), **self.tone(raw, path)}
        if "value" in raw:
            out["value"] = self.scalar(raw["value"], f"{path}/value")
        if "max" in raw:
            out["max"] = self.scalar(raw["max"], f"{path}/max")
        if "indeterminate" in raw:
            out["indeterminate"] = indeterminate
        return out

    def n_empty_state(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "title" not in raw:
            raise UiDocError("missing_value", path)
        out: Dict[str, Any] = {"title": self.string(raw["title"], f"{path}/title", MAX_LABEL), **self.tone(raw, path)}
        if "description" in raw:
            out["description"] = self.string(raw["description"], f"{path}/description", MAX_TEXT)
        if "action" in raw:
            out["action"] = self.action(raw["action"], f"{path}/action")
        return out

    def n_sparkline(self, raw: Mapping[str, Any], path: str, depth: int) -> Dict[str, Any]:
        if "values" not in raw:
            raise UiDocError("missing_value", path)
        vals = raw["values"]
        if not isinstance(vals, list) or len(vals) > MAX_ROWS or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or (isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))))
            for x in vals
        ):
            raise UiDocError("bad_values", f"{path}/values")
        out: Dict[str, Any] = {"values": list(vals), **self.tone(raw, path)}
        if "label" in raw:
            out["label"] = self.string(raw["label"], f"{path}/label", MAX_LABEL)
        return out


_FIELDS: Dict[str, frozenset] = {
    "section": frozenset({"title", "children"}), "row": frozenset({"children", "gap", "wrap"}), "column": frozenset({"children", "gap", "wrap"}),
    "text": frozenset({"value", "tone"}), "badge": frozenset({"status", "text", "tone"}),
    "stat": frozenset({"label", "value", "unit", "delta", "tone"}), "list": frozenset({"items", "empty"}),
    "table": frozenset({"columns", "rows"}), "button": frozenset({"label", "action", "confirm", "tone"}),
    "meter": frozenset({"value", "max", "label", "thresholds"}),
    "input": frozenset({"name", "label", "value", "placeholder", "input_type", "required", "disabled"}),
    "textarea": frozenset({"name", "label", "value", "placeholder", "rows", "required", "disabled"}),
    "select": frozenset({"name", "label", "value", "options", "required", "disabled"}),
    "toggle": frozenset({"name", "label", "checked", "disabled", "tone"}),
    "tabs": frozenset({"items", "active"}),
    "form": frozenset({"children", "action", "submit_label", "tone"}),
    "code": frozenset({"value", "language"}),
    "markdown_safe": frozenset({"value"}),
    "progress": frozenset({"value", "max", "label", "indeterminate", "tone"}),
    "empty_state": frozenset({"title", "description", "action", "tone"}),
    "sparkline": frozenset({"values", "label", "tone"}),
}
NODE_TYPES = frozenset(_FIELDS)


def validate(document: Any, *, routes: Collection[str], tools: Collection[str]) -> Dict[str, Any]:
    if not isinstance(document, dict) or set(document) - {"schema", "root", "data"}:
        raise UiDocError("bad_document", "")
    doc_schema = document.get("schema")
    if type(doc_schema) is not int or doc_schema not in SUPPORTED_SCHEMAS:
        raise UiDocError("bad_schema", "/schema")
    try:
        size = len(json.dumps(document, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise UiDocError("not_json", "") from exc
    if size > MAX_BYTES:
        raise UiDocError("too_large", "")
    walk = _Walk(routes, tools, schema=doc_schema)
    out: Dict[str, Any] = {"schema": doc_schema, "root": walk.node(document.get("root"), "/root", 0)}
    if "data" in document:
        if not isinstance(document["data"], dict):
            raise UiDocError("bad_data", "/data")
        out["data"] = walk.json_value(document["data"], "/data", 0, scheme=False)
    return out


def _safe_href(value: Any, path: str, walk: _Walk) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise UiDocError("bad_string", path)
    if any(unicodedata.category(c) in _INVISIBLE for c in value):
        raise UiDocError("invisible_character", path)
    if scan_text(value):
        raise UiDocError("secret_shape", path)
    stripped = value.strip()
    parsed = urlparse(stripped)
    if parsed.scheme:
        if parsed.scheme.lower() not in _SAFE_URLS or not parsed.netloc:
            raise UiDocError("link_not_allowed", path)
    elif not stripped.startswith("/") or stripped.startswith("//") or _SCHEME.search(stripped):
        raise UiDocError("link_not_allowed", path)
    return stripped


def validate_slot_entry(
    entry: Any,
    *,
    routes: Collection[str],
    tools: Collection[str],
    path: str = "/slot",
    macros: Collection[str] = (),
) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise UiDocError("bad_slot_entry", path)
    try:
        size = len(json.dumps(entry, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise UiDocError("not_json", path) from exc
    if size > MAX_BYTES:
        raise UiDocError("too_large", path)
    if "schema" in entry and "root" in entry:
        return validate(entry, routes=routes, tools=tools)
    extra = set(entry) - _SLOT_ENTRY_KEYS
    if extra:
        raise UiDocError("unknown_field", f"{path}/{sorted(map(str, extra))[0][:30]}")
    walk = _Walk(routes, tools, schema=SCHEMA)
    out: Dict[str, Any] = walk.tone(entry, path)
    for key in _SLOT_LABEL_KEYS:
        if key in entry:
            out[key] = walk.string(entry[key], f"{path}/{key}", MAX_LABEL)
    if "widget" in entry:
        raw_widget = entry["widget"]
        if not isinstance(raw_widget, str) or len(raw_widget) > MAX_LABEL:
            raise UiDocError("bad_string", f"{path}/widget")
        if any(unicodedata.category(c) in _INVISIBLE for c in raw_widget):
            raise UiDocError("invisible_character", f"{path}/widget")
        if scan_text(raw_widget):
            raise UiDocError("secret_shape", f"{path}/widget")
        if not _WIDGET_ID.fullmatch(raw_widget):
            if _SCHEME.search(raw_widget):
                raise UiDocError("link_not_allowed", f"{path}/widget")
            raise UiDocError("bad_widget", f"{path}/widget")
        out["widget"] = raw_widget
    if "description" in entry:
        out["description"] = walk.string(entry["description"], f"{path}/description", MAX_TEXT, allow_newlines=True)
    if "status" in entry:
        if not isinstance(entry["status"], str) or entry["status"] not in STATUSES:
            raise UiDocError("bad_status", f"{path}/status")
        out["status"] = entry["status"]
    if "disabled" in entry:
        if not isinstance(entry["disabled"], bool):
            raise UiDocError("bad_value", f"{path}/disabled")
        out["disabled"] = entry["disabled"]
    for num_key in ("order", "priority", "width", "height"):
        if num_key in entry:
            val = entry[num_key]
            if isinstance(val, bool) or not isinstance(val, (int, float)) or val != val or val in (float("inf"), float("-inf")):
                raise UiDocError("bad_number", f"{path}/{num_key}")
            out[num_key] = val
    if "route" in entry:
        route_name = entry["route"]
        if not isinstance(route_name, str) or route_name not in walk.routes:
            raise UiDocError("action_not_declared", f"{path}/route")
        out["route"] = route_name
    if "tool" in entry:
        tool_name = entry["tool"]
        if not isinstance(tool_name, str) or tool_name not in walk.tools:
            raise UiDocError("action_not_declared", f"{path}/tool")
        out["tool"] = tool_name
    if "macro" in entry:
        macro_name = walk.string(entry["macro"], f"{path}/macro", MAX_LABEL)
        if macro_name not in set(macros or ()):
            raise UiDocError("action_not_declared", f"{path}/macro")
        out["macro"] = macro_name
    if "action" in entry:
        raw_action = entry["action"]
        if isinstance(raw_action, dict):
            out["action"] = walk.action(raw_action, f"{path}/action")
        else:
            out["action"] = walk.string(raw_action, f"{path}/action", MAX_LABEL)
    if "href" in entry:
        out["href"] = _safe_href(entry["href"], f"{path}/href", walk)
    if "document" in entry:
        out["document"] = validate(entry["document"], routes=routes, tools=tools)
    if "payload" in entry:
        out["payload"] = walk.payload(entry["payload"], f"{path}/payload")
    for obj_key in ("props", "data", "when", "popout"):
        if obj_key in entry:
            out[obj_key] = walk.json_value(entry[obj_key], f"{path}/{obj_key}", 0, scheme=(obj_key != "data"))
    return out
