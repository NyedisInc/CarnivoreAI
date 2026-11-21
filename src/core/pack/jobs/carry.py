
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.pack.jobs import gitio
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.target import SSH_PREFIX, is_ssh


def project_row(project_uid: str) -> Optional[Dict[str, Any]]:
    from src.api import projects_service
    from src.config import settings

    with closing(projects_service.open_db_or_503(settings)) as conn:
        row = conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone()
        return dict(row) if row is not None else None


async def default_carry(project_root: str, project_uid: str, peer_install_id: str) -> Optional[Dict[str, Any]]:
    from src.api import project_transport_routes

    if is_ssh(peer_install_id):
        return await ssh_seed(project_root, project_uid, peer_install_id)
    project = await asyncio.to_thread(project_row, project_uid) or {"root": project_root, "uid": project_uid, "air_gap": 1}
    return await project_transport_routes.carry_to(project, peer_install_id, peer_install_id, False)


async def ssh_seed(project_root: str, project_uid: str, peer_install_id: str, store: Optional[JobStore] = None) -> Optional[Dict[str, Any]]:
    from src.config import settings

    store = store or JobStore(Path(settings.get_state_dir()))
    key = peer_install_id[len(SSH_PREFIX):]
    if store.ssh_seed_get(project_uid, key) is None:
        cp = await asyncio.to_thread(gitio.run, ["rev-parse", "--verify", "-q", "HEAD"], cwd=project_root, check=False)
        store.ssh_seed_set(project_uid, key, gitio.out(cp) if cp.returncode == 0 else "")
    return {}
