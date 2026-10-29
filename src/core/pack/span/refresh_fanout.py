
from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

logger = structlog.get_logger()

PEER_PATH = "/federation/pack/refresh"
SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "refresh-local-install.sh"
STALE_SECONDS = 30 * 60
_background: set = set()


async def fan_out(project: Optional[str], install: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if project:
        from src.api import project_transport_routes as transport

        out["code"] = await transport.sync_project(project, transport.SyncBody())
    if install:
        out["install"] = await _ask_install()
    return out


async def _ask_install() -> List[Dict[str, Any]]:
    from src.api import peer_auth

    with closing(peer_auth.open_db()) as conn:
        peers = peer_hosts.list_peers(conn)
    links = peer_links.LINKS
    results: List[Dict[str, Any]] = []
    for peer in peers:
        client = links.client(peer.peer_install_id) if links is not None else None
        if client is None:
            results.append({"machine": str(peer.label), "status": "not_connected"})
            continue
        try:
            answer = await client.request("POST", PEER_PATH, json={}, timeout=15)
        except (PeerUnreachable, PeerRefused) as exc:
            results.append({"machine": str(peer.label), "status": type(exc).__name__})
            continue
        results.append({"machine": str(peer.label), "status": "started" if answer.status_code == 202 else f"refused_{answer.status_code}"})
    return results


def _lock_dir() -> Path:
    from src.config import settings as app_settings

    return Path(app_settings.get_state_dir()) / "pack" / "refresh.lock"


def _take_lock() -> bool:
    path = _lock_dir()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        if time.time() - path.stat().st_mtime < STALE_SECONDS:
            return False
        logger.warning("pack_refresh_stale_lock_broken")
        for child in path.iterdir():
            child.unlink()
        path.rmdir()
        path.mkdir()
    (path / "owner").write_text(f"refresh {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n", encoding="utf-8")
    return True


def _release_lock() -> None:
    path = _lock_dir()
    for child in path.iterdir():
        child.unlink()
    path.rmdir()


async def _run(script: Path) -> None:
    try:
        proc = await asyncio.create_subprocess_exec("/bin/bash", str(script), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                    cwd=str(script.parent.parent))
        code = await asyncio.wait_for(proc.wait(), timeout=STALE_SECONDS)
        logger.info("pack_refresh_finished", code=code)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.warning("pack_refresh_failed", error=type(exc).__name__)
    finally:
        await asyncio.to_thread(_release_lock)


async def run_install_refresh() -> Dict[str, Any]:
    """
    Raises: LookupError (no script in this install: ``no_refresh_script``), RuntimeError (one is already running: ``refresh_running``).
    """
    if not SCRIPT.is_file():
        raise LookupError("no_refresh_script")
    if not await asyncio.to_thread(_take_lock):
        raise RuntimeError("refresh_running")
    task = asyncio.create_task(_run(SCRIPT))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"op_id": uuid.uuid4().hex}
