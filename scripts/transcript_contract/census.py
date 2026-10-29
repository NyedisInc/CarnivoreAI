
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, DefaultDict, Dict, List, Mapping, Optional, Tuple

_SAFE_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-:.<>]{0,63}$")

_VERSION = re.compile(r"^\d+(?:\.\d+){1,3}(?:-[A-Za-z]+(?:\.\d+)?)?$")

NON_TOKEN: str = "<non-identifier-key>"

CLAUDE_ENUM_PATHS: Tuple[str, ...] = (
    "subtype", "operation", "userType", "entrypoint", "promptSource",
    "origin.kind", "level", "message.role", "message.type",
    "message.stop_reason", "attachment.type", "toolUseResult.status",
    "permissionMode", "toolDenialKind",
)


def json_type(value: Any) -> str:
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


def safe_version(value: Any) -> Optional[str]:
    if isinstance(value, str) and _VERSION.match(value):
        return value
    return None


def version_key(version: str) -> Tuple[int, ...]:
    numeric, _, pre = version.partition("-")
    head = tuple(int(part) for part in numeric.split("."))
    tail = tuple(int(p) for p in re.findall(r"\d+", pre))
    return head + ((0,) + tail if pre else (1,))


class _ShapeTable:

    def __init__(self) -> None:
        self.count: int = 0
        self.keys: Counter = Counter()
        self.types: DefaultDict[str, Counter] = defaultdict(Counter)
        self.versions: Counter = Counter()
        self.key_versions: DefaultDict[str, set] = defaultdict(set)

    def observe(self, obj: Mapping[str, Any], version: Optional[str]) -> None:
        self.count += 1
        for key, value in obj.items():
            name = safe_token(key)
            self.keys[name] += 1
            self.types[name][json_type(value)] += 1
            if version:
                self.key_versions[name].add(version)
        if version:
            self.versions[version] += 1

    def to_json(self) -> Dict[str, Any]:
        ordered = sorted(self.versions, key=version_key)
        return {
            "count": self.count,
            "first_version": ordered[0] if ordered else None,
            "last_version": ordered[-1] if ordered else None,
            "keys": {
                k: {"count": n, "types": dict(sorted(self.types[k].items())),
                    "first_version": min(self.key_versions[k], key=version_key, default=None),
                    "last_version": max(self.key_versions[k], key=version_key, default=None)}
                for k, n in sorted(self.keys.items())
            },
        }


