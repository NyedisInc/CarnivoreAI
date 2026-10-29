
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import httpx
import structlog

from src.core.computers import direction
from src.core.federation import peer_hosts, peer_http, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

logger = structlog.get_logger()

DEADLINE_SECONDS = 4.0


@dataclass(frozen=True)
class PeerAnswer:
    """One peer's part of a merged answer: ``data`` is its JSON, or None with a ``reason`` word when it could not answer."""

    host_key: str
    label: str
    data: Optional[Any]
    reason: str = ""
    code: str = ""


def is_peer_call(request: Any) -> bool:
    return getattr(request.state, "peer_grant", None) is not None


def unavailable_marker(answers: List[PeerAnswer]) -> List[Dict[str, str]]:
    """The named ``peer_unavailable`` list: one ``{host_key, host_label, reason}`` per peer that did not answer. PURE."""
    return [{"host_key": a.host_key, "host_label": a.label, "reason": a.reason} for a in answers if a.data is None]


def _error_code(reply: Any) -> str:
    try:
        detail = reply.json().get("detail")
    except (ValueError, AttributeError, RecursionError):
        return ""
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else ""


async def _ask(peer: peer_hosts.PeerRow, links: "peer_links.PeerLinks", path: str) -> PeerAnswer:
    client = links.client(peer.peer_install_id)
    if client is None:
        return PeerAnswer(peer.key, peer.label, None, "disconnected")
    try:
        reply = await asyncio.wait_for(client.request("GET", path, max_body=peer_http.MAX_LISTING_BODY), DEADLINE_SECONDS)
        if reply.status_code != 200:
            return PeerAnswer(peer.key, peer.label, None, f"http_{reply.status_code}", _error_code(reply))
        return PeerAnswer(peer.key, peer.label, reply.json())
    except asyncio.TimeoutError:
        return PeerAnswer(peer.key, peer.label, None, "timeout")
    except PeerUnreachable:
        return PeerAnswer(peer.key, peer.label, None, "unreachable")
    except PeerRefused as exc:
        return PeerAnswer(peer.key, peer.label, None, exc.code)
    except (httpx.HTTPError, ValueError, RecursionError):
        return PeerAnswer(peer.key, peer.label, None, "bad_answer")


async def ask_peers(path: str, open_db: Callable[[], sqlite3.Connection],
                    links: Optional["peer_links.PeerLinks"] = None, only: Optional[str] = None) -> List[PeerAnswer]:
    links = links if links is not None else peer_links.LINKS
    if links is None:
        return []
    try:
        def read() -> List[peer_hosts.PeerRow]:
            with closing(open_db()) as conn:
                return peer_hosts.list_peers(conn)
        peers = await asyncio.to_thread(read)
    except (sqlite3.Error, OSError) as exc:
        logger.info("peer_fanout_peers_unreadable", reason=type(exc).__name__)
        return []
    peers = [p for p in peers if (only is None or p.key == only) and not direction.is_one_way_toward(p.peer_install_id)]
    return list(await asyncio.gather(*(_ask(p, links, path) for p in peers)))
