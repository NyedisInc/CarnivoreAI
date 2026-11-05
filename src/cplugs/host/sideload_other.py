
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.api.catalog_consent import install_consent_satisfied
from src.core.sessions.ports import InstallRoots, Target
from src.core.skills import digest as folder_digest
from src.core.skills import kinds, roots as root_rules, targets
from src.core.skills.code_gate import staged_plugin_declares_code
from src.core.skills.installer import StagingBusy, staging_root_for
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.core.skills.manifest_preview import preview_manifest
from src.core.skills.manifest_rules import check_manifest, declares_script
from src.core.skills.validate_types import is_script_member
from src.core.skills import plugin_safe_subset
from src.core.skills.plugin_safe_subset import staged_mcp_servers
from src.core.test_write_guard import assert_test_write_allowed
from src.core.theme_catalog_consent import drop_stale_effects_grant
from src.core.ui_preferences_store import UiPreferencesStore
from src.models.catalog_api import InstallConsent
from src.models.themes import ThemeManifest
from src.cplugs.host import sideload, sideload_kind
from src.cplugs.host.sideload import SideloadRefused

logger = structlog.get_logger()

KINDS = (kinds.KIND_THEME, kinds.KIND_SKILL, kinds.KIND_PLUGIN)
CONSENT_REQUIRED = "consent_required"
_install_lock = threading.Lock()


class ConsentRequired(Exception):

    def __init__(self, sheet: Dict[str, Any]) -> None:
        super().__init__(sheet["detail"])
        self.sheet = sheet


@dataclass(frozen=True)
class Env:

    state_dir: Path
    roots: InstallRoots
    prefs: Optional[UiPreferencesStore]


def held_kinds(state_dir: Path, name: str) -> List[str]:
    found = [r["kind"] for r in sideload.installs(state_dir).values() if r.get("name") == name]
    if name in sideload.items(state_dir):
        found.append(kinds.KIND_CPLUG)
    return sorted(found)


def _refuse_root(check: root_rules.RootCheck, name: str) -> SideloadRefused:
    code = "target_exists" if check.state == root_rules.TARGET_EXISTS else "root_unsafe"
    return SideloadRefused(code, f"{check.root / name} cannot be written ({check.state}); a folder that is not a sideload is never replaced", 409)


def _plan(roots: InstallRoots, kind: str, name: str, record: Optional[Dict[str, Any]]) -> List[Tuple[Target, Path, bool]]:
    plan: List[Tuple[Target, Path, bool]] = []
    ours = set((record or {}).get("targets", ()))
    try:
        for target in roots.targets_for(kind, SCOPE_GLOBAL, None):
            check = root_rules.check_root(target, name)
            if check.state == root_rules.ROOT_OK:
                plan.append((target, root_rules.target_dir(target, name), False))
            elif check.state == root_rules.TARGET_EXISTS and target.harness in ours:
                plan.append((target, root_rules.target_dir(target, name), True))
            elif check.state != root_rules.ROOT_ABSENT:
                raise _refuse_root(check, name)
    except root_rules.UnsafeInstallName as exc:
        raise SideloadRefused("name_invalid", str(exc), 409) from exc
    if not plan:
        raise SideloadRefused("root_absent", f"this computer has no {kind} folder to install into", 409)
    return plan


def _body_sha(staged: Path, kind: str) -> str:
    return hashlib.sha256((staged / kinds.manifest_name(kind)).read_bytes()).hexdigest()


def _code_paths(kind: str, staged: Path, executable: frozenset) -> frozenset:
    files = {p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()}
    named = {p for p in files if is_script_member(p, p in executable) or p in plugin_safe_subset.CODE_PATHS
             or p.split("/")[0].lower() in ("monitors", "bin", "workflows")
             or os.path.splitext(p)[1].lower() in plugin_safe_subset.SCRIPT_EXTENSIONS
             or (p.lower().endswith(".md") and plugin_safe_subset.markdown_runs_code(staged / p))}
    if kind == kinds.KIND_THEME:
        named.add(str((_json(staged / "theme.json") or {}).get("effects") or ""))
    named &= files
    return frozenset(named or {kinds.manifest_name(kind)})


