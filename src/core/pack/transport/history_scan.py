
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import BinaryIO, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.pack.transport import history_objects as objects
from src.core.pack.transport import lfs_scan
from src.core.pack.transport.history_objects import HistoryBudgetExceeded, HistoryScanFailed

logger = structlog.get_logger()

PUSHED_REF = "HEAD"

Detector = Callable[[Callable[[], BinaryIO], List[int]], bool]


@dataclass(frozen=True)
class Hit:

    kind: str
    object_id: str


def resolve_head(root: str) -> Optional[str]:
    done = objects.git(root, "rev-parse", "--verify", "-q", f"{PUSHED_REF}^{{commit}}")
    commit = done.stdout.decode("ascii", "replace").strip()
    if done.returncode == 0 and commit:
        return commit
    if done.returncode == 1 and not commit:
        return None
    raise HistoryScanFailed("rev_parse")


def message_bytes(commit: bytes) -> bytes:
    _head, sep, body = commit.partition(b"\n\n")
    return body if sep else b""


def _scan_objects(root: str, sizes: Dict[str, Tuple[str, int]], holds: Detector, remaining: List[int]) -> Tuple[List[Hit], Dict[str, str]]:
    hits: List[Hit] = []
    pointers: Dict[str, str] = {}
    for group in objects.batches(sizes):
        for object_id, content in objects.read_batch(root, group):
            if sizes[object_id][0] == "commit":
                message = message_bytes(bytes(content))
                if message and holds(lambda message=message: io.BytesIO(message), remaining):
                    hits.append(Hit("message", object_id))
                continue
            if holds(lambda content=content: objects.ViewStream(content), remaining):
                hits.append(Hit("blob", object_id))
            oid = lfs_scan.pointer_oid(bytes(content)) if len(content) < lfs_scan.MAX_POINTER_BYTES else None
            if oid:
                pointers.setdefault(oid, object_id)
    return hits, pointers


def _scan_lfs(root: str, pointers: Dict[str, str], paths: Dict[str, str], holds: Detector, remaining: List[int]) -> List[Hit]:
    if not pointers:
        return []
    git_dir = objects.git_common_dir(root)
    sizes = lfs_scan.object_sizes(git_dir, {oid: paths[blob] for oid, blob in pointers.items()})
    if sum(sizes.values()) > remaining[0]:
        raise HistoryBudgetExceeded([paths[pointers[oid]] for oid in sorted(sizes, key=sizes.__getitem__, reverse=True)])
    hits: List[Hit] = []
    for oid in sizes:
        path = lfs_scan.object_path(git_dir, oid)
        try:
            if holds(lambda path=path: path.open("rb"), remaining):
                hits.append(Hit("lfs", pointers[oid]))
        except OSError:
            raise HistoryScanFailed("lfs_read") from None
    return hits


def _names(root: str, rev: str, staged: bool, paths: Dict[str, str], hits: List[Hit]) -> List[str]:
    shorts: Dict[str, str] = {}
    added: Dict[str, str] = {}
    if not staged:
        shorts, added = objects.commit_names(root, rev, {h.object_id for h in hits if h.kind != "message"},
                                             {h.object_id for h in hits if h.kind == "message"})
    named: List[str] = []
    for hit in hits:
        if hit.kind == "message":
            named.append(f"commit {shorts.get(hit.object_id, hit.object_id[:12])} message")
            continue
        where = "staged" if staged else (f"commit {added[hit.object_id]}" if added.get(hit.object_id) else "")
        label = ", ".join(part for part in ("lfs object" if hit.kind == "lfs" else "", where) if part)
        named.append(f"{paths[hit.object_id]} ({label})" if label else paths[hit.object_id])
    return named


def history_hits(root: str, rev: str, *, staged: bool, holds_secret: Detector, budget: int) -> List[str]:
    paths = objects.reachable_objects(root, rev)
    sizes = objects.object_sizes(root, list(paths))
    if sum(size for _kind, size in sizes.values()) > budget:
        biggest = sorted(sizes, key=lambda object_id: sizes[object_id][1], reverse=True)
        raise HistoryBudgetExceeded([paths[i] or f"commit {i[:12]}" for i in biggest])
    remaining = [budget]
    hits, pointers = _scan_objects(root, sizes, holds_secret, remaining)
    hits += _scan_lfs(root, pointers, paths, holds_secret, remaining)
    logger.info("pack_publish_history_scanned", objects=len(sizes), lfs_objects=len(pointers), staged=staged,
                bytes=budget - remaining[0], hits=len(hits))
    return _names(root, rev, staged, paths, hits)
