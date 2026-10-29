
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, Mapping, Optional

from src.cplugs.crate import constants as K
from src.cplugs.crate import import_job, import_store, refs, service
from src.cplugs.crate import service_crates as svc
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.errors import CrateApiError, conflict, invalid, not_found
from src.cplugs.crate.refs import CrateRef
from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_import as ci
from src.cplugs.sdk import crate_sources as cs

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_OPTIONS = ("mode", "new_root", "target_project_id", "skip_conflicts", "exclude_conversations", "include_project_files",
            "work_in_restored_copy", "include_instructions", "include_plugin_data", "made_here", "keep_conversations", "file_backups", "file_backup_units", "rules")


def import_env_of(env: CrateEnv) -> ci.ImportEnv:
    install_id, _label = cs.install_identity(state_dir=env.state)
    return ci.import_env(env.state, env.locations, install_id, env.live_panes)


def request_of(body: Mapping[str, Any], *, allow_made_here: bool) -> ci.ImportRequest:
    mode = body.get("mode", "same_paths")
    if mode not in ci.MODES:
        raise invalid("bad_mode", "mode is same_paths or relocate")
    exclude = body.get("exclude_conversations") or []
    rules = body.get("rules") or []
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise invalid("bad_request", "exclude_conversations is a list of conversation ids")
    if not isinstance(rules, list) or not all(isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(p, str) and p.startswith("/") for p in r)
                                              for r in rules):
        raise invalid("bad_request", "rules is a list of [old, new] absolute paths")
    units = body.get("file_backup_units") or []
    if not isinstance(units, list) or not all(isinstance(u, str) and ci.backup_unit_ok(u) for u in units):
        raise invalid("bad_request", "file_backup_units is a list of plugin folder units, each <plugin>.<data id>")
    return ci.ImportRequest(
        mode=mode, new_root=body.get("new_root"), target_project_id=body.get("target_project_id"),
        skip_conflicts=bool(body.get("skip_conflicts")), exclude_conversations=tuple(exclude),
        include_project_files=bool(body.get("include_project_files")),
        work_in_restored_copy=bool(body.get("work_in_restored_copy")), include_instructions=bool(body.get("include_instructions")),
        include_plugin_data=bool(body.get("include_plugin_data")), made_here=bool(body.get("made_here")) and allow_made_here,
        keep_conversations=bool(body.get("keep_conversations")) and allow_made_here,
        file_backups=bool(body.get("file_backups")) and allow_made_here,
        file_backup_units=tuple(sorted(set(units))) if allow_made_here else (),
        rules=tuple((r[0], r[1]) for r in rules))


def ref_of(source: Mapping[str, Any]) -> CrateRef:
    if isinstance(source.get("bundle_id"), str) and source["bundle_id"]:
        return CrateRef(bundle_id=source["bundle_id"])
    if source.get("folder") in ("primary", "second") and isinstance(source.get("name"), str):
        return CrateRef(folder=source["folder"], name=source["name"])
    raise invalid("bad_source", "source is a recorded bundle_id, or a folder (primary or second) and a crate name")


def _blocked(code: str, detail: str, source: Mapping[str, Any]) -> Dict[str, Any]:
    """The answer for a crate that could not be planned. Pure."""
    return {"version": 1, "ok": False, "fingerprint": "", "source": dict(source), "blockers": [{"code": code, "detail": detail}],
            "warnings": []}


def _plan_of(env: CrateEnv, ref: CrateRef, key: Optional[bytes], request: ci.ImportRequest, source: Mapping[str, Any]) -> tuple:
    found = svc.resolve(env, ref)
    sha = bc.sha256_file(found.path)
    if found.expected_sha256 and found.expected_sha256 != sha:
        return _blocked(ci.B_VERIFY_FAILED, "the file does not match the recorded sha256", source), found, sha
    try:
        reader = cf.open_crate(found.path, key)
    except cf.CrateTooNew as exc:
        return _blocked(ci.B_TOO_NEW, str(exc.code), source), found, sha
    except cf.CrateError:
        reader = refs.open_reader(found.path, key)
    with reader:
        try:
            plan_ = ci.plan_import(reader, import_env_of(env), request, crate_sha256=sha, encrypted=found.encrypted, source=dict(source))
        except cf.CrateError as exc:
            return _blocked(ci.B_VERIFY_FAILED, f"{exc.code}: the crate could not be read", source), found, sha
        except ci.EnvUnreadable as exc:
            raise CrateApiError(503, "install_unreadable", str(exc)) from exc
    return plan_, found, sha


