
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from src.core.transcript_contract.fields import (
    ARR,
    BOOL,
    OBJ,
    STR,
    UNKNOWN_TYPE,
    Report,
    bind,
    jf,
    json_type,
    safe_token,
)


@dataclass(frozen=True, kw_only=True)
class BlockSource:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.62")
    media_type: Optional[str] = jf("media_type", STR, required=True, first_seen="1.0.62")
    data: Optional[str] = jf("data", STR, required=True, first_seen="1.0.62")


def _source(value: Any, path: str, report: Report) -> Optional[BlockSource]:
    return bind(BlockSource, value, path, report)


@dataclass(frozen=True, kw_only=True)
class TextBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.61")
    text: Optional[str] = jf("text", STR, required=True, first_seen="1.0.61")


@dataclass(frozen=True, kw_only=True)
class ThinkingBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.62")
    thinking: Optional[str] = jf("thinking", STR, required=True, first_seen="1.0.62")
    signature: Optional[str] = jf("signature", STR, required=True, first_seen="1.0.62")


@dataclass(frozen=True, kw_only=True)
class ToolUseBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.62")
    id: Optional[str] = jf("id", STR, required=True, first_seen="1.0.62")
    name: Optional[str] = jf("name", STR, required=True, first_seen="1.0.62")
    input: Optional[Mapping[str, Any]] = jf("input", OBJ, required=True, first_seen="1.0.62")
    caller: Optional[Mapping[str, Any]] = jf("caller", OBJ, first_seen="2.1.39")


@dataclass(frozen=True, kw_only=True)
class FallbackBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.197")
    from_: Optional[Mapping[str, Any]] = jf("from", OBJ, required=True, first_seen="2.1.197")
    to: Optional[Mapping[str, Any]] = jf("to", OBJ, required=True, first_seen="2.1.197")


@dataclass(frozen=True, kw_only=True)
class ImageBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.62")
    source: Optional[BlockSource] = jf("source", OBJ, required=True, first_seen="1.0.62",
                                       nested=_source)


@dataclass(frozen=True, kw_only=True)
class DocumentBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.69")
    source: Optional[BlockSource] = jf("source", OBJ, required=True, first_seen="1.0.69",
                                       nested=_source)


@dataclass(frozen=True, kw_only=True)
class ToolReferenceBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.71")
    tool_name: Optional[str] = jf("tool_name", STR, required=True, first_seen="2.1.71")


@dataclass(frozen=True)
class UnknownBlock:

    type: str
    raw: Any


ResultItem = Union[TextBlock, ImageBlock, DocumentBlock, ToolReferenceBlock, UnknownBlock]


def _result_content(value: Any, path: str, report: Report) -> Union[str, Tuple[ResultItem, ...]]:
    if isinstance(value, str):
        return value
    return tuple(_parse_one(item, path, report, RESULT_ITEM_TYPES, "tool_result")
                 for item in value)


@dataclass(frozen=True, kw_only=True)
class ToolResultBlock:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.62")
    tool_use_id: Optional[str] = jf("tool_use_id", STR, required=True, first_seen="1.0.62")
    content: Optional[Union[str, Tuple[ResultItem, ...]]] = jf(
        "content", ARR + STR, first_seen="1.0.62", nested=_result_content)
    is_error: Optional[bool] = jf("is_error", BOOL, first_seen="1.0.62")


Block = Union[TextBlock, ThinkingBlock, ToolUseBlock, FallbackBlock, ImageBlock, DocumentBlock,
              ToolResultBlock, ToolReferenceBlock, UnknownBlock]

ASSISTANT_BLOCK_TYPES: Dict[str, type] = {
    "text": TextBlock, "thinking": ThinkingBlock, "tool_use": ToolUseBlock,
    "fallback": FallbackBlock,
}

USER_BLOCK_TYPES: Dict[str, type] = {
    "text": TextBlock, "tool_result": ToolResultBlock, "image": ImageBlock,
    "document": DocumentBlock,
}

RESULT_ITEM_TYPES: Dict[str, type] = {
    "text": TextBlock, "image": ImageBlock, "document": DocumentBlock,
    "tool_reference": ToolReferenceBlock,
}


def _parse_one(item: Any, path: str, report: Report, table: Mapping[str, type],
               owner: str) -> Block:
    if not isinstance(item, dict):
        kind = f"<{json_type(item)}>"
        report.add(UNKNOWN_TYPE, f"block:{owner}", kind)
        return UnknownBlock(kind, item)
    btype = item.get("type")
    cls = table.get(btype) if isinstance(btype, str) else None
    if cls is None:
        token = safe_token(btype)
        report.add(UNKNOWN_TYPE, f"block:{owner}", token)
        return UnknownBlock(token, item)
    return bind(cls, item, f"{path.rstrip('.')}[{btype}].", report)


def parse_blocks(value: List[Any], path: str, report: Report, role: str) -> Tuple[Block, ...]:
    table = ASSISTANT_BLOCK_TYPES if role == "assistant" else USER_BLOCK_TYPES
    return tuple(_parse_one(item, path, report, table, role) for item in value)
