
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence

from scripts.crate.client import JOB_TIMEOUT_S, CrateClient
from scripts.crate.errors import BlockedError, IntegrityError, VerifyError

OK_STATES = ("done", "done_with_warnings", "noop")

_HINTS: Dict[str, str] = {
    "relocate_required": "restore with --relocate ROOT (the plan's suggested_root is a good choice)",
    "project_choice_needed": "restore with --target-project ID of the project that should take the crate's sessions",
    "conflict": "a file here differs from the crate's; --skip-conflicts keeps the local copy and restores the rest",
    "needs_identity": "the crate is encrypted; export it with --plain (this script never takes a private key)",
}


HELD_BACK_WHY: Dict[str, str] = {"project_files_not_ticked": "project_files", "instructions_held_back": "instructions",
                                 "plugin_data_not_ticked": "plugin_data"}
_PLUGIN_STORE_PREFIX = "plugin_store_"


@dataclass(frozen=True)
class ImportOptions:

    include_project_files: bool = False
    include_instructions: bool = False
    include_plugin_data: bool = False

    def as_body(self) -> Dict[str, Any]:
        return {k: True for k in ("include_project_files", "include_instructions", "include_plugin_data") if getattr(self, k)}

    def asked(self) -> FrozenSet[str]:
        return frozenset(k[len("include_"):] for k in self.as_body())


def export_body(scope: str, target: str, *, variant: str = "own", plain: bool = True, label: Optional[str] = None,
                include_project_files: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {"scope": scope, "target": target, "variant": variant, "include_project_files": include_project_files}
    if plain:
        body["encrypt"] = False
    if label:
        body["label"] = label
    return body


def export_crate(client: CrateClient, body: Mapping[str, Any], timeout: float = JOB_TIMEOUT_S) -> Dict[str, Any]:
    result = client.export(body, timeout)
    return {"bundle_id": result["bundle_id"], "file_name": result.get("file_name"), "sha256": result["sha256"],
            "size": result.get("size"), "warnings": result.get("warnings", [])}


def send_crate(src: CrateClient, dst: CrateClient, bundle_id: str, *, workdir: Optional[Path] = None) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="crate-send-", dir=str(workdir) if workdir else None) as scratch:
        path, sha = src.download_bundle(bundle_id, Path(scratch))
        stored = dst.upload_crate(path, sha)
        if stored["sha256"] != sha:
            raise IntegrityError("the destination stored different bytes than were sent", code="upload_mismatch", detail=stored)
        return {"bundle_id": bundle_id, "name": stored["name"], "sha256": sha, "size": stored["size"]}


def import_body(name: str, *, relocate: Optional[str] = None, target_project: Optional[int] = None,
                skip_conflicts: bool = False, options: ImportOptions = ImportOptions()) -> Dict[str, Any]:
    body: Dict[str, Any] = {"source": {"folder": "primary", "name": name}, "mode": "relocate" if relocate else "same_paths"}
    if relocate:
        body["new_root"] = relocate
    if target_project is not None:
        body["target_project_id"] = target_project
    if skip_conflicts:
        body["skip_conflicts"] = True
    body.update(options.as_body())
    return body


def blockers_text(plan: Mapping[str, Any]) -> str:
    lines: List[str] = []
    for blocker in plan.get("blockers", []):
        code = str(blocker.get("code"))
        hint = _HINTS.get(code)
        extra = ""
        if code == "relocate_required" and (plan.get("project") or {}).get("suggested_root"):
            extra = f" (suggested root: {plan['project']['suggested_root']})"
        lines.append(f"{code}: {blocker.get('detail')}" + (f" -> {hint}{extra}" if hint else ""))
    return "\n".join(lines)


def crate_file_name(name: str) -> str:
    return name if name.endswith((".crate", ".crate.age")) else f"{name}.crate"


def relocate_ignored_text(plan: Mapping[str, Any], relocate: str) -> Optional[str]:
    project = plan.get("project") or {}
    if project.get("action") != "follow_uid":
        return None
    here = project.get("root_to")
    return (f"relocate did not apply: the project already exists here at {here} (matched by its uid), and a project's folder moves only "
            f"through the move route. Nothing was written. Restore without --relocate to add the crate's sessions to the project at "
            f"{here}, or restore on a computer that does not have the project yet (asked for: {relocate})")


def restore_crate(dst: CrateClient, name: str, *, relocate: Optional[str] = None, target_project: Optional[int] = None,
                  skip_conflicts: bool = False, options: ImportOptions = ImportOptions(),
                  timeout: float = JOB_TIMEOUT_S) -> Dict[str, Any]:
    body = import_body(crate_file_name(name), relocate=relocate, target_project=target_project, skip_conflicts=skip_conflicts,
                       options=options)
    plan = dst.plan_import(body)
    if not plan.get("ok") or plan.get("blockers"):
        raise BlockedError("the restore is blocked, nothing was written:\n" + blockers_text(plan), blockers=plan.get("blockers", []))
    ignored = relocate_ignored_text(plan, relocate) if relocate else None
    if ignored:
        raise BlockedError(ignored, blockers=[{"code": "relocate_ignored", "detail": ignored}])
    started = dst.start_import(body, plan["fingerprint"])
    receipt = dst.wait_job(started["job_id"], timeout)["result"]
    return {"import_id": started["import_id"], "provenance": plan.get("provenance"), "plan_fingerprint": plan["fingerprint"],
            "plan_not_restored": plan.get("not_restored", []), "receipt": receipt}