def _json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sheet(kind: str, name: str, staged: Path, digest: str, body_sha: str, detail: str, executable: frozenset) -> Dict[str, Any]:
    view = preview_manifest(staged, kind)
    code = _code_paths(kind, staged, executable)
    return {"code": CONSENT_REQUIRED, "kind": kind, "name": name, "item_id": f"{sideload.LOCAL_PUBLISHER}/{name}", "requires_consent": True,
            "publisher": sideload.LOCAL_PUBLISHER, "digest": digest, "digest_prefix": digest[:12], "body_sha": body_sha, "body": view.skill_md_text,
            "body_truncated": view.skill_md_truncated,
            "files": [{"path": f.relpath, "size": f.size, "exec": f.relpath in code} for f in view.files], "total_bytes": view.total_bytes,
            "mcp_servers": staged_mcp_servers(staged) if kind != kinds.KIND_THEME else [], "detail": detail}


def _check_theme_shape(staged: Path) -> None:
    try:
        raw = json.loads((staged / "theme.json").read_text(encoding="utf-8"))
        ThemeManifest(**{**raw, "source": "user", "effectsDigest": None, "feedbackItemId": None, "publisher": None, "scriptTrust": None})
    except (OSError, ValueError, TypeError) as exc:
        raise SideloadRefused("manifest_invalid", f"theme.json would not be listed by the theme picker: {exc}", 422) from exc


def _ships_code(kind: str, staged: Path, entries: Tuple[folder_digest.DigestEntry, ...]) -> bool:
    exec_mode = folder_digest.mode_string(True)
    return (staged_plugin_declares_code(kind, staged) or (kind == kinds.KIND_THEME and declares_script(kind, staged))
            or any(is_script_member(e.relpath, e.mode == exec_mode) for e in entries))


def _stage(roots: InstallRoots, source: Path) -> Tuple[Path, Dict[str, str]]:
    try:
        holder = staging_root_for(roots)
    except StagingBusy as exc:
        raise SideloadRefused("staging_busy", str(exc), 503) from exc
    try:
        return holder / "tree", sideload.copy_tree(source, holder / "tree")
    except (SideloadRefused, OSError):
        targets.remove_tree(holder)
        raise


def _incoming_root(roots: InstallRoots, harness: str) -> Path:
    trash = roots.trash_dir(harness, SCOPE_GLOBAL, None)
    if os.path.lexists(trash) and trash.is_symlink():
        raise targets.TrashFolderIsLink(f"{trash} is a symlink; refusing to write through it")
    assert_test_write_allowed(trash)
    trash.mkdir(parents=True, exist_ok=True)
    os.chmod(trash, targets.DIR_MODE)
    targets.ensure_trash_gitignore(trash)
    return trash


def _place(staged: Path, dest: Path, incoming: Path, exec_paths: frozenset) -> None:
    tmp = incoming / f".incoming-{uuid.uuid4().hex}"
    targets.copy_tree(staged, tmp, exec_paths=exec_paths)
    try:
        assert_test_write_allowed(dest)
        try:
            os.mkdir(dest, 0o700)
        except FileExistsError as exc:
            raise SideloadRefused("target_exists", f"{dest} appeared while loading; it is left alone", 409) from exc
        try:
            os.rename(tmp, dest)
        except OSError:
            try:
                os.rmdir(dest)
            except OSError:
                logger.warning("sideload_claim_not_empty", dest=str(dest))
            raise
    except BaseException:
        targets.remove_tree(tmp)
        raise


def tree_digest(root: Path) -> Tuple[str, Tuple[folder_digest.DigestEntry, ...]]:
    _all, entries = folder_digest.digest_directory(root)
    kept = tuple(e for e in entries if not sideload.is_noise(e.relpath.rsplit("/", 1)[-1]))
    return folder_digest.digest_entries(kept), kept


def _check_unmodified(plan: List[Tuple[Target, Path, bool]], record: Optional[Dict[str, Any]]) -> None:
    for _target, dest, replace in plan:
        if replace and tree_digest(dest)[0] != (record or {}).get("digest"):
            raise SideloadRefused("target_changed", f"{dest} was changed after it was loaded; it is left alone. remove or move it yourself first", 409)


def _undo(done: List[List[Any]]) -> None:
    for dest, displaced, created in reversed(done):
        if created:
            targets.remove_tree(dest)
        if displaced is not None and not os.path.lexists(dest):
            os.rename(displaced, dest)


