
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core import db
from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.span import memory_mirror
from src.core.swarm import body_create, memory, store

logger = structlog.get_logger()

BODY_PATH = "/federation/swarm/body"
SLEEP_PATH = "/federation/swarm/body/{agent}/sleep"
WRITEBACK_PATH = "/federation/swarm/memory/writeback"


def peer_for(wanted: str) -> Any:
    from src.api import peer_auth

    with closing(peer_auth.open_db()) as conn:
        peers = peer_hosts.list_peers(conn)
    for peer in peers:
        if wanted in (peer.key, peer.peer_install_id) or wanted.lower() == str(peer.label).lower():
            return peer
    raise body_create.CreateRefused(f"no paired computer matches {wanted[:64]!r}")


def _client(peer: Any) -> Any:
    links = peer_links.LINKS
    client = links.client(peer.peer_install_id) if links is not None else None
    if client is None:
        raise body_create.CreateRefused(f"{peer.label} is not connected; retry when it is")
    return client


async def _post(peer: Any, path: str, payload: Dict[str, Any], timeout: float = 45) -> Dict[str, Any]:
    try:
        answer = await _client(peer).request("POST", path, json=payload, timeout=timeout)
    except (PeerUnreachable, PeerRefused) as exc:
        raise body_create.CreateRefused(f"{peer.label} did not answer ({type(exc).__name__})") from exc
    if answer.status_code != 200:
        try:
            detail = answer.json().get("detail")
            code = detail.get("code") if isinstance(detail, dict) else str(detail)
        except ValueError:
            code = str(answer.status_code)
        raise body_create.CreateRefused(f"{peer.label} refused ({code})")
    data = answer.json()
    return data if isinstance(data, dict) else {}


def _relayed_account(conn: sqlite3.Connection, peer_install_id: str) -> Optional[str]:
    from src.core.pack.relay import targets

    on = [t.account_key for t in targets.list_all(conn) if t.target_install_id == peer_install_id and t.enabled]
    return on[0] if on else None


def _packet(agent: Dict[str, Any], state_dir: Path, peer_install_id: str) -> Dict[str, Any]:
    if agent["rank"] not in ("feature", "task"):
        raise body_create.CreateRefused("only a feature or task agent runs on another computer")
    with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
        parent = store.get_agent(conn, agent["parent_id"]) if agent.get("parent_id") is not None else None
        uid = conn.execute("SELECT uid FROM projects WHERE id = ?", (agent.get("project_id"),)).fetchone()
        account = _relayed_account(conn, peer_install_id)
    if not uid or not uid[0]:
        raise body_create.CreateRefused("the agent's project has no uid yet")
    files: List[Dict[str, str]] = []
    if agent["memory_scope"] == memory.SCOPE_PROJECT:
        files = memory_mirror.collect(memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"]))
    keys = ("slug", "rank", "display_name", "job", "goal", "persona", "effort", "effort_reason", "harness", "model",
            "launch_profile", "naming_family")
    packet: Dict[str, Any] = {k: agent.get(k) for k in keys if agent.get(k) not in (None, "")}
    packet.update(home_agent_id=agent["id"], project_uid=uid[0], character_seed=str(agent["character_seed"]),
                  parent_name=parent["display_name"] if parent else None, parent_slug=parent["slug"] if parent else None,
                  memory_files=files, account_key=account)
    return {k: v for k, v in packet.items() if v is not None}


async def _confirm(peer: Any, created: Dict[str, Any]) -> Any:
    from src.api import peer_auth
    from src.core.crosstalk import spawn_remote
    from src.core.federation import peer_listing
    from src.core.mcp import federated

    await peer_listing.refresh(peer, peer_links.LINKS, peer_auth.open_db, force=True)
    child = next((i for i in await federated.peer_infos(force=True) if i.host_key == peer.key
                  and i.tmux_session == created.get("tmux_name")), None)
    if not spawn_remote.same_created_child(child, created, peer.peer_install_id):
        raise body_create.CreateRefused(f"{peer.label} made the body but its pane identity was not confirmed")
    return child


async def _carry_code(agent: Dict[str, Any], peer: Any) -> None:
    from src.api import project_transport_routes as transport_routes
    from src.config import settings as app_settings
    from src.core.pack.transport import bundles

    def read() -> Optional[Dict[str, Any]]:
        with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT uid, root, air_gap FROM projects WHERE id = ?", (agent.get("project_id"),)).fetchone()
        return dict(row) if row and bundles.is_repo(row["root"]) else None

    project = await asyncio.to_thread(read)
    if project is not None:
        outcome = await transport_routes.carry_to(project, peer.peer_install_id, str(peer.label), False)
        logger.info("remote_body_code_carried", machine=peer.key, sent=outcome.get("sent"), error=outcome.get("error"))


async def start(app_state: Any, agent: Dict[str, Any], mode: str) -> body_create.BodyIdentity:
    from src.config import settings as app_settings

    state_dir = app_settings.get_state_dir()
    peer = await asyncio.to_thread(peer_for, agent["host_key"])
    await asyncio.to_thread(body_create._prepare, state_dir, agent)
    fresh = await _row(agent["id"]) or agent
    packet = await asyncio.to_thread(_packet, fresh, state_dir, peer.peer_install_id)
    await _carry_code(fresh, peer)
    created = await _post(peer, BODY_PATH, packet)
    child = await _confirm(peer, created)
    row_id = int(child.session_row_id)

    def bind() -> None:
        with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
            if agent["session_row_id"] is None:
                store.set_session_row(conn, agent["id"], row_id)
            elif agent["session_row_id"] != row_id:
                raise body_create.CreateRefused("the host answered with a different session than the agent's own")

    await asyncio.to_thread(bind)
    return body_create.BodyIdentity(child.session.id, row_id, child.session_uuid or "", str(child.tmux_session), child.session.tmux_created_epoch)


async def _row(agent_id: int) -> Optional[Dict[str, Any]]:
    from src.core.swarm import body

    return await body.run_db(lambda c: store.get_agent(c, agent_id))


async def sleep(app_state: Any, agent: Dict[str, Any]) -> None:
    from src.core.mcp import federated
    from src.core.swarm import body

    info = await body.live_info(app_state, agent)
    if info is None:
        return
    peer = await asyncio.to_thread(peer_for, agent["host_key"])
    try:
        await _post(peer, SLEEP_PATH.format(agent=agent["id"]), {"teardown": False})
    except body_create.CreateRefused as exc:
        raise RuntimeError(str(exc)) from exc
    answer = await federated.forward(info, "POST", "/sessions/{session_uuid}/sleep")
    if answer.get("status") not in (None, "asleep"):
        raise RuntimeError(str(answer.get("detail") or "the body would not close"))


async def paste(info: Any, text: str) -> None:
    from src.core.mcp import federated

    await federated.forward(info, "POST", "/sessions/{session_id}/skills/one-shot", {"text": text})
