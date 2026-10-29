
from __future__ import annotations

import re
from typing import Any, Awaitable, Dict, Mapping, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import import_undo, imports, removal, service
from src.cplugs.crate import service_crates as svc
from src.cplugs.crate.errors import CrateApiError
from src.cplugs.crate.models import RemoveBody
from src.cplugs.crate.refs import CrateRef
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result
from src.cplugs.sdk import crate_import as ci

_PLAN_KEYS = ("scope", "target", "variant", "encrypt", "recipients", "label", "include_project_files", "include_backups", "backup_units")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

ROUTE_TOOLS: Mapping[str, str] = {
    "/summary": "crate_status", "/backup-families": "crate_backup_families", "/plan": "crate_export_preview", "/exports": "crate_export",
    "/jobs": "crate_jobs_list", "/jobs/{job_id}": "crate_jobs_list", "/jobs/{job_id}/cancel": "crate_job_cancel",
    "/bundles": "crate_bundles_list", "/bundles/{bundle_id}": "crate_bundles_list",
    "/bundles/{bundle_id}/contents": "crate_bundles_list", "/bundles/{bundle_id}/verify": "crate_check",
    "/bundles/{bundle_id}/copies": "crate_copy", "/bundles/{bundle_id}/extract": "crate_unpack",
    "/folders/{folder}/crates": "crate_folder_crates_list",
    "/folders/primary/crates/upload": "crate_folder_crates_list", "/crates/remove": "crate_remove",
    "/folders/{folder}/crates/{name}/contents": "crate_folder_crates_list",
    "/folders/{folder}/crates/{name}/verify": "crate_check", "/folders/{folder}/crates/{name}/extract": "crate_unpack",
    "/imports/plan": "crate_import_preview", "/imports": "crate_import", "/imports/{import_id}": "crate_imports_list",
    "/imports/{import_id}/undo": "crate_import_undo",
}

NO_TOOL_ROUTES = frozenset({"/bundles/{bundle_id}/download", "/folders/{folder}/crates/{name}/download"})


async def _answer(work: Awaitable[Any]) -> dict:
    try:
        return tool_result(scrub(await work))
    except CrateApiError as exc:
        raise ToolError(exc.sentence()) from exc


def _no_identity(args: dict) -> None:
    if "identity" in args:
        raise ToolError("identity is refused: a private key never rides an MCP call; read or verify an encrypted crate "
                        "in the app")


def _ref(args: dict) -> CrateRef:
    _no_identity(args)
    if isinstance(args.get("bundle_id"), str) and args["bundle_id"]:
        return CrateRef(bundle_id=args["bundle_id"])
    if args.get("folder") in (K.FOLDER_PRIMARY, K.FOLDER_SECOND) and isinstance(args.get("name"), str):
        return CrateRef(folder=args["folder"], name=args["name"])
    raise ToolError("name a crate: bundle_id, or folder (primary or second) and name")


async def _encrypted(ctx: CplugContext, ref: CrateRef) -> bool:
    if ref.name is not None:
        return ref.name.endswith(".age")
    try:
        return bool((await svc.bundle(ctx, str(ref.bundle_id)))["encrypted"])
    except CrateApiError as exc:
        raise ToolError(exc.sentence()) from exc


async def _plain_only(ctx: CplugContext, ref: CrateRef, what: str) -> None:
    if await _encrypted(ctx, ref):
        raise ToolError(f"needs_identity: {what} an encrypted crate needs its age identity, which only the app takes")


