"""The crate plugin's import routes: the plan, the restore and the receipts. ``routes.py`` hangs them on the plugin's one router (``add_to``).
Same auth, switch (409 ``cplug_disabled`` while the plugin is off) and error shape as there.

  POST /imports/plan   {source: {bundle_id} | {folder: primary | second, name}, identity?, mode: same_paths | relocate,
                        new_root?, target_project_id?, skip_conflicts, exclude_conversations: [id], include_project_files,
                        work_in_restored_copy, include_instructions, include_plugin_data, made_here, rules: [[old, new]]}
        200 {version, ok, fingerprint, source, crate: {bundle_id, label, created_at, variant, scope, encrypted, format_version},
             provenance: own_verified | foreign, provenance_reason, project: {action: create | attach | follow_uid, id, name,
             uid, root_from, root_to, name_changed_to?, adoptions}, mapping: [{from, to, source}], enc: [{from, to,
             verified_by}], conversations: [{id, title, class, resume}], rows: {"<store>.<table>": {insert, present, kept_local,
             skipped, reason?}}, rewrites, dropped, files: {count, bytes, by_home, side_folder, boards_beside, conflicts_kept},
             entries, journal: {rebased}, trust, instructions, secrets, not_restored: [{what, why}], space: {needed, free,
             volume}, blockers: [{code, detail}], warnings: [{code, detail}], start_available}.
        ``start_available`` is true only while this router carries ``POST /imports`` (the call that starts the restore); the
        restore dialog offers its restore button only when it is true, so no button ever points at a missing route.
        WRITES NOTHING. A blocked plan is still a 200 with ok false and fingerprint "" when the plan could not be built far
        enough to have one. ``made_here`` and ``identity`` are honored on this route only (never over MCP).
        404 crate_not_found, bundle_not_found; 409 needs_identity, bundle_unreachable; 403 wrong_key; 422 bad_source, bad_mode,
        bad_request, identity_invalid, crate_unreadable; 503 install_unreadable, exports_unavailable.

  POST /imports        {the plan body, fingerprint}. Needs the ``imports.write`` grant (403 permission_missing). Re-plans, requires the
                       fingerprint the plan answered, and starts the restore as a job (kind ``import``, one slot with the other crate jobs).
        202 {job_id, import_id}. 409 plan_changed (detail: the fresh plan), blocked (detail: the blockers), job_busy; 507 no_space;
        and the plan's own refusals. A restore refused after it starts (another project move or import holds the lock) ends the
        job failed with code ``busy``, nothing written. ``GET /jobs/{job_id}`` reports it (phase, progress; the receipt is its result).
  GET /imports         200 {imports: [receipt]}, newest first (finished imports only).
  GET /imports/{import_id}
        200 receipt {import_id, state: done | done_with_warnings | noop, bundle_id, crate_sha256, provenance, project: {id, name,
        root, action}, files, rows, sessions: [{session_uuid, asleep}], conversations, warnings, not_restored, checks, journal,
        task_files, entries, plugin_data, project_files, finished_at}. 404 import_not_found; 500 receipt_unreadable.

  GET /imports/{import_id}/undo
        What taking a FINISHED restore back would do, writing nothing. 200 {import_id, ok, blockers: [{code, detail}], rows_to_remove,
        rows_to_put_back, kept: [{what, why}], files}. ``ok`` false lists why (a later restore from the same source followed it, a crate job
        runs, the restore predates undo, the backup plugin or a plugin store it used is off). 404 import_not_found; 409 already_undone,
        nothing_to_undo; 500 receipt_unreadable.
  POST /imports/{import_id}/undo
        Take the restore back (needs the ``imports.write`` grant, 403 permission_missing). It removes exactly what that import wrote (the
        database rows it inserted, the files it created, the backup points it filed, the sessions and project it created), puts back what
        it deleted or changed (a tombstone it cleared, a board's relinked sidecar's old bytes, config entries it added), and NEVER touches
        what was already here or what changed since: a file whose bytes differ from the crate's, a row someone changed, a row something
        added since points at, all stay and are listed in ``undo.kept``. Refused (409 undo_blocked, detail: the blockers, nothing written)
        while a later restore from the same source stands, the import's record is incomplete, or a step cannot be undone cleanly. The
        receipt becomes ``state: undone`` with ``undone_at`` and ``undo: {rows: {deleted, restored, reverted}, files_removed, folders_removed,
        entries_removed, kept, errors, file_errors}``; ``GET /imports`` still lists it. Pushes ``jobs`` and the projects, Task Manager,
        automation and bookmark resource topics.
        200 {import_id, state: undone, undone_at, undo}. 404 import_not_found; 409 job_busy (a crate job runs), already_undone,
        nothing_to_undo, undo_blocked; 403 permission_missing; 500 receipt_unreadable. MCP twin: ``crate_import_undo`` (owner approval).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Path

from src.cplugs.crate import import_undo, imports
from src.cplugs.crate.errors import answered
from src.cplugs.crate.models import ImportBody, ImportPlanBody
from src.cplugs.sdk import CplugContext


def has_start_route(router: APIRouter) -> bool:
    return any(getattr(r, "path", "").endswith("/imports") and "POST" in (getattr(r, "methods", None) or ()) for r in router.routes)


def add_to(router: APIRouter, ctx_dep: Any) -> None:

    @router.post("/imports/plan")
    async def post_import_plan(body: ImportPlanBody, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """What restoring a crate here would do. Writes nothing."""
        fields = body.model_dump(exclude={"identity"}, exclude_none=True)
        fields["identity"] = body.identity_text()
        out = await answered(imports.plan(ctx, fields, allow_made_here=True))
        out["start_available"] = has_start_route(router)
        return out

    @router.post("/imports", status_code=202)
    async def post_import(body: ImportBody, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Restore the crate the quoted plan describes, as a job."""
        fields = body.model_dump(exclude={"identity"}, exclude_none=True)
        fields["identity"] = body.identity_text()
        return await answered(imports.start(ctx, fields, allow_made_here=True))

    @router.get("/imports")
    async def get_imports(ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """The receipts of finished imports, newest first."""
        return await answered(imports.list_imports(ctx))

    @router.get("/imports/{import_id}/undo")
    async def get_import_undo(import_id: str = Path(..., max_length=64), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """What undoing a finished import would do, and what blocks it. Writes nothing."""
        return await answered(import_undo.preview(ctx, import_id))

    @router.post("/imports/{import_id}/undo")
    async def post_import_undo(import_id: str = Path(..., max_length=64), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Take a finished import back (the module docstring says exactly what that means)."""
        return await answered(import_undo.undo(ctx, import_id))

    @router.get("/imports/{import_id}")
    async def get_import(import_id: str = Path(..., max_length=64), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """One finished import's receipt."""
        return await answered(imports.get_import(ctx, import_id))
