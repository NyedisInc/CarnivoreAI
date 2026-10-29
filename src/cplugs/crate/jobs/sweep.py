
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate import record
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.jobs import runner, state
from src.cplugs.crate.jobs.sweep_import import end_import
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import exports as sx

logger = structlog.get_logger()

_AFTER_PUBLISH = (K.PHASE_PUBLISHING, K.PHASE_RECORDING, K.PHASE_COPYING)


def _ours(path: Path, env: CrateEnv) -> bool:
    if path.name.startswith(".") and path.name.endswith(".partial"):
        return True
    drill_root = Path(env.work) / K.EXTRACT_DIR
    return path.parent == drill_root and path.name.startswith(K.DRILL_PREFIX)


def remove_temp(path_text: str, env: CrateEnv) -> bool:
    path = Path(path_text)
    if not _ours(path, env):
        logger.warning("crate_sweep_refused_path", path=path_text)
        return False
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return True
    if os.path.lexists(path):
        os.unlink(path)
        return True
    return False


def _bundle_known(env: CrateEnv, bundle_id: str) -> bool:
    def work(conn: Any) -> bool:
        try:
            sx.bundle(conn, bundle_id)
        except sx.BundleNotFound:
            return False
        return True

    return sx.with_main_db(work, state=env.state)


def _recover(env: CrateEnv, rec: state.JobRecord, now: float) -> Dict[str, Any]:
    pub: Dict[str, Any] = rec.publish or {}
    final = Path(str(pub.get("path", "")))
    if not pub or not final.is_file() or final.is_symlink():
        return {"state": K.STATE_FAILED, "error": {"code": K.E_INTERRUPTED,
                                                   "detail": "the app stopped before the crate was published"}}
    report = cf.verify(final, "quick", expected_sha256=str(pub.get("sha256")))
    if not report.ok:
        return {"state": K.STATE_FAILED, "error": {
            "code": K.E_INTERRUPTED_UNVERIFIED,
            "detail": f"{final} was left where it is: it did not pass a quick check ({', '.join(report.codes)})"}}
    recovered = {"bundle_id": pub.get("bundle_id"), "path": str(final), "sha256": pub.get("sha256"),
                 "recovered": True, "recorded": False}
    if pub.get("variant") != "share":
        if not _bundle_known(env, str(pub.get("bundle_id"))):
            record.record_published(env, pub, now)
        recovered["recorded"] = True
    return {"state": K.STATE_DONE, "result": recovered}


def _end(env: CrateEnv, rec: state.JobRecord, now: float) -> None:
    for path in list(rec.temp_paths):
        remove_temp(path, env)
    rec.temp_paths = []
    if rec.kind == K.KIND_IMPORT:
        end_import(env, rec, now)
        return
    if rec.phase in _AFTER_PUBLISH:
        outcome = _recover(env, rec, now)
    else:
        outcome = {"state": K.STATE_FAILED,
                   "error": {"code": K.E_INTERRUPTED, "detail": "the app stopped while this job ran; its temp files "
                                                                "were removed and nothing was published"}}
    rec.state = outcome["state"]
    rec.result = outcome.get("result")
    rec.error = outcome.get("error")
    rec.updated_at = now


def sweep_interrupted(env: CrateEnv, now: Optional[float] = None) -> int:
    """End every job a stopped process left ``running`` (module docstring). Blocking. Output: how many were ended.

    Raises: OSError (a record could not be written). A database that cannot be read leaves that job ``running`` for
      the next sweep (logged), so a recovery is never skipped silently.
    """
    root = state.jobs_dir(env.work)
    live = runner.running_id()
    at = time.time() if now is None else now
    ended = 0
    for rec in state.all_jobs(root):
        if rec.finished or rec.job_id == live:
            continue
        try:
            _end(env, rec, at)
        except (OSError, sqlite3.Error, sx.ExportsError) as exc:
            logger.error("crate_sweep_deferred", job_id=rec.job_id, error_type=type(exc).__name__)
            continue
        state.save(root, rec)
        logger.info("crate_job_swept", job_id=rec.job_id, state=rec.state)
        ended += 1
    return ended