async def crate_status(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _answer(service.summary(ctx))


async def crate_backup_families(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    _no_identity(args)
    return await _answer(service.backup_families(ctx, {k: args[k] for k in ("scope", "target") if k in args}))


async def crate_export_preview(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    _no_identity(args)
    return await _answer(service.plan(ctx, {k: args[k] for k in _PLAN_KEYS if k in args}))


async def _export_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    _no_identity(args)
    fingerprint = args.get("fingerprint")
    if not isinstance(fingerprint, str) or not _HEX64.match(fingerprint):
        raise ToolError("fingerprint is required: the fingerprint crate_export_preview answered")
    body = {k: args[k] for k in _PLAN_KEYS if k in args}
    try:
        view = await service.plan(ctx, body)
    except CrateApiError as exc:
        raise ToolError(exc.sentence()) from exc
    if not view["ok"]:
        raise ToolError("blocked: " + "; ".join(f"{b['code']}: {b['detail']}" for b in view["blockers"])[:900])
    if view["fingerprint"] != fingerprint:
        raise ToolError(f"plan_changed: {service.PLAN_CHANGED_SENTENCE}; quote the new fingerprint")
    subject = view["subject"] or {}
    who = subject.get("title") or subject.get("name") or body.get("target")
    lock = f", encrypted to {len(view['recipients'])} age recipient(s)" if view["encrypt"] else ""
    project = view.get("project_files")
    lock += f", with the project's files ({project['files']} files, {project['bytes']} bytes)" if project else ""
    sentence = (f"export {view['scope']} {who} as a {view['variant']} crate{lock}: {view['files']} files, about "
                f"{view['estimate_bytes']} bytes, into {view['folder']}")
    return {**body, "fingerprint": fingerprint}, sentence


async def crate_export(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    body = {k: args[k] for k in _PLAN_KEYS if k in args}
    return await _answer(service.start_export(ctx, body, str(args.get("fingerprint", ""))))


async def crate_jobs_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    if isinstance(args.get("job_id"), str):
        return await _answer(service.job(ctx, args["job_id"]))
    limit = args.get("limit", K.JOBS_LIMIT_DEFAULT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= K.JOBS_LIMIT_MAX:
        raise ToolError(f"limit is 1 to {K.JOBS_LIMIT_MAX}")
    return await _answer(service.jobs(ctx, limit))


async def crate_job_cancel(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    if not isinstance(args.get("job_id"), str):
        raise ToolError("job_id is required")
    return await _answer(service.cancel(ctx, args["job_id"]))


async def crate_bundles_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    _no_identity(args)
    bundle_id = args.get("bundle_id")
    if not isinstance(bundle_id, str) or not bundle_id:
        project = args.get("project")
        if project is not None and (not isinstance(project, int) or isinstance(project, bool) or project < 1):
            raise ToolError("project must be a project id (a whole number from 1)")
        return await _answer(svc.bundles(ctx, project))
    if args.get("contents") is True:
        ref = CrateRef(bundle_id=bundle_id)
        await _plain_only(ctx, ref, "reading")
        return await _answer(svc.contents(ctx, ref))
    return await _answer(svc.bundle(ctx, bundle_id))


async def crate_check(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    ref = _ref(args)
    level = args.get("level", "full")
    if level != "quick":
        await _plain_only(ctx, ref, f"a {level} verify of")
    return await _answer(svc.start_verify(ctx, ref, str(level)))


async def crate_unpack(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    ref = _ref(args)
    if not isinstance(args.get("conversation_id"), str):
        raise ToolError("conversation_id is required")
    await _plain_only(ctx, ref, "unpacking")
    return await _answer(svc.extract(ctx, ref, args["conversation_id"]))


async def crate_copy(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    _no_identity(args)
    if not isinstance(args.get("bundle_id"), str):
        raise ToolError("bundle_id is required")
    return await _answer(svc.start_copy(ctx, args["bundle_id"]))


async def crate_folder_crates_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    _no_identity(args)
    folder, name = args.get("folder"), args.get("name")
    if folder not in (K.FOLDER_PRIMARY, K.FOLDER_SECOND):
        raise ToolError("folder is primary or second")
    if isinstance(name, str) and args.get("contents") is True:
        ref = CrateRef(folder=folder, name=name)
        await _plain_only(ctx, ref, "reading")
        return await _answer(svc.contents(ctx, ref))
    try:
        listing: Dict[str, Any] = await svc.folder_crates(ctx, folder)
    except CrateApiError as exc:
        raise ToolError(exc.sentence()) from exc
    if isinstance(name, str):
        listing = {"crates": [c for c in listing["crates"] if c["name"] == name]}
    return tool_result(scrub(listing))


def _remove_body(args: dict) -> RemoveBody:
    _no_identity(args)
    keys = ("bundle_id", "folder", "name", "also_second")
    try:
        return RemoveBody(**{k: args[k] for k in keys if k in args})
    except ValueError as exc:
        raise ToolError("name a crate: bundle_id, or folder (primary or second) and name; also_second is true or false") from exc


async def _remove_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    body = _remove_body(args)
    ref = _ref(args)
    what = ref.bundle_id or f"{ref.folder}/{ref.name}"
    also = "; the same-named copy in the second folder goes too" if body.also_second else ""
    return body.model_dump(exclude_none=True), f"move crate {what} to the Trash (it can be put back from there){also}"


async def crate_remove(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _answer(removal.remove_crate(ctx, _remove_body(args)))


_IMPORT_KEYS = ("source", "mode", "new_root", "target_project_id", "skip_conflicts", "exclude_conversations",
                "include_project_files", "work_in_restored_copy", "include_instructions", "include_plugin_data", "rules")


async def crate_import_preview(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    body = _import_body(args)
    await _plain_only(ctx, _ref(args), "previewing an import of")
    return await _answer(imports.plan(ctx, body, allow_made_here=False))


def _import_body(args: dict) -> dict:
    _no_identity(args)
    if "made_here" in args:
        raise ToolError("made_here is refused: only the owner's own click in the app can say the owner made a crate on this computer")
    source = {k: args[k] for k in ("bundle_id", "folder", "name") if k in args}
    if not source:
        raise ToolError("name a crate: bundle_id, or folder (primary or second) and name")
    return {"source": source, **{k: args[k] for k in _IMPORT_KEYS if k in args and k != "source"}}


async def _import_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    body = _import_body(args)
    fingerprint = args.get("fingerprint")
    if not isinstance(fingerprint, str) or not _HEX64.match(fingerprint):
        raise ToolError("fingerprint is required: the fingerprint crate_import_preview answered")
    await _plain_only(ctx, _ref(args), "restoring")
    try:
        view = await imports.plan(ctx, body, allow_made_here=False)
    except CrateApiError as exc:
        raise ToolError(exc.sentence()) from exc
    if not view["ok"]:
        raise ToolError("blocked: " + "; ".join(f"{b['code']}: {b['detail']}" for b in view["blockers"])[:900])
    if view["fingerprint"] != fingerprint:
        raise ToolError("plan_changed: the plan changed since it was previewed; preview again and quote the new fingerprint")
    crate, project = view.get("crate") or {}, view.get("project") or {}
    where = project.get("root_to") or "its own folders"
    sentence = (f"restore crate {crate.get('label') or crate.get('bundle_id') or body['source']} ({view.get('provenance')}) "
                f"into project {project.get('name')} ({project.get('action')}) at {where}: {len(view.get('conversations') or [])} "
                f"conversation(s), {(view.get('files') or {}).get('count', 0)} file(s); every restored session comes back asleep")
    return {**body, "fingerprint": fingerprint}, sentence


async def crate_import(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    body = _import_body(args)
    body["fingerprint"] = str(args.get("fingerprint", ""))
    return await _answer(imports.start(ctx, body, allow_made_here=False))


async def crate_imports_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    if isinstance(args.get("import_id"), str):
        return await _answer(imports.get_import(ctx, args["import_id"]))
    return await _answer(imports.list_imports(ctx))


def _undo_id(args: dict) -> str:
    import_id = args.get("import_id")
    if not isinstance(import_id, str) or not ci.IMPORT_ID_RE.match(import_id):
        raise ToolError("import_id is the id of a finished import (crate_imports_list)")
    return import_id


async def _undo_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    import_id = _undo_id(args)
    try:
        view = await import_undo.preview(ctx, import_id)
    except CrateApiError as exc:
        raise ToolError(exc.sentence()) from exc
    if not view["ok"]:
        raise ToolError("blocked: " + "; ".join(f"{b['code']}: {b['detail']}" for b in view["blockers"])[:900])
    kept = f"; {len(view['kept'])} row(s) changed since stay" if view["kept"] else ""
    return {"import_id": import_id}, (f"undo restore {import_id}: remove the {view['rows_to_remove']} database row(s) and {view['files']} file entry(ies) "
                                      f"it wrote, put back what it changed; anything already here or changed since stays{kept}")


async def crate_import_undo(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _answer(import_undo.undo(ctx, _undo_id(args)))


_SCOPE = {"type": "string", "enum": ["session", "project"]}
_TARGET = {"type": "string", "minLength": 1, "maxLength": 1024,
           "description": "A session (uuid, id or name) or a project (name, id or folder)."}
_PLAN_PROPS = {"scope": _SCOPE, "target": _TARGET, "variant": {"type": "string", "enum": ["own", "share"]},
               "encrypt": {"type": "boolean"}, "recipients": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
               "label": {"type": "string", "maxLength": K.LABEL_MAX},
               "include_backups": {"type": "boolean", "description": "Also carry every backup point of each conversation from the backup "
                                    "vault (own copies only; needs the backup plugin on). Default false."},
               "backup_units": {"type": "array", "maxItems": 50, "items": {"type": "string", "maxLength": 130},
                                "description": "Also carry the backup points of these plugin folders, each <plugin>.<data id> as "
                                               "crate_backup_families lists them (own copies only; only this project's part). Default none."},
               "include_project_files": {"type": "boolean", "description": "Also carry the project folder's files (own "
                                         "copies only; a fixed skip list leaves out node_modules, venv, build output "
                                         "and .git; .env and key files ARE kept). Default false."}}
_BUNDLE = {"type": "string", "maxLength": 80, "description": "A recorded bundle id (crate_bundles_list)."}
_FOLDER = {"type": "string", "enum": [K.FOLDER_PRIMARY, K.FOLDER_SECOND]}
_NAME = {"type": "string", "maxLength": 128, "description": "A crate file name (crate_folder_crates_list)."}

_IMPORT_OPTIONS = {"bundle_id": _BUNDLE, "folder": _FOLDER, "name": _NAME,
    "mode": {"type": "string", "enum": ["same_paths", "relocate"]},
    "new_root": {"type": "string", "maxLength": 1024},
    "target_project_id": {"type": "integer", "minimum": 1},
    "skip_conflicts": {"type": "boolean"},
    "exclude_conversations": {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 500},
    "include_project_files": {"type": "boolean"}, "work_in_restored_copy": {"type": "boolean"},
    "include_instructions": {"type": "boolean"}, "include_plugin_data": {"type": "boolean"},
    "rules": {"type": "array", "maxItems": 50,
              "items": {"type": "array", "items": {"type": "string", "maxLength": 1024}, "minItems": 2, "maxItems": 2}}}
_IMPORT_PROPS = {**_IMPORT_OPTIONS, "fingerprint": {"type": "string", "minLength": 64, "maxLength": 64}}

TOOLS: Dict[str, ToolSpec] = {
    "crate_status": ToolSpec(
        description="Crate export status: the crate folders (state, free space), encryption defaults, the running job, "
                    "and how many crates are recorded.",
        properties={}, required=[], handler=crate_status, gate="read"),
    "crate_backup_families": ToolSpec(
        description="The backup ticks an export of one session or project offers: whether conversation backups are available, and one "
                    "family per plugin folder the project owns a part of (review boards: its board folders), each ok, plugin_off or "
                    "switched_off in the backup menu. Name the ok ones in crate_export_preview's backup_units.",
        properties={"scope": _SCOPE, "target": _TARGET}, required=["scope", "target"], handler=crate_backup_families, gate="read"),
    "crate_export_preview": ToolSpec(
        description="Preview a crate export of one session or project: conversations, what goes in and what stays out, "
                    "blockers (live sessions, unreadable sources), warnings, the size estimate and the fingerprint "
                    "crate_export must quote. variant own is byte exact; share is redacted and resumes only as a fork.",
        properties=_PLAN_PROPS, required=["scope", "target"], handler=crate_export_preview, gate="read"),
    "crate_export": ToolSpec(
        description="Ask the owner to export a session or project to one crate file, quoting crate_export_preview's "
                    "fingerprint. It waits for their approval every time, then runs as a job (crate_jobs_list). Encrypting "
                    "to age recipients is allowed; they are public keys.",
        properties={**_PLAN_PROPS, "fingerprint": {"type": "string", "minLength": 64, "maxLength": 64}},
        required=["scope", "target", "fingerprint"], handler=crate_export, gate="inbox", prepare=_export_prepare,
        dedupe_by=("scope", "target", "variant")),
    "crate_jobs_list": ToolSpec(
        description="Crate jobs (export, verify, copy), newest first, with phase, progress and result or error; job_id "
                    "reads one.",
        properties={"job_id": {"type": "string", "maxLength": 64},
                    "limit": {"type": "integer", "minimum": 1, "maximum": K.JOBS_LIMIT_MAX}},
        required=[], handler=crate_jobs_list, gate="read"),
    "crate_job_cancel": ToolSpec(
        description=("Cancel the running crate job; an export cancelled before it is recorded leaves no file, sidecar or "
                     "record behind (a cancel during the second copy only skips that copy)."),
        properties={"job_id": {"type": "string", "maxLength": 64}}, required=["job_id"], handler=crate_job_cancel,
        gate="agent"),
    "crate_bundles_list": ToolSpec(
        description="Recorded crate bundles with each location's state and the crate's original project_root (null when none); project (a project id) keeps one project's; "
                    "bundle_id reads one (and a plain crate's summary); contents true lists a plain crate's files and "
                    "row counts.",
        properties={"bundle_id": _BUNDLE, "contents": {"type": "boolean"},
                    "project": {"type": "integer", "minimum": 1}}, required=[],
        handler=crate_bundles_list, gate="read"),
    "crate_check": ToolSpec(
        description="Verify a crate as a job: quick (whole-file hash), full (every blob and file, the default) or "
                    "drill (full plus an extract and re-hash). Name bundle_id, or folder and name. An encrypted crate "
                    "is checked quick only here. A pass records when it was verified.",
        properties={"bundle_id": _BUNDLE, "folder": _FOLDER, "name": _NAME,
                    "level": {"type": "string", "enum": ["quick", "full", "drill"]}},
        required=[], handler=crate_check, gate="agent"),
    "crate_unpack": ToolSpec(
        description="Write one conversation of a plain crate into a fresh scratch folder of the plugin, laid out as its "
                    "harness home, and answer the resume hint for a test resume. Name bundle_id, or folder and name.",
        properties={"bundle_id": _BUNDLE, "folder": _FOLDER, "name": _NAME,
                    "conversation_id": {"type": "string", "minLength": 8, "maxLength": 64}},
        required=["conversation_id"], handler=crate_unpack, gate="agent"),
    "crate_copy": ToolSpec(
        description="Copy a recorded crate to the second crate folder, verify it there, and record the new location.",
        properties={"bundle_id": _BUNDLE}, required=["bundle_id"], handler=crate_copy, gate="agent"),
    "crate_folder_crates_list": ToolSpec(
        description="The crate files in the primary or second crate folder (share crates included), each with its "
                    "recorded bundle id and original project_root (null when none or encrypted); name narrows to one, and with contents true lists a plain crate's files.",
        properties={"folder": _FOLDER, "name": _NAME, "contents": {"type": "boolean"}}, required=["folder"],
        handler=crate_folder_crates_list, gate="read"),
    "crate_remove": ToolSpec(
        description="Ask the owner to remove a crate: the file and its checksum files move to the Trash (recoverable there), "
                    "never deleted. Name bundle_id (its copy in folder, default primary) or folder and name. A recorded "
                    "crate keeps its record and shows as removed once no copy is left. also_second true also removes the "
                    "same-named copy in the second folder; default false. It waits for their approval every time; a crate "
                    "a job is working on is refused.",
        properties={"bundle_id": _BUNDLE, "folder": _FOLDER, "name": _NAME, "also_second": {"type": "boolean"}},
        required=[], handler=crate_remove, gate="inbox", prepare=_remove_prepare,
        dedupe_by=("bundle_id", "folder", "name")),
    "crate_import_preview": ToolSpec(
        description="Preview restoring a plain crate here, writing nothing: whether it is this computer's own, which project it "
                    "lands in and at which folder (same_paths or relocate with new_root), the conversations and files and how "
                    "each would land (new, already here, grows, conflicts), the table rows by outcome, what is never restored "
                    "and why, blockers (a live session, an unsafe folder) and warnings. Name bundle_id, or folder and name.",
        properties=_IMPORT_OPTIONS,
        required=[], handler=crate_import_preview, gate="read"),
    "crate_import": ToolSpec(
        description="Ask the owner to restore a plain crate into this install, quoting crate_import_preview's fingerprint and the "
                    "same options. It waits for their approval every time, then runs as a job (crate_jobs_list; the receipt is the "
                    "result and crate_imports_list). Every restored session comes back asleep. Encrypted crates and the 'I made "
                    "this crate here' tick are the app's only.",
        properties=_IMPORT_PROPS, required=["fingerprint"], handler=crate_import, gate="inbox", prepare=_import_prepare,
        dedupe_by=("bundle_id", "folder", "name", "mode", "new_root")),
    "crate_import_undo": ToolSpec(
        description="Ask the owner to undo a FINISHED crate restore (import_id from crate_imports_list): it removes exactly what that import "
                    "wrote (database rows, files, backup points, the sessions and project it made) and puts back what it changed. Anything that "
                    "was already here, or changed since, stays and is listed. It waits for their approval every time and is refused (nothing "
                    "written) while a crate job runs, a later restore from the same source stands, or a step cannot be undone cleanly.",
        properties={"import_id": {"type": "string", "maxLength": 64}}, required=["import_id"], handler=crate_import_undo, gate="inbox",
        prepare=_undo_prepare, dedupe_by=("import_id",)),
    "crate_imports_list": ToolSpec(
        description="Receipts of finished crate imports, newest first: what each restored (project, sessions asleep, files, rows), "
                    "what it did not and why, and its warnings. import_id reads one.",
        properties={"import_id": {"type": "string", "maxLength": 64}}, required=[], handler=crate_imports_list, gate="read"),
}