def _dig(obj: Mapping[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class ShapeCensus:

    def __init__(self) -> None:
        self.lines: Counter = Counter()
        self.tables: DefaultDict[str, _ShapeTable] = defaultdict(_ShapeTable)
        self.enums: DefaultDict[str, Counter] = defaultdict(Counter)
        self.versions: Counter = Counter()

    def _table(self, name: str, obj: Mapping[str, Any], version: Optional[str]) -> None:
        self.tables[name].observe(obj, version)

    def observe_status(self, family: str, status: str) -> None:
        self.lines[f"{family}:{status}"] += 1

    def observe_claude(self, obj: Mapping[str, Any], scope: str,
                       file_version: Optional[str] = None) -> Optional[str]:
        self.lines[f"claude:{scope}:ok"] += 1
        rtype = safe_token(obj.get("type")) if "type" in obj else "<no-type>"
        own = safe_version(obj.get("version"))
        if own:
            self.versions[f"claude:{own}"] += 1
        version = own or file_version
        self._table(f"claude:record:{rtype}", obj, version)
        for path in CLAUDE_ENUM_PATHS:
            value = _dig(obj, path)
            if value is not None:
                self.enums[f"claude:{rtype}:{path}"][safe_token(value)] += 1
        sub = obj.get("subtype")
        if isinstance(sub, str):
            self._table(f"claude:system:{safe_token(sub)}", obj, version)
        for nested in ("message", "attachment", "toolUseResult", "origin", "snapshot",
                       "compactMetadata", "data", "mcpMeta"):
            inner = obj.get(nested)
            if isinstance(inner, dict):
                kind = safe_token(inner.get("type")) if nested == "attachment" else "*"
                self._table(f"claude:{rtype}.{nested}:{kind}", inner, version)
            elif isinstance(inner, list) and nested == "toolUseResult":
                self.enums[f"claude:{rtype}:toolUseResult[]"]["array"] += 1
        message = obj.get("message")
        if isinstance(message, dict):
            usage = message.get("usage")
            if isinstance(usage, dict):
                self._table("claude:message.usage", usage, version)
            content = message.get("content")
            self.enums[f"claude:{rtype}:message.content"][json_type(content)] += 1
            if isinstance(content, list):
                role = safe_token(message.get("role"))
                for block in content:
                    if isinstance(block, dict):
                        btype = safe_token(block.get("type"))
                        self._table(f"claude:block:{role}:{btype}", block, version)
                        self._nested_block(btype, block, version)
                    else:
                        self.enums[f"claude:{rtype}:block"][json_type(block)] += 1
        return version

    def _nested_block(self, btype: str, block: Mapping[str, Any], version: Optional[str]) -> None:
        inner = block.get("content")
        if btype == "tool_result":
            self.enums["claude:block:tool_result:content"][json_type(inner)] += 1
            if isinstance(inner, list):
                for item in inner:
                    if isinstance(item, dict):
                        self._table(f"claude:tool_result_item:{safe_token(item.get('type'))}",
                                    item, version)
        source = block.get("source")
        if isinstance(source, dict):
            self._table(f"claude:block_source:{btype}:{safe_token(source.get('type'))}",
                        source, version)

    def observe_codex(self, obj: Mapping[str, Any]) -> None:
        self.lines["codex:ok"] += 1
        ltype = safe_token(obj.get("type")) if "type" in obj else "<no-type>"
        self._table(f"codex:line:{ltype}", obj, None)
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            self.enums[f"codex:{ltype}:payload"][json_type(payload)] += 1
            return
        ptype = safe_token(payload.get("type")) if "type" in payload else "<no-type>"
        version = safe_version(payload.get("cli_version"))
        if version:
            self.versions[f"codex:{version}"] += 1
        self._table(f"codex:payload:{ltype}:{ptype}", payload, version)
        for key in ("role", "originator", "source", "status", "model_provider"):
            value = payload.get(key)
            if isinstance(value, str):
                self.enums[f"codex:{ltype}:{ptype}:{key}"][safe_token(value)] += 1
        for key in ("content", "summary"):
            items = payload.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        self._table(f"codex:item:{ptype}.{key}:{safe_token(item.get('type'))}",
                                    item, version)
        info = payload.get("info")
        if isinstance(info, dict):
            self._table(f"codex:payload:{ltype}:{ptype}.info", info, version)

    def to_json(self) -> Dict[str, Any]:
        def ordered_versions(prefix: str) -> List[Dict[str, Any]]:
            rows = [(k.split(":", 1)[1], n) for k, n in self.versions.items() if k.startswith(prefix)]
            return [{"version": v, "lines": n} for v, n in sorted(rows, key=lambda r: version_key(r[0]))]

        return {
            "lines": dict(sorted(self.lines.items())),
            "claude_versions": ordered_versions("claude:"),
            "codex_versions": ordered_versions("codex:"),
            "shapes": {k: t.to_json() for k, t in sorted(self.tables.items())},
            "enums": {k: dict(c.most_common()) for k, c in sorted(self.enums.items())},
        }

    def merge(self, other: "ShapeCensus") -> None:
        self.lines.update(other.lines)
        self.versions.update(other.versions)
        for name, counter in other.enums.items():
            self.enums[name].update(counter)
        for name, table in other.tables.items():
            mine = self.tables[name]
            mine.count += table.count
            mine.keys.update(table.keys)
            mine.versions.update(table.versions)
            for key, seen in table.key_versions.items():
                mine.key_versions[key] |= seen
            for key, counter in table.types.items():
                mine.types[key].update(counter)
