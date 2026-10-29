
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi.concurrency import run_in_threadpool

from src.core.account_switch.pane_account import read_pane_profile
from src.core.bookmarks import rows
from src.core.session_contents import claude, codex
from src.core.session_contents import constants as C
from src.core.session_contents.enrich import enrich
from src.core.session_contents.errors import RemoteSession, UnsupportedFamily

PROFILE_VARIABLES = {C.FAMILY_CLAUDE: "CLAUDE_CONFIG_DIR", C.FAMILY_CODEX: "CODEX_HOME"}


async def pane_profile(row: rows.SessionRow, family: str, default_socket: Optional[str]) -> Optional[str]:
    socket = row.tmux_socket or default_socket
    if not row.tmux_name or not socket:
        return None
    pane = await read_pane_profile(socket, row.tmux_name, PROFILE_VARIABLES[family])
    if not (pane.readable and pane.value):
        return None
    path = os.path.normpath(os.path.expanduser(pane.value))
    return path if os.path.isabs(path) else None


def build(row: rows.SessionRow, family: str, profile_dir: Optional[str]) -> Dict[str, Any]:
    reader = claude.gather if family == C.FAMILY_CLAUDE else codex.gather
    home = str(codex.codex_home(profile_dir)) if family == C.FAMILY_CODEX else str(
        os.path.expanduser(profile_dir) if profile_dir else claude.default_config_dir())
    return {"session_uuid": row.session_uuid, "row_id": row.id, "family": family, "config_dir": home,
            "working_dir": row.working_dir, "sections": enrich(reader(profile_dir, row.working_dir), row.working_dir)}


async def read(session_key: str, default_socket: Optional[str]) -> Dict[str, Any]:
    row = await run_in_threadpool(rows.read_row, session_key)
    if row.host_key != "local":
        raise RemoteSession("this session runs on a paired computer; open its contents there")
    family = await run_in_threadpool(rows.family_of, row.agent_type)
    if family not in C.SECTIONS_BY_FAMILY:
        raise UnsupportedFamily(f"a {family} session has no skills, instruction files or MCP servers to list")
    profile = await pane_profile(row, family, default_socket)
    return await run_in_threadpool(build, row, family, profile)
