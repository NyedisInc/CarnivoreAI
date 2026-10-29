
from __future__ import annotations

import time
from typing import Any, Dict

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate import import_job, import_store, imports
from src.cplugs.crate import service_crates as svc
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.errors import CrateApiError
from src.cplugs.crate.jobs import state
from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_import as ci

logger = structlog.get_logger()

_FINISHED = ("done", "done_with_warnings")


def _fail(rec: state.JobRecord, code: str, detail: str) -> None:
    rec.state, rec.result, rec.error = K.STATE_FAILED, None, {"code": code, "detail": detail}


def _resume(env: CrateEnv, ienv: ci.ImportEnv, rec: state.JobRecord, import_id: str, now: float) -> None:
    asked: Dict[str, Any] = rec.request
    if asked.get("encrypted"):
        _fail(rec, K.E_INTERRUPTED_NEEDS_KEY, "the app stopped after the rows were saved; restore the same crate again with its key to finish")
        return
    try:
        found = svc.resolve(env, imports.ref_of(asked.get("source") or {}))
        if bc.sha256_file(found.path) != asked.get("crate_sha256"):
            _fail(rec, K.E_INTERRUPTED_UNFINISHED, "the crate file changed since the import started; restore it again to finish")
            return
        request = imports.request_of(asked.get("options") or {}, allow_made_here=True)
        with cf.open_crate(found.path, None) as reader:
            receipt = ci.finish_import(reader, ienv, request, crate_sha256=str(asked["crate_sha256"]), import_id=import_id)
    except (CrateApiError, cf.CrateError, ci.ImportRefused, ci.ImportFailed, KeyError) as exc:
        logger.warning("crate_import_resume_failed", import_id=import_id, error_type=type(exc).__name__)
        _fail(rec, K.E_INTERRUPTED_UNFINISHED, "the app stopped after the rows were saved and the rest could not be finished; "
                                               "restore the same crate again to finish")
        return
    stored = {**import_job.finished(receipt, _utc(now)), "interrupted_resumed": True}
    import_store.write_receipt(env.work, import_id, stored)
    rec.state, rec.result, rec.error = K.STATE_DONE, stored, None


def _utc(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def end_import(env: CrateEnv, rec: state.JobRecord, now: float) -> None:
    import_id = str(rec.request.get("import_id") or "")
    if not ci.IMPORT_ID_RE.match(import_id):
        _fail(rec, K.E_INTERRUPTED, "the app stopped while this import ran; its record names no import")
        return
    ienv = imports.import_env_of(env)
    try:
        conn = ienv.connect()
    except ci.EnvUnreadable as exc:
        raise OSError(str(exc)) from exc
    try:
        entry = ci.ledger.read_entry(conn, import_id)
    finally:
        conn.close()
    if entry is None:
        report = ci.recover_files(import_store.read_undo(env.work, import_id), ienv, import_id)
        kept = f"; {len(report.kept) + len(report.errors)} file(s) were left where they are" if report.kept or report.errors else ""
        _fail(rec, K.E_INTERRUPTED_UNDONE, f"the app stopped before the rows were saved; {len(report.removed)} file(s) it placed were removed{kept}")
    elif entry.get("phase") in _FINISHED:
        rec.state, rec.error = K.STATE_DONE, None
        try:
            rec.result = import_store.read_receipt(env.work, import_id)
        except (KeyError, ValueError):
            rec.result = {"import_id": import_id, "state": entry.get("phase"), "recovered": True}
    else:
        _resume(env, ienv, rec, import_id, now)
    rec.temp_paths, rec.updated_at = [], now
    logger.info("crate_import_swept", import_id=import_id, state=rec.state)

