
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Tuple

from fastapi.concurrency import run_in_threadpool

from src.cplugs.save import import_service as svc
from src.cplugs.save.import_routes import ImportSources
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.old_sources import labels, model
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result, vault_sources

ROUTE_TOOLS: Mapping[str, str] = {
    "/imports/preview": "save_import_preview", "/imports/apply": "save_import", "/imports": "save_imports_list",
    "/imports/{run_id}": "save_imports_list", "/imports/{run_id}/undo": "save_import_remove", "/imports/{run_id}/verify": "save_import_check",
    "/imports/review": "save_import_decide",
}
_PATH_ARGS = ("archives", "folders", "old_stores", "tar_roots", "recovered_root", "plan_applied", "trash_manifests", "rows_file", "reorg_rules")
_EXPECTED = (svc.ImportRefused, VaultUnavailable, model.SourceError, labels.LabelError, vault_sources.SourceUnavailable, OSError)


def _schema() -> Dict[str, Any]:
    props = ImportSources.model_json_schema().get("properties", {})
    return {k: {kk: vv for kk, vv in v.items() if kk != "title"} for k, v in props.items()}


async def _answer(call: Callable[..., Any], *args: Any) -> dict:
    try:
        return tool_result(scrub(await run_in_threadpool(call, *args)))
    except svc.ImportRefused as exc:
        raise ToolError(f"{exc.code}: {exc.detail}") from exc
    except _EXPECTED as exc:
        raise ToolError(f"{type(exc).__name__}: {str(exc)[:300]}") from exc


def _sources(args: dict) -> Dict[str, Any]:
    unknown = sorted(set(args) - set(ImportSources.model_fields) - {"fingerprint", "units", "verdict", "date", "run_id"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    return ImportSources(**{k: v for k, v in args.items() if k in ImportSources.model_fields}).model_dump()


async def save_import_preview(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _answer(svc.preview_blocking, _sources(args))


async def _apply_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    fingerprint = args.get("fingerprint")
    counts = svc.previewed(fingerprint) if isinstance(fingerprint, str) else None
    if counts is None:
        raise ToolError("fingerprint is required: the fingerprint save_import_preview answered (a full preview, not quick)")
    points, extras = counts["points"], counts["extras"]
    sentence = (f"file the old archive in the backup vault, add only: {counts['conversations']['to_import']} conversation(s) as {points['total']} point(s) "
                f"({points['kept']} kept copies), {counts['files']} file(s), {counts['bytes']} bytes, {counts['hidden_from_search']} held back from deep search "
                f"until the once-over, {counts['no_project']} in the group 'imported, no project', and {extras['files']} table dump and audit log file(s) "
                f"as one folder; no old source is touched")
    return {**_sources(args), "fingerprint": fingerprint}, sentence


async def save_import(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    body = _sources(args)
    return await _answer(svc.apply_blocking, body, str(args["fingerprint"]))


async def save_import_remove(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _answer(svc.undo_blocking, str(args["run_id"]))


async def _undo_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    run_id = str(args.get("run_id") or "")
    try:
        receipt = await run_in_threadpool(svc.receipts_blocking, run_id)
    except svc.ImportRefused as exc:
        raise ToolError(f"{exc.code}: {exc.detail}") from exc
    if receipt.get("state") == "undone":
        raise ToolError("nothing_to_undo: this import was already undone")
    return {"run_id": run_id}, (f"take back import {run_id}: remove the {sum((receipt.get('filed') or {}).values())} point(s) it filed and the chunks "
                                f"only it wrote; a point pinned or changed since stays")


async def save_import_check(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _answer(svc.verify_blocking, str(args["run_id"]))


async def save_imports_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    run_id = args.get("run_id")
    if run_id:
        return await _answer(svc.receipts_blocking, str(run_id))
    return await _answer(lambda: {"imports": svc.receipts_blocking()})


async def _review_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    units, verdict, date = args.get("units"), str(args.get("verdict")), str(args.get("date"))
    if not isinstance(units, list) or not units or not all(isinstance(u, str) for u in units):
        raise ToolError("units is a non-empty list of imported conversation ids")
    if verdict not in ("keep", "junk") or not (len(date) == 8 and date.isdigit()):
        raise ToolError("bad_verdict: verdict is keep or junk, date like 20261022")
    return {"units": units, "verdict": verdict, "date": date}, (f"record the once-over verdict '{verdict}' ({date}) on {len(units)} imported conversation(s)"
                                                                 + ("; keep lets them into deep search" if verdict == "keep" else ""))


async def save_import_decide(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _answer(svc.review_blocking, list(args["units"]), str(args["verdict"]), str(args["date"]))


_RUN = {"run_id": {"type": "string", "maxLength": 64}}
TOOLS: Dict[str, ToolSpec] = {
    "save_import_preview": ToolSpec(
        description="Preview taking the old archive and recovered files into the backup vault, writing NOTHING: how many copies are held, covered "
                    "or would be filed, kept copies, labels, conversations with no project, bytes, and the fingerprint save_import must quote. "
                    "Reads the named sources read only (minutes on the real archives; quick true trusts recorded hashes for a faster, non-appliable look).",
        properties=_schema(), required=[], handler=save_import_preview, gate="read", pane_only_args=_PATH_ARGS),
    "save_import": ToolSpec(
        description="Ask the owner to file the previewed old archive conversations in the backup vault, quoting save_import_preview's fingerprint and "
                    "the same sources. Add only: no old source is touched and nothing existing is changed. It waits for their approval every time.",
        properties={**_schema(), "fingerprint": {"type": "string", "minLength": 64, "maxLength": 64}}, required=["fingerprint"],
        handler=save_import, gate="inbox", prepare=_apply_prepare, pane_only_args=_PATH_ARGS, dedupe_by=("fingerprint",)),
    "save_import_remove": ToolSpec(
        description="Ask the owner to take back a finished old archive import (run_id from save_imports_list): removes exactly the points it filed "
                    "and the chunks only it wrote; a point pinned or changed since stays. It waits for their approval every time.",
        properties=_RUN, required=["run_id"], handler=save_import_remove, gate="inbox", prepare=_undo_prepare, dedupe_by=("run_id",)),
    "save_import_check": ToolSpec(
        description="Read an import run's points back from the vault and compare every file to what the run filed (a damaged chunk is reported, "
                    "not raised), and show that every copy sits in exactly one bucket (held, covered, imported, skipped).",
        properties=_RUN, required=["run_id"], handler=save_import_check, gate="read"),
    "save_imports_list": ToolSpec(
        description="Receipts of old archive import runs, newest first: what each filed, refused and counted. run_id reads one.",
        properties=_RUN, required=[], handler=save_imports_list, gate="read"),
    "save_import_decide": ToolSpec(
        description="Ask the owner to record the once-over verdict on imported conversations: keep or junk with a date (20261022). Only adds the "
                    "label reviewed-<date>:<verdict>; keep lets a junk, trash or review labeled import into deep search. Waits for their approval.",
        properties={"units": {"type": "array", "items": {"type": "string", "maxLength": 200}, "minItems": 1, "maxItems": 500},
                    "verdict": {"type": "string", "enum": ["keep", "junk"]}, "date": {"type": "string", "pattern": "^[0-9]{8}$"}},
        required=["units", "verdict", "date"], handler=save_import_decide, gate="inbox", prepare=_review_prepare),
}
