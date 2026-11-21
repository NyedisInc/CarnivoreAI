
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import structlog

from src.core.pack.jobs.types import HostJob, JobRecord

log = structlog.get_logger(__name__)

WARM_PREFIX = "warm-"


def _json(text: Optional[str], default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def _listing_uuid(peer_install_id: Optional[str], worker_uuid: Optional[str]) -> Optional[str]:
    if not worker_uuid:
        return None
    if not peer_install_id:
        return worker_uuid
    from src.core.federation.shadow_rows import shadow_uuid

    return shadow_uuid(peer_install_id, worker_uuid)


def job_view(rec: JobRecord) -> Dict[str, Any]:
    request = _json(rec.request_json, {}).get("request", {})
    land = _json(rec.land_json, {})
    return {"id": rec.id, "side": "caller", "state": rec.state.value, "body": rec.body, "project_uid": rec.project_uid,
            "project_name": rec.project_name, "folder": request.get("folder"), "command": request.get("command"),
            "kind": request.get("kind"), "task_head": rec.task_head, "agent_type": rec.agent_type, "computer": rec.peer_label,
            "reason": rec.reason, "exit_code": rec.exit_code, "output_tail": rec.output_tail, "applied": land.get("applied", []),
            "deleted": land.get("deleted", []), "clashes": land.get("clashes", []), "ref": land.get("ref"),
            "error_code": rec.error_code, "error_detail": rec.error_detail, "question": rec.question, "question_kind": rec.question_kind,
            "result_text": rec.result_text, "account_label": rec.account_label, "usage": _json(rec.usage_json, None),
            "created_at": rec.created_at, "started_at": rec.started_at, "ended_at": rec.ended_at, "caller_session": rec.caller_session,
            "worker_session_uuid": rec.worker_session_uuid, "peer_install_id": rec.peer_install_id,
            "worker_listing_uuid": _listing_uuid(rec.peer_install_id, rec.worker_session_uuid)}


def host_view(row: HostJob, label: Optional[str]) -> Dict[str, Any]:
    return {"id": row.job_id, "side": "host", "state": row.state.value, "body": row.body, "project_uid": row.project_uid,
            "project_name": None, "folder": None, "command": None, "kind": None, "task_head": None, "agent_type": None,
            "computer": label or row.caller_install or None, "reason": None, "exit_code": row.exit_code, "output_tail": None,
            "applied": [], "deleted": [], "clashes": [], "ref": None, "error_code": None, "error_detail": row.detail,
            "question": row.question, "question_kind": row.question_kind, "result_text": row.result_text,
            "account_label": row.account_label, "usage": _json(row.usage_json, None), "created_at": row.created_at,
            "started_at": row.started_at, "ended_at": row.ended_at, "caller_session": None,
            "worker_session_uuid": row.worker_session_uuid, "peer_install_id": row.caller_install or None,
            "worker_listing_uuid": row.worker_session_uuid}


def host_labels(state_dir: Path, installs: Iterable[str]) -> Dict[str, str]:
    wanted = {i for i in installs if i}
    out = {i: i for i in wanted}
    if not wanted:
        return out
    from src.core.db import DatastoreUnreadableError, connect, db_path_for
    from src.core.pack.identity import home

    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            for install in wanted:
                out[install] = home.machine_label(conn, install) or install
    except (OSError, sqlite3.Error, DatastoreUnreadableError) as exc:
        log.warning("pack_jobs_labels_unreadable", error=type(exc).__name__)
    return out
