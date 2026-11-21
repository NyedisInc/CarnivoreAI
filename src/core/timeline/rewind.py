
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.timeline.model import Kind, Pos, TimelineEvent

if TYPE_CHECKING:
    from src.core.bookmarks import transcript_index as graph

log = structlog.get_logger(__name__)

DIVIDER_N: int = 1000
MAX_MAPS: int = 8
VISIBLE_TYPES = frozenset({"user", "assistant"})


@dataclass(frozen=True)
class Fork:

    fork_uuid: str
    abandoned_from: int
    abandoned_to: int
    resumes_at: int


@dataclass(frozen=True)
class RewindMap:

    abandoned: FrozenSet[int] = frozenset()
    forks: Tuple[Fork, ...] = field(default_factory=tuple)


EMPTY = RewindMap()
_maps: "OrderedDict[Tuple[str, int, Optional[str]], RewindMap]" = OrderedDict()
_lock = threading.Lock()


def _branch(index: "graph.TranscriptIndex", root: str, on_path: Set[str]) -> List["graph.Node"]:
    found, stack, seen = [], [root], set()
    while stack:
        uuid = stack.pop()
        if uuid in seen or uuid in on_path or uuid not in index.nodes:
            continue
        seen.add(uuid)
        found.append(index.nodes[uuid])
        stack.extend(index.children.get(uuid, ()))
    return sorted(found, key=lambda node: node.offset)


def _is_branch_root(node: "graph.Node", fork: "graph.Node") -> bool:
    if node.tool_results and not node.prompt:
        return False
    return not (node.kind == "assistant" and node.msg_id and node.msg_id == fork.msg_id)


def _opens_turn(node: "graph.Node") -> bool:
    return node.kind == "user" and not node.tool_results


def _first_live(path: Sequence["graph.Node"], after: int) -> Optional["graph.Node"]:
    return next((node for node in path[after + 1:] if node.kind in VISIBLE_TYPES), None)


def _crosses_compaction(path: Sequence["graph.Node"], position: int) -> bool:
    following = path[position + 1] if position + 1 < len(path) else None
    return following is not None and following.parent is None and following.logical_parent is not None


def compute(index: "graph.TranscriptIndex") -> RewindMap:
    path = index.active_path()
    on_path = {node.uuid for node in path}
    abandoned: Set[int] = set()
    forks: List[Fork] = []
    for position, fork in enumerate(path):
        spans: List["graph.Node"] = []
        for child in index.children.get(fork.uuid, ()):
            node = index.nodes.get(child)
            if node is None or child in on_path or not _is_branch_root(node, fork):
                continue
            spans.extend(_branch(index, child, on_path))
        visible = [n for n in spans if n.kind in VISIBLE_TYPES and not (n.tool_results and not n.prompt)]
        later = _first_live(path, position)
        first_off = min(visible, key=lambda n: n.offset) if visible else None
        if first_off is None or not _opens_turn(first_off) or later is None or not _opens_turn(later) or _crosses_compaction(path, position):
            continue
        abandoned.update(n.offset + n.length for n in spans)
        forks.append(Fork(fork.uuid, min(n.offset for n in spans), max(n.offset + n.length for n in spans), later.offset + later.length))
    return RewindMap(frozenset(abandoned), tuple(forks))


def map_for(real: str) -> RewindMap:
    from src.core.bookmarks import transcript_index as graph  # noqa: PLC0415
    from src.core.bookmarks.errors import TranscriptUnavailable  # noqa: PLC0415

    try:
        index = graph.cached_index(Path(real))
    except TranscriptUnavailable as exc:
        log.warning("timeline_rewind_unavailable", error=str(exc))
        return EMPTY
    key = (real, index.size, index.last_serial)
    with _lock:
        held = _maps.get(key)
        if held is not None:
            _maps.move_to_end(key)
            return held
    built = compute(index) if any(len(kids) > 1 for kids in index.children.values()) else EMPTY
    with _lock:
        _maps[key] = built
        while len(_maps) > MAX_MAPS:
            _maps.popitem(last=False)
    return built


def clear() -> None:
    with _lock:
        _maps.clear()


def _divider(fork: Fork, anchor: TimelineEvent) -> TimelineEvent:
    return TimelineEvent(pos=Pos(conv=anchor.pos.conv, file_key=anchor.pos.file_key, offset=anchor.pos.offset, serial=anchor.pos.serial),
                         n=DIVIDER_N, t=anchor.t, thread=anchor.thread, turn=anchor.turn, kind=Kind.REWIND,
                         data={"fork_uuid": fork.fork_uuid, "abandoned_from": fork.abandoned_from, "abandoned_to": fork.abandoned_to})


def annotate(events: Sequence[TimelineEvent], rewind: RewindMap, include_abandoned: bool) -> Tuple[List[TimelineEvent], FrozenSet[str]]:
    if not rewind.forks:
        return list(events), frozenset()
    resumes: Dict[int, Fork] = {fork.resumes_at: fork for fork in rewind.forks}
    out: List[TimelineEvent] = []
    kept: Set[str] = set()
    placed: Set[int] = set()
    for event in events:
        offset = event.pos.offset
        if offset in rewind.abandoned:
            if not include_abandoned:
                continue
            kept.add(event.id)
        elif offset in resumes and offset not in placed:
            placed.add(offset)
            out.append(_divider(resumes[offset], event))
        out.append(event)
    return out, frozenset(kept)
