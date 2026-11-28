
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import structlog

from src.core import resource_push, session_change_notice
from src.core.db import get_meta, transaction
from src.core.db_models import META_INSTALL_ID
from src.core.pack.globalsync import panel_merge
from src.core.resource_push import topics

log = structlog.get_logger(__name__)

APPLY_LOCK = threading.Lock()

Compute = Callable[[Any, str, Optional[Mapping[str, Any]]], Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]


def run_locked(ui_store: Any, open_db: Callable[[], Any], compute: Compute, after_commit: Callable[[Any, Any, str], None]
               ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], Any]:
    with panel_merge.LOCK:
        current = ((ui_store.read() or {}).get("values") or {}).get("drawer_arrangement") if ui_store is not None else None
        with closing(open_db()) as conn, APPLY_LOCK:
            with transaction(conn):
                iid = get_meta(conn, META_INSTALL_ID)
                report, arrangement = compute(conn, iid, current)
        result = None
        if arrangement is not None and ui_store is not None:
            result = ui_store.update({"drawer_arrangement": arrangement})
            committed = (result.values or {}).get("drawer_arrangement") if result.status in ("committed", "unchanged") else None
            if isinstance(committed, dict):
                with closing(open_db()) as conn:
                    after_commit(conn, committed, iid)
    return report, arrangement, result


async def announce(app_state: Any, report: Dict[str, Any], result: Any) -> bool:
    moved = bool(report["companies_created"] or report["companies_updated"] or report["projects_updated"])
    if report["groups_changed"]:
        session_change_notice.publish(app_state, session_change_notice.build_structural_notice("groups"))
        from src.core.pack.globalsync import wiring

        wiring.groups_changed()
    if report.get("layouts_changed"):
        session_change_notice.publish(app_state, session_change_notice.build_structural_notice("layouts"))
        resource_push.notify(topics.LAYOUTS)
    if result is not None:
        from src.core.preferences_push.broadcast import broadcast_changed

        if result.status == "committed":
            moved = True
            await broadcast_changed(app_state, result, None)
        elif result.status != "unchanged":
            report["arrangement"] = result.status
    if moved:
        resource_push.notify(topics.PROJECTS)
        resource_push.notify(topics.COMPANIES)
    return moved


def records_carry(iid: Optional[str] = None) -> bool:
    from src.core.pack.machines import capabilities

    if not capabilities.mesh_on():
        return False
    from src.core.pack.machines.roster_v2 import RosterV2
    from src.core.pack.meshdata import gossip, panel_kind

    active = gossip.ACTIVE
    if active is None:
        return False
    try:
        lst = active.held_list()
        return isinstance(lst, RosterV2) and panel_kind.approved(lst, active.store.own_iid if iid is None else iid)
    except (OSError, ValueError, sqlite3.Error) as exc:
        log.info("mesh_panel_gate_failed", error=type(exc).__name__)
        return False


def mesh_member(iid: str) -> bool:
    from src.core.pack.machines import capabilities

    if not capabilities.mesh_on():
        return False
    from src.core.federation import peer_links

    links = peer_links.LINKS
    return links is not None and capabilities.has(links.capabilities(iid), capabilities.CAP_MESH) and records_carry(iid)


def legacy_before(conn: Any, current: Optional[Mapping[str, Any]], own: str, path: Path) -> Dict[str, str]:
    from src.core.pack.globalsync import mesh_panel_doc

    return mesh_panel_doc.legacy_hashes(panel_merge.local_doc(conn, current, own, panel_merge.Ledger(path), False))


def claim_bridged(path: Path, before: Mapping[str, str], own: str, caller: str) -> int:
    with panel_merge.LOCK:
        ledger = panel_merge.Ledger(path)
        claimed = 0
        for field, row in ledger.fields.items():
            if before.get(field) != row[2] and row[1] in ("", own):
                row[1] = caller
                claimed += 1
        if claimed:
            ledger.save()
    return claimed