async def plan(ctx: Any, body: Mapping[str, Any], *, allow_made_here: bool = True) -> Dict[str, Any]:
    source = body.get("source")
    if not isinstance(source, dict):
        raise invalid("bad_source", "source is required")
    ref = ref_of(source)
    request = request_of({k: body[k] for k in _OPTIONS if k in body}, allow_made_here=allow_made_here)
    identity = body.get("identity")

    def work() -> Dict[str, Any]:
        env = service.env_of(ctx)
        return _plan_of(env, ref, refs.parse_identity(identity), request, source)[0]

    return await asyncio.to_thread(work)


def _refused(fresh: Mapping[str, Any]) -> CrateApiError:
    blockers = list(fresh.get("blockers") or [])
    if blockers and {b.get("code") for b in blockers} == {"no_space"}:
        return CrateApiError(507, "no_space", blockers)
    return conflict("blocked", blockers)


async def start(ctx: Any, body: Mapping[str, Any], *, allow_made_here: bool = True) -> Dict[str, Any]:
    """``POST /imports``: re-plan, require the quoted fingerprint, start the restore as a job. Output: ``{job_id, import_id}``.

    Body: the plan body plus ``fingerprint``. The plugin must hold ``imports.write``. An engine refusal after the job starts
    (another move or import holds the lock: ``busy``) ends the job ``failed`` with that code; nothing was written.
    Raises: CrateApiError 403 permission_missing; 409 plan_changed (detail: the fresh plan), blocked (the blockers), job_busy;
    507 no_space; and the plan's own refusals.
    """
    fingerprint = body.get("fingerprint")
    if not isinstance(fingerprint, str) or not _HEX64.match(fingerprint):
        raise invalid("bad_fingerprint", "fingerprint is the 64 character fingerprint the plan answered")
    if not ctx.has("imports.write"):
        raise CrateApiError(403, "permission_missing", "restoring a crate needs the imports.write permission, which the owner has not granted")
    source = body.get("source")
    if not isinstance(source, dict):
        raise invalid("bad_source", "source is required")
    ref = ref_of(source)
    request = request_of({k: body[k] for k in _OPTIONS if k in body}, allow_made_here=allow_made_here)
    identity = body.get("identity")

    def work() -> Dict[str, Any]:
        env = service.env_of(ctx)
        key = refs.parse_identity(identity)
        fresh, found, sha = _plan_of(env, ref, key, request, source)
        if fresh.get("fingerprint") != fingerprint:
            raise conflict("plan_changed", fresh)
        if not fresh.get("ok"):
            raise _refused(fresh)
        import_id = ci.new_import_id()
        job = import_job.make_work(env, import_env_of(env), found.path, key, found.expected_sha256, sha, request, fingerprint,
                                   import_id, lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        asked = {"import_id": import_id, "source": ref.as_json(), "crate_sha256": sha, "encrypted": found.encrypted,
                 "options": request.as_json()}
        return {"job_id": service.start_job(ctx, env, K.KIND_IMPORT, asked, job), "import_id": import_id}

    return await asyncio.to_thread(work)


async def list_imports(ctx: Any) -> Dict[str, Any]:
    return await asyncio.to_thread(lambda: {"imports": import_store.list_receipts(service.env_of(ctx).work)})


async def get_import(ctx: Any, import_id: str) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        try:
            return import_store.read_receipt(service.env_of(ctx).work, import_id)
        except KeyError as exc:
            raise not_found("import_not_found", f"no finished import {import_id}") from exc
        except ValueError as exc:
            raise CrateApiError(500, "receipt_unreadable", str(exc)) from exc

    return await asyncio.to_thread(work)
