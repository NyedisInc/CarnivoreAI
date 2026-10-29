
from __future__ import annotations

from typing import List, Optional, Set

from src.core.bookmarks.errors import EntryNotFound
from src.core.bookmarks.transcript_index import Node, TranscriptIndex


def _next_on_path(index: TranscriptIndex, node: Node, live: Set[str]) -> Optional[Node]:
    kids = index.children.get(node.uuid) or []
    if not kids:
        return None
    for uuid in kids:
        if uuid in live:
            return index.nodes[uuid]
    return index.nodes[kids[-1]]


def chain_to(index: TranscriptIndex, end: Node) -> List[Node]:
    out: List[Node] = []
    seen: Set[str] = set()
    cursor: Optional[str] = end.uuid
    while cursor and cursor in index.nodes and cursor not in seen:
        seen.add(cursor)
        node = index.nodes[cursor]
        out.append(node)
        cursor = node.parent
    out.reverse()
    return out


def turn_end(index: TranscriptIndex, prompt: Node, live: Set[str]) -> Node:
    cursor = prompt
    while True:
        nxt = _next_on_path(index, cursor, live)
        if nxt is None or nxt.stop:
            return cursor
        cursor = nxt


def _open_tool_uses(chain: List[Node]) -> Set[str]:
    last_reply: Optional[str] = None
    opened: Set[str] = set()
    answered: Set[str] = set()
    for node in reversed(chain):
        if node.kind == "assistant" and node.msg_id:
            if last_reply is None:
                last_reply = node.msg_id
            if node.msg_id != last_reply:
                break
            opened.update(node.tool_uses)
        elif last_reply is not None and node.kind == "assistant":
            break
        elif last_reply is None:
            answered.update(node.tool_results)
    return opened - answered


def complete(index: TranscriptIndex, start: Node, live: Set[str]) -> Node:
    pending = _open_tool_uses(chain_to(index, start))
    cursor = start
    while True:
        nxt = _next_on_path(index, cursor, live)
        if nxt is None or nxt.stop:
            return cursor
        same_reply = nxt.kind == "assistant" and cursor.kind == "assistant" and nxt.msg_id and nxt.msg_id == cursor.msg_id
        if same_reply:
            pending.update(nxt.tool_uses)
        elif pending and nxt.kind != "assistant":
            pending.difference_update(nxt.tool_results)
        else:
            return cursor
        cursor = nxt


def with_parallel_results(index: TranscriptIndex, chain: List[Node]) -> List[Node]:
    on_chain = {n.uuid for n in chain}
    answered = {r for n in chain for r in n.tool_results}
    out: List[Node] = []
    group: List[Node] = []
    for i, node in enumerate(chain):
        out.append(node)
        if node.kind != "assistant" or not node.msg_id:
            group = []
            continue
        group = group + [node] if group and group[-1].msg_id == node.msg_id else [node]
        nxt = chain[i + 1] if i + 1 < len(chain) else None
        if nxt is not None and nxt.kind == "assistant" and nxt.msg_id == node.msg_id:
            continue
        uses = {u for block in group for u in block.tool_uses}
        for block in group:
            for kid in index.children.get(block.uuid) or []:
                hanging = index.nodes[kid]
                if (kid not in on_chain and hanging.kind == "user" and hanging.tool_results
                        and set(hanging.tool_results) & uses and not set(hanging.tool_results) <= answered):
                    out.append(hanging)
                    answered.update(hanging.tool_results)
    return out


def compact_summary_of(index: TranscriptIndex, node: Node) -> Node:
    if node.kind == "system" and node.logical_parent and node.parent is None:
        kids = index.children.get(node.uuid) or []
        if kids:
            return index.nodes[kids[0]]
    return node


def kept_chain(index: TranscriptIndex, entry_uuid: str) -> List[Node]:
    node = index.nodes.get(entry_uuid)
    if node is None:
        raise EntryNotFound("that point is not in this conversation's transcript")
    node = compact_summary_of(index, node)
    live = {n.uuid for n in index.active_path()}
    end = turn_end(index, node, live) if node.prompt else complete(index, node, live)
    return with_parallel_results(index, chain_to(index, end))
