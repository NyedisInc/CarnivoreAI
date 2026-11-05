from __future__ import annotations

import re
from pathlib import Path

from src.models.sessions import Session, SessionInfo

REPO_ROOT = Path(__file__).resolve().parents[3]
TYPES_TS = REPO_ROOT / "web" / "src" / "opscenter" / "api" / "types.ts"

NOT_ON_THE_WIRE: dict[str, dict[str, str]] = {"SessionInfo": {}, "Session": {}}


def ts_interface_fields(source: str, name: str) -> set[str]:
    start = re.search(rf"export interface {re.escape(name)}\b[^{{]*\{{", source)
    if not start:
        return set()
    depth, i, body = 1, start.end(), []
    while i < len(source) and depth:
        ch = source[i]
        depth += (ch == "{") - (ch == "}")
        body.append(ch)
        i += 1
    text = "".join(body)
    fields: set[str] = set()
    depth = 0
    for line in text.splitlines():
        if depth == 0:
            m = re.match(r"\s*(?:readonly\s+)?([A-Za-z_]\w*)\??\s*:", line)
            if m:
                fields.add(m.group(1))
        depth += line.count("{") - line.count("}")
    return fields


def missing_fields(model: type, ts_name: str) -> list[str]:
    declared = ts_interface_fields(TYPES_TS.read_text(encoding="utf-8"), ts_name)
    skip = set(NOT_ON_THE_WIRE.get(model.__name__, {}))
    return sorted(set(model.model_fields) - declared - skip)


def test_session_info_wrapper_fields_all_in_ts() -> None:
    assert missing_fields(SessionInfo, "SessionInfo") == []


def test_session_nested_fields_all_in_ts() -> None:
    assert missing_fields(Session, "SessionRow") == []


def test_extractor_goes_red_on_a_fixture() -> None:
    src = "export interface T {\n  a: number;\n  b?: { inner: string };\n}\n"
    assert ts_interface_fields(src, "T") == {"a", "b"}
    assert ts_interface_fields(src, "Nope") == set()
