
from __future__ import annotations

import json
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.argent import store


def ref_for_name(tenant_id: str, tmux_name: str, *, state_dir: Optional[Path] = None, clock: Any = time.time) -> str:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT session_ref FROM ref_alias WHERE tenant_id = ? AND tmux_name = ?", (tenant_id, tmux_name)).fetchone()
        if row is not None:
            conn.execute("COMMIT")
            return str(row[0])
        ref, n = tmux_name, 1
        while conn.execute("SELECT 1 FROM ref_alias WHERE tenant_id = ? AND session_ref = ?", (tenant_id, ref)).fetchone():
            n += 1
            ref = f"{tmux_name}-{n}"[-128:]
        conn.execute("INSERT INTO ref_alias (tenant_id, tmux_name, session_ref, updated_at) VALUES (?, ?, ?, ?)", (tenant_id, tmux_name, ref, float(clock())))
        conn.execute("COMMIT")
        return ref


def ref_for_uuid(tenant_id: str, session_uuid: str, *, state_dir: Optional[Path] = None) -> Optional[str]:
    if not session_uuid:
        return None
    with closing(store.open_db(state_dir)) as conn:
        row = conn.execute("SELECT session_ref FROM ref_alias WHERE tenant_id = ? AND session_uuid = ? ORDER BY updated_at DESC LIMIT 1", (tenant_id, session_uuid)).fetchone()
    return str(row[0]) if row else None


def bind(tenant_id: str, tmux_name: str, *, session_uuid: str, agent_id: str, reg: Dict[str, Any], state_dir: Optional[Path] = None, clock: Any = time.time) -> str:
    ref = ref_for_name(tenant_id, tmux_name, state_dir=state_dir, clock=clock)
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("UPDATE ref_alias SET session_uuid = ?, agent_id = ?, reg = ?, updated_at = ? WHERE tenant_id = ? AND tmux_name = ?",
                     (session_uuid or "", agent_id, json.dumps(reg), float(clock()), tenant_id, tmux_name))
    return ref


def registration(tenant_id: str, session_ref: str, *, state_dir: Optional[Path] = None) -> Dict[str, Any]:
    with closing(store.open_db(state_dir)) as conn:
        row = conn.execute("SELECT reg FROM ref_alias WHERE tenant_id = ? AND session_ref = ? AND reg != '' ORDER BY updated_at DESC LIMIT 1", (tenant_id, session_ref)).fetchone()
    try:
        data = json.loads(row[0]) if row else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def rename(tenant_id: str, old_name: str, new_name: str, *, state_dir: Optional[Path] = None, clock: Any = time.time) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM ref_alias WHERE tenant_id = ? AND tmux_name = ?", (tenant_id, old_name)).fetchone():
            conn.execute("DELETE FROM ref_alias WHERE tenant_id = ? AND tmux_name = ?", (tenant_id, new_name))
            conn.execute("UPDATE ref_alias SET tmux_name = ?, updated_at = ? WHERE tenant_id = ? AND tmux_name = ?", (new_name, float(clock()), tenant_id, old_name))
        conn.execute("COMMIT")


def rename_all(old_name: str, new_name: str, *, state_dir: Optional[Path] = None, clock: Any = time.time) -> None:
    with closing(store.open_db(state_dir)) as conn:
        tenants = [r[0] for r in conn.execute("SELECT DISTINCT tenant_id FROM ref_alias WHERE tmux_name = ?", (old_name,))]
    for tenant in tenants:
        rename(tenant, old_name, new_name, state_dir=state_dir, clock=clock)


RETIRING_REASONS = ("destroyed", "external_destroyed")
_RETIRED = "retired:"


def retire(tenant_id: str, tmux_name: str, *, state_dir: Optional[Path] = None, clock: Any = time.time) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("UPDATE ref_alias SET tmux_name = ? || session_ref, updated_at = ? WHERE tenant_id = ? AND tmux_name = ?",
                     (_RETIRED, float(clock()), tenant_id, tmux_name))