def _write(plan: List[Tuple[Target, Path, bool]], roots: InstallRoots, staged: Path, exec_paths: frozenset) -> List[List[Any]]:
    done: List[List[Any]] = []
    try:
        for target, dest, replace in plan:
            incoming = _incoming_root(roots, target.harness)
            entry: List[Any] = [dest, None, False]
            done.append(entry)
            if replace:
                entry[1] = targets.move_to_trash(dest, incoming, uuid.uuid4().hex)
            _place(staged, dest, incoming, exec_paths)
            entry[2] = True
    except BaseException:
        _undo(done)
        raise
    return done


def sync(env: Env, kind: str, source: Path, given: Optional[str], consent: Optional[InstallConsent]) -> Dict[str, Any]:
    name = sideload_kind.name_for(kind, source, given)
    key = f"{kind}/{name}"
    with _install_lock:
        record = sideload.installs(env.state_dir).get(key)
        plan = _plan(env.roots, kind, name, record)
        staged, files = _stage(env.roots, source)
        try:
            return _install(env, kind, name, source, staged, files, plan, record, consent)
        finally:
            targets.remove_tree(staged.parent)


def _install(env: Env, kind: str, name: str, source: Path, staged: Path, files: Dict[str, str], plan: List[Tuple[Target, Path, bool]],
             record: Optional[Dict[str, Any]], consent: Optional[InstallConsent]) -> Dict[str, Any]:
    refusal = check_manifest(kind, staged, expected_id=name)
    if refusal is not None:
        raise SideloadRefused("manifest_invalid", refusal, 422)
    if kind == kinds.KIND_THEME:
        _check_theme_shape(staged)
    digest, entries = tree_digest(staged)
    answer = {"id": name, "item_id": f"{sideload.LOCAL_PUBLISHER}/{name}", "kind": kind, "tier": sideload.TIER_LOCAL, "unverified": True,
              "digest": digest, "needs_approval": False, "targets": [t.harness for t, _d, _r in plan]}
    if record and record.get("digest") == digest and all(d.is_dir() for _t, d, _r in plan):
        _check_unmodified(plan, record)
        sideload.put_install(env.state_dir, {**record, "source": str(source), "synced_at": sideload.wall()})
        return {**answer, "unchanged": True, "changed": []}
    body_sha = _body_sha(staged, kind)
    consented = _ships_code(kind, staged, entries)
    executable = frozenset(e.relpath for e in entries if e.mode == folder_digest.mode_string(True))
    if consented and not install_consent_satisfied(consent, digest=digest, body_sha=body_sha):
        raise ConsentRequired(_sheet(kind, name, staged, digest, body_sha, "this folder runs code; show the sheet and send its digest and body_sha back as consent", executable))
    _check_unmodified(plan, record)
    done = _write(plan, env.roots, staged, executable)
    changed = sideload.changed_files((record or {}).get("files", {}), files)
    try:
        _record(env, kind, name, digest, files, changed, source, answer, consented)
    except BaseException:
        _undo(done)
        raise
    if kind == kinds.KIND_THEME and env.prefs is not None:
        for target, dest, _replace in plan:
            drop_stale_effects_grant(env.prefs, name, dest)
    logger.info("sideload_installed", kind=kind, name=name, digest=digest[:12], changed=len(changed))
    return {**answer, "unchanged": False, "changed": changed}


def _record(env: Env, kind: str, name: str, digest: str, files: Dict[str, str], changed: List[str], source: Path, answer: Dict[str, Any], consented: bool) -> None:
    sideload.put_install(env.state_dir, {"kind": kind, "name": name, "digest": digest, "files": files, "changed": changed, "source": str(source),
                                         "synced_at": sideload.wall(), "targets": answer["targets"], "consented_digest": digest if consented else None})


def remove(env: Env, kind: str, name: str) -> bool:
    with _install_lock:
        record = sideload.installs(env.state_dir).get(f"{kind}/{name}")
        if record is None:
            return False
        owned: List[Tuple[Target, Path]] = []
        for target in env.roots.targets_for(kind, SCOPE_GLOBAL, None):
            dest = root_rules.target_dir(target, name)
            linked = target.leaf_dir.is_symlink() or root_rules.symlinked_intermediate(target.leaf_dir) is not None
            if target.harness in record.get("targets", ()) and os.path.lexists(dest) and not linked:
                owned.append((target, dest))
        _check_unmodified([(t, d, True) for t, d in owned], record)
        for target, dest in owned:
            targets.move_to_trash(dest, env.roots.trash_dir(target.harness, SCOPE_GLOBAL, None), uuid.uuid4().hex)
        sideload.forget_install(env.state_dir, kind, name)
    return True