def held_back_of(not_restored: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    found: Dict[tuple, Dict[str, str]] = {}
    for item in not_restored:
        what, why = str(item.get("what")), str(item.get("why"))
        carry = HELD_BACK_WHY.get(why) or ("plugin_data" if what.startswith("plugin_data:") and why.startswith(_PLUGIN_STORE_PREFIX) else None)
        if carry:
            found[(what, why)] = {"what": what, "why": why, "carry": carry}
    return list(found.values())


def verify_receipt(receipt: Mapping[str, Any], *, crate_sha256: Optional[str] = None, asked: Optional[ImportOptions] = None,
                   plan_not_restored: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    problems: List[str] = []
    checks = receipt.get("checks") or {}
    if receipt.get("state") not in OK_STATES:
        problems.append(f"state is {receipt.get('state')!r}")
    if checks.get("file_mismatch"):
        problems.append(f"{len(checks['file_mismatch'])} placed file(s) do not match the crate: {checks['file_mismatch'][:5]}")
    if checks.get("resume_unverified"):
        problems.append(f"conversations that cannot be resumed: {sorted(checks['resume_unverified'])[:5]}")
    awake = [s.get("session_uuid") for s in receipt.get("sessions", []) if not s.get("asleep")]
    if awake:
        problems.append(f"restored sessions that are not asleep: {awake[:5]}")
    if (receipt.get("task_files") or {}).get("failed"):
        problems.append(f"task files failed: {receipt['task_files']['failed'][:5]}")
    if crate_sha256 and receipt.get("crate_sha256") != crate_sha256:
        problems.append("the receipt's crate sha256 is not the sha256 of the crate that was sent")
    held_back = held_back_of([*(receipt.get("not_restored") or []), *plan_not_restored])
    wanted = asked.asked() if asked else frozenset()
    for item in held_back:
        if item["carry"] in wanted:
            problems.append(f"asked for {item['carry']} but it was held back: {item['what']} ({item['why']})")
    files = receipt.get("files") or {}
    rows = sum(int(t.get("inserted", 0)) for t in (receipt.get("rows") or {}).values())
    return {"ok": not problems, "problems": problems, "held_back": held_back, "files_written": files.get("written", 0),
            "files_same": files.get("same", 0), "sessions": len(receipt.get("sessions", [])), "rows_inserted": rows,
            "warnings": len(receipt.get("warnings", []))}


def verify_import(dst: CrateClient, import_id: str, *, crate_sha256: Optional[str] = None, asked: Optional[ImportOptions] = None,
                  plan_not_restored: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    report = verify_receipt(dst.receipt(import_id), crate_sha256=crate_sha256, asked=asked, plan_not_restored=plan_not_restored)
    report["import_id"] = import_id
    if not report["ok"]:
        raise VerifyError("the restore does not match the crate:\n" + "\n".join(report["problems"]), code="verify_failed", detail=report)
    return report


def undo_import(dst: CrateClient, import_id: str) -> Dict[str, Any]:
    preview = dst.undo_preview(import_id)
    if not preview.get("ok"):
        text = "\n".join(f"{b.get('code')}: {b.get('detail')}" for b in preview.get("blockers", []))
        raise BlockedError("the undo is blocked, nothing was written:\n" + text, blockers=preview.get("blockers", []))
    return {"import_id": import_id, "preview": preview, "result": dst.undo(import_id)}


def cycle(src: CrateClient, dst: CrateClient, export: Mapping[str, Any], *, relocate: Optional[str] = None,
          target_project: Optional[int] = None, skip_conflicts: bool = False, options: ImportOptions = ImportOptions(),
          undo: bool = False, timeout: float = JOB_TIMEOUT_S, workdir: Optional[Path] = None) -> Dict[str, Any]:
    exported = export_crate(src, export, timeout)
    sent = send_crate(src, dst, exported["bundle_id"], workdir=workdir)
    restored = restore_crate(dst, sent["name"], relocate=relocate, target_project=target_project, skip_conflicts=skip_conflicts,
                             options=options, timeout=timeout)
    verified = verify_import(dst, restored["import_id"], crate_sha256=sent["sha256"], asked=options,
                             plan_not_restored=restored["plan_not_restored"])
    undone = undo_import(dst, restored["import_id"]) if undo else None
    return {"export": exported, "send": sent, "restore": restored, "verify": verified, "undo": undone}
