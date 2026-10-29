
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Callable, Dict, List, Mapping, Optional

import httpx
import pydantic
import structlog

from src.core.approvals.bounds import bound_item
from src.core.federation import peer_hosts, peer_links, peer_listing
from src.core.federation.pairing import ANSWER_ALL_MINOR
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.hosts.identity import REMOTE_ID_PREFIX, remote_session_id
from src.models.dialogs import ApprovalItem

logger = structlog.get_logger()

DEADLINE_SECONDS: float = 1.5
MAX_PER_PEER: int = 100


def serve(items: List[Dict[str, Any]], install_id: Optional[str]) -> List[Dict[str, Any]]:
    return [{**i, "origin_install_id": install_id} for i in items
            if i.get("source") == "dialog" and i.get("host") == "local"
            and not str(i.get("session_id", "")).startswith(REMOTE_ID_PREFIX)]


def accept(raw: Any, peer: "peer_hosts.PeerRow") -> Optional[ApprovalItem]:
    if not isinstance(raw, Mapping):
        return None
    try:
        item = ApprovalItem.model_validate(bound_item(dict(raw)))
    except pydantic.ValidationError as exc:
        logger.warning("peer_approval_item_dropped", peer=peer.key, item_id=str(raw.get("id"))[:80],
                       fields=sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]}))
        return None
    if (item.origin_install_id != peer.peer_install_id or item.host != "local" or item.source != "dialog"
            or not item.tmux_session or item.session_id.startswith(REMOTE_ID_PREFIX)):
        return None
    try:
        wire = remote_session_id(peer.key, item.tmux_session)
    except ValueError:
        return None
    return item.model_copy(update={"id": f"{REMOTE_ID_PREFIX}{peer.key}:{item.id}", "host": peer.key,
                                   "host_label": peer.label or None,
                                   "session_id": wire})


def without_batch(item: ApprovalItem) -> ApprovalItem:
    return item.model_copy(update={"questions": [], "questions_fingerprint": None, "questions_state": None})


async def _one(peer: "peer_hosts.PeerRow", links: "peer_links.PeerLinks") -> List[Dict[str, Any]]:
    client = links.client(peer.peer_install_id)
    if client is None:
        return []
    try:
        reply = await asyncio.wait_for(client.request("GET", "/approvals"), DEADLINE_SECONDS)
        if reply.status_code == 404:
            logger.debug("peer_approvals_route_missing", peer=peer.key)
            return []
        if reply.status_code != 200:
            logger.info("peer_approvals_unavailable", peer=peer.key, status=reply.status_code)
            return []
        raw = reply.json().get("items")
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.info("peer_approvals_unavailable", peer=peer.key, reason=type(exc).__name__)
        return []
    if not isinstance(raw, list):
        return []
    kept = [i for i in (accept(r, peer) for r in raw[:MAX_PER_PEER]) if i is not None]
    if links.minor(peer.peer_install_id) < ANSWER_ALL_MINOR:
        kept = [without_batch(i) for i in kept]
    return [i.model_dump() for i in kept]


async def peer_items(open_db: Callable[[], sqlite3.Connection],
                     links: Optional["peer_links.PeerLinks"] = None) -> List[Dict[str, Any]]:
    links = links or peer_links.LINKS
    if links is None:
        return []
    try:
        peers = await asyncio.to_thread(peer_listing.read_peers, open_db)
    except (sqlite3.Error, OSError):
        return []
    done = await asyncio.gather(*(_one(p, links) for p in peers), return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for peer, result in zip(peers, done):
        if isinstance(result, BaseException):
            logger.warning("peer_approvals_failed", peer=peer.key, error_type=type(result).__name__)
        else:
            out += result
    return out
