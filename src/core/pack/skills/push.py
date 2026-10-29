
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import structlog

from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.skills.bundle import BundleError, build_bundle
from src.core.pack.skills.scan import scan_root
from src.core.pack.transport import blobs

logger = structlog.get_logger()

OFFER_PATH = "/federation/pack/skills/offer"
APPLY_PATH = "/federation/pack/skills/apply"
BLOBS_PATH = "/federation/pack/skills/blobs"
CAP_PER_DIGEST = 3
BACKOFF_SECONDS = (30.0, 60.0, 300.0)
REASON_KEEPS_CHANGING = "keeps changing on {label}"

Pair = tuple[str, str]
Republish = Callable[[int], Optional[dict[str, Any]]]
WIRE_ERRORS = (PeerUnreachable, PeerRefused, TimeoutError, asyncio.TimeoutError, OSError, blobs.BlobError, BundleError)


@dataclass
class PeerState:

    label: str = ""
    busy: bool = False
    fails: int = 0
    next_at: float = 0.0
    error: str = ""
    last_try: Optional[tuple[Any, ...]] = None
    pending_key: Optional[tuple[Any, ...]] = None
    counts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    capped: dict[Pair, str] = field(default_factory=dict)

    def failed(self, now: float) -> None:
        self.fails += 1
        self.next_at = now + BACKOFF_SECONDS[min(self.fails, len(BACKOFF_SECONDS)) - 1]

    def reset(self) -> None:
        self.fails, self.next_at, self.last_try, self.error = 0, 0.0, None, ""

    def conflicts(self) -> list[list[str]]:
        return [[f, n, REASON_KEEPS_CHANGING.format(label=self.label or "that computer")] for (f, n) in sorted(self.capped)]


def _detail_code(answer: Any) -> str:
    detail = answer.get("detail") if isinstance(answer, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else ""


def _clean_need(answer: Any, digests: Mapping[Pair, str]) -> list[Pair]:
    rows = answer.get("need") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        return []
    return [(r[0], r[1]) for r in rows if isinstance(r, list) and len(r) == 2 and (r[0], r[1]) in digests]


def build_outgoing(roots: Mapping[str, Path], pairs: list[Pair], digests: Mapping[Pair, str], out: Path) -> list[Pair]:
    scans = {family: scan_root(root, family) for family, root in roots.items() if family in {p[0] for p in pairs}}
    items, sent = [], []
    for family, name in pairs:
        found = scans[family].skills.get(name) if family in scans else None
        if found is not None and found.problem is None and found.digest == digests[(family, name)]:
            items.append((family, name, roots[family] / name, found.files))
            sent.append((family, name))
    if items:
        out.parent.mkdir(parents=True, exist_ok=True)
        build_bundle(out, items)
    return sent


async def deliver(request: blobs.Request, doc: dict[str, Any], peer: PeerState, roots: Mapping[str, Path], outbox: Path,
                  republish: Republish, now: Callable[[], float], refs_ok: bool = False) -> str:
    try:
        status, answer = await request("POST", OFFER_PATH, json=doc)
        if status == 409 and _detail_code(answer) == "stale":
            newer = await asyncio.to_thread(republish, int(answer.get("applied_gen") or 0) + 1)
            if newer is None:
                return "stale"
            doc = newer
            status, answer = await request("POST", OFFER_PATH, json=doc)
        if status == 403:
            peer.error = _detail_code(answer) or "refused"
            return "refused"
        if status != 200 or not isinstance(answer, dict):
            peer.failed(now())
            return "failed"
        peer.error = ""
        digests: dict[Pair, str] = {(f, n): d for f, n, d in doc["skills"]}
        need = _clean_need(answer, digests)
        sendable = [p for p in need if peer.counts.get((p[0], p[1], digests[p]), 0) < CAP_PER_DIGEST]
        peer.capped = {p: digests[p] for p in need if p not in sendable}
        blob_id: Optional[str] = None
        sha: Optional[str] = None
        sent: list[Pair] = []
        bundle = outbox / f"out-{blobs.new_id()}.tgz"
        try:
            if sendable:
                sent = await asyncio.to_thread(build_outgoing, roots, sendable, digests, bundle)
            if sent:
                sha = await asyncio.to_thread(blobs.file_sha256, str(bundle))
                blob_id = await blobs.send_file(request, str(bundle), blob_id=blobs.new_id(), kind="tar", base_path=BLOBS_PATH)
        finally:
            await asyncio.to_thread(_remove, bundle)
        body: dict[str, Any] = {"gen": doc["gen"], "blob_id": blob_id, "blob_sha256": sha}
        install: list[Pair] = []
        if refs_ok:
            ref_digest = {(e[0], e[1]): e[5] for e in doc.get("warez", [])}
            wanted = _clean_need({"need": answer.get("need_refs")}, ref_digest)
            install = [p for p in wanted if peer.counts.get((p[0], p[1], ref_digest[p]), 0) < CAP_PER_DIGEST]
            peer.capped.update({p: ref_digest[p] for p in wanted if p not in install})
            body["install"] = [list(p) for p in install]
        status, answer = await request("POST", APPLY_PATH, json=body)
        if status == 409 and _detail_code(answer) == "stale":
            return "stale"
        if status != 202:
            peer.failed(now())
            return "failed"
        for family, name in sent:
            key = (family, name, digests[(family, name)])
            peer.counts[key] = peer.counts.get(key, 0) + 1
        for family, name in install:
            key = (family, name, ref_digest[(family, name)])
            peer.counts[key] = peer.counts.get(key, 0) + 1
        peer.fails, peer.next_at = 0, 0.0
        return "synced"
    except WIRE_ERRORS as exc:
        logger.info("pack_skills_deliver_failed", error=type(exc).__name__)
        peer.failed(now())
        return "failed"


def _remove(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("pack_skills_outbox_remove_failed", errno=exc.errno)
