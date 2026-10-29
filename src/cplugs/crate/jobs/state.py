
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.cplugs.crate import constants as K

logger = structlog.get_logger()

_TERMINAL = (K.STATE_DONE, K.STATE_FAILED, K.STATE_CANCELLED)


@dataclass
class JobRecord:

    job_id: str
    kind: str
    state: str = K.STATE_RUNNING
    phase: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    request: Dict[str, Any] = field(default_factory=dict)
    progress: Dict[str, int] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    temp_paths: List[str] = field(default_factory=list)
    publish: Optional[Dict[str, Any]] = None

    @property
    def finished(self) -> bool:
        return self.state in _TERMINAL

    def view(self) -> Dict[str, Any]:
        p = self.progress or {}
        done, total = int(p.get("done_bytes", 0)), int(p.get("total_bytes", 0))
        return {"job_id": self.job_id, "kind": self.kind, "state": self.state, "phase": self.phase,
                "done_bytes": done, "total_bytes": total, "files_done": int(p.get("files_done", 0)),
                "files_total": int(p.get("files_total", 0)),
                "percent": round(min(done, total) * 100.0 / total, 1) if total else None,
                "result": self.result, "error": self.error, "created_at": self.created_at,
                "updated_at": self.updated_at}


def new_job_id(now: Optional[float] = None) -> str:
    stamp = time.strftime(K.BUNDLE_STAMP_FMT, time.gmtime(time.time() if now is None else now))
    return f"job-{stamp}-{secrets.token_hex(4)}"


def jobs_dir(work: Path) -> Path:
    folder = Path(work) / K.JOBS_DIR
    folder.mkdir(mode=K.FOLDER_MODE, parents=True, exist_ok=True)
    return folder


def _path(root: Path, job_id: str) -> Path:
    if not K.JOB_ID_RE.match(job_id):
        raise KeyError(job_id)
    return Path(root) / f"{job_id}.json"


def save(root: Path, rec: JobRecord) -> None:
    target = _path(root, rec.job_id)
    temp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, K.FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(rec), handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            os.unlink(temp)


def _from_json(data: Any) -> JobRecord:
    if not isinstance(data, dict) or not isinstance(data.get("job_id"), str) or not isinstance(data.get("kind"), str):
        raise ValueError("not a job record")
    known = set(JobRecord.__dataclass_fields__)
    return JobRecord(**{k: v for k, v in data.items() if k in known})


def load(root: Path, job_id: str) -> JobRecord:
    path = _path(root, job_id)
    try:
        return _from_json(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise KeyError(job_id) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"job record {job_id} could not be read ({type(exc).__name__})") from exc


def all_jobs(root: Path) -> List[JobRecord]:
    out: List[JobRecord] = []
    for path in Path(root).glob("job-*.json"):
        try:
            out.append(_from_json(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:
            logger.warning("crate_job_record_unreadable", file=path.name, error_type=type(exc).__name__)
    return sorted(out, key=lambda r: (r.created_at, r.job_id), reverse=True)


def list_jobs(root: Path, limit: int = K.JOBS_LIMIT_DEFAULT) -> List[JobRecord]:
    return all_jobs(root)[:max(0, int(limit))]


def prune(root: Path, now: Optional[float] = None) -> int:
    cutoff = (time.time() if now is None else now) - K.JOB_KEEP_DAYS * 86400
    removed = 0
    for rec in all_jobs(root):
        if rec.finished and rec.updated_at < cutoff:
            try:
                os.unlink(_path(root, rec.job_id))
                removed += 1
            except FileNotFoundError:
                continue
    return removed
