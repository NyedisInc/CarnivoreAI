
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import time
import tomllib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import HTTPException, Request

from src.core.db import connect, db_path_for
from src.core.plugin_registry import plugin_layout
from src.core.skills import kinds
from src.core.skills.consent_via_ddl import CONSENT_SHEET
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, SCOPE_PROJECT, InstallTarget, InstalledItem
from src.models.catalog_names import is_first_party_publisher
from src.plugins.host import (
    identity,
    install_gates,
    runtime,
    secret_store,
    sideload,
    sideload_git,
    sideload_kind,
    sideload_other,
    sideload_routes,
    state as owner_state,
)


def err(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail, **extra})


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def ledger_conn(state_dir: Path) -> Iterator[InstallLedger]:
    conn = connect(db_path_for(state_dir), create=True)
    try:
        yield InstallLedger(conn)
    finally:
        conn.close()


def raw_declared_id(source: Path) -> Optional[str]:
    if (source / "carnivore.toml").is_file():
        try:
            doc = tomllib.loads((source / "carnivore.toml").read_text(encoding="utf-8"))
            val = doc.get("id")
            return val if isinstance(val, str) else None
        except (OSError, ValueError):
            return None
    for fname in ("carnivore.json", "cplug.json"):
        p = source / fname
        if p.is_file():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                val = doc.get("id") if isinstance(doc, dict) else None
                return val if isinstance(val, str) else None
            except (OSError, ValueError):
                return None
    return None


def catalog_items_from_app(request: Request) -> List[Any]:
    services = getattr(request.app.state, "services", None)
    cache = getattr(getattr(services, "catalog", None), "index_cache", None)
    if cache is None:
        return []
    snap = cache.snapshot() if hasattr(cache, "snapshot") else (cache.current() if hasattr(cache, "current") else None)
    if snap is None:
        return []
    verified = getattr(snap, "verified", None)
    items = getattr(verified, "items", None) if verified is not None else getattr(snap, "items", None)
    return list(items) if items else []


def _norm_repo(val: str) -> str:
    text = (val or "").strip().lower().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def check_revoked_github_install(
    request: Request,
    repo_slug: str,
    *,
    name: Optional[str] = None,
    raw_id: Optional[str] = None,
) -> None:
    services = getattr(request.app.state, "services", None)
    cache = getattr(getattr(services, "catalog", None), "index_cache", None)
    if cache is None:
        return
    snap = cache.snapshot() if hasattr(cache, "snapshot") else (cache.current() if hasattr(cache, "current") else None)
    if snap is None:
        return
    verified = getattr(snap, "verified", None)
    rev_items: set[str] = set()
    rev_versions: set[tuple[str, str]] = set()
    rev_keys: set[str] = set()
    if hasattr(cache, "_floor_and_revocations"):
        try:
            _floor, seen = cache._floor_and_revocations()
            for rv in seen or ():
                r_kind = getattr(rv, "kind", "")
                subj = getattr(rv, "subject", "") or ""
                if r_kind == "key" and subj:
                    rev_keys.add(subj.strip().upper())
                elif "@" in subj:
                    iid, _, ver = subj.partition("@")
                    rev_versions.add((iid, ver))
                elif subj:
                    rev_items.add(subj)
        except Exception:
            pass
    if verified is not None:
        if hasattr(cache, "revoked_sets"):
            k_set, v_set = cache.revoked_sets(verified)
            rev_keys.update(str(k).strip().upper() for k in (k_set or ()) if k)
            for subj in v_set or ():
                if "@" in subj:
                    iid, _, ver = subj.partition("@")
                    rev_versions.add((iid, ver))
                else:
                    rev_items.add(subj)
        for rk in getattr(verified, "revoked_keys", ()) or ():
            if isinstance(rk, str) and rk:
                rev_keys.add(rk.strip().upper())
        for rv in getattr(verified, "revocations", ()) or ():
            if isinstance(rv, str):
                if "@" in rv:
                    iid, _, ver = rv.partition("@")
                    rev_versions.add((iid, ver))
                else:
                    rev_items.add(rv)
            else:
                r_kind = getattr(rv, "kind", "")
                subj = getattr(rv, "subject", "") or ""
                if r_kind == "key" and subj:
                    rev_keys.add(subj.strip().upper())
                elif "@" in subj:
                    iid, _, ver = subj.partition("@")
                    rev_versions.add((iid, ver))
                elif subj:
                    rev_items.add(subj)
    store = getattr(cache, "revocations", None)
    if store is not None and hasattr(store, "active"):
        for rec in store.active():
            if rec.key_id:
                rev_keys.add(rec.key_id.strip().upper())
            elif rec.item_id and rec.version:
                rev_versions.add((rec.item_id, rec.version))
            elif rec.item_id:
                rev_items.add(rec.item_id)

    norm_slug = _norm_repo(repo_slug)
    candidates: List[str] = []
    slug_tail = norm_slug.partition("/")[2] if "/" in norm_slug else ""
    for c in (
        raw_id,
        f"{identity.GITHUB_PUBLISHER}/{name}" if name else None,
        f"{identity.GITHUB_PUBLISHER}/{slug_tail}" if slug_tail else None,
        repo_slug,
    ):
        if isinstance(c, str) and c:
            candidates.append(c)
    if hasattr(cache, "item_ids_for_repo"):
        for mapped_id in cache.item_ids_for_repo(norm_slug) or ():
            if isinstance(mapped_id, str) and mapped_id:
                candidates.append(mapped_id)

    all_items: List[Any] = list(getattr(snap, "items", None) or ())
    if verified is not None:
        all_items.extend(list(getattr(verified, "items", None) or ()))
        all_items.extend(list(getattr(verified, "untrusted_items", None) or ()))
    for item in all_items:
        iid = getattr(item, "id", "")
        if not iid:
            continue
        for ver in getattr(item, "versions", None) or ():
            prov = getattr(ver, "provenance", None)
            prepo = _norm_repo(getattr(prov, "repo", "") if prov is not None else "")
            if prepo and prepo == norm_slug:
                candidates.append(iid)
                kid = (getattr(getattr(ver, "sig", None), "key_id", "") or "").strip().upper()
                if kid and kid in rev_keys:
                    raise err(409, "key_untrusted", f"repository {repo_slug!r} publisher key was revoked")
                if (iid, getattr(ver, "v", "")) in rev_versions:
                    raise err(409, "version_revoked", f"repository {repo_slug!r} ({iid}) was revoked")

    cand_lower = {c.lower() for c in candidates if isinstance(c, str) and c}
    tail_lower = {t.lower() for t in (name, raw_id) if isinstance(t, str) and t}
    if verified is not None:
        for ref_item in getattr(verified, "refused", None) or ():
            ref_code = getattr(ref_item, "code", None) or (ref_item.get("code") if isinstance(ref_item, dict) else None)
            if ref_code and ref_code not in ("version_revoked", "key_untrusted"):
                continue
            ref_id = (
                getattr(ref_item, "item_id", None)
                or getattr(ref_item, "id", None)
                or (ref_item.get("item_id") or ref_item.get("id") if isinstance(ref_item, dict) else None)
            )
            ref_repos_raw = (
                getattr(ref_item, "provenance_repos", None)
                or (ref_item.get("provenance_repos") if isinstance(ref_item, dict) else None)
                or ()
            )
            ref_repos = {_norm_repo(r) for r in ref_repos_raw if isinstance(r, str) and r}
            ref_tail = ref_id.partition("/")[2].lower() if isinstance(ref_id, str) and "/" in ref_id else ""
            matched = bool(
                norm_slug in ref_repos
                or (
                    isinstance(ref_id, str)
                    and ref_id
                    and (
                        ref_id.lower() in cand_lower
                        or _norm_repo(ref_id) == norm_slug
                        or (ref_tail and ref_tail in tail_lower)
                    )
                )
            )
            if matched:
                out_code = "key_untrusted" if ref_code == "key_untrusted" else "version_revoked"
                label = ref_id or repo_slug
                raise err(409, out_code, f"repository {repo_slug!r} ({label}) was revoked")

    norm_rev_items = {r.lower() for r in rev_items}
    norm_rev_ver_ids = {iid.lower() for iid, _v in rev_versions}
    for cand in candidates:
        low = cand.lower()
        if low in norm_rev_items or low in norm_rev_ver_ids:
            raise err(409, "version_revoked", f"repository {repo_slug!r} ({cand}) was revoked in catalog")


def check_hijack(
    state_dir: Path,
    name: str,
    raw_id: Optional[str],
    canonical_url: str,
    shipped_ids: Any,
    renamed_ids: Any,
    catalog_items: List[Any],
    *,
    kind: str,
) -> None:
    if kind == kinds.KIND_CPLUG:
        if not identity.INSTALL_NAME.match(name):
            raise err(422, "name_invalid", f"plugin id must match {identity.INSTALL_NAME.pattern}")
        if name in identity.reserved_names(shipped_ids) or name in set(renamed_ids):
            raise err(409, "catalog_id_hijack", f"{name} is a reserved built-in or host plugin ID")
    if isinstance(raw_id, str) and "/" in raw_id:
        pub, _, tail = raw_id.partition("/")
        if is_first_party_publisher(pub) or pub == identity.OWNER_PUBLISHER or pub in identity.RESERVED_PUBLISHERS or pub in set(shipped_ids):
            raise err(409, "catalog_id_hijack", f"GitHub repo may not claim reserved publisher {pub!r}")
        for item in catalog_items:
            iid = str(getattr(item, "id", "") or "")
            if iid == raw_id or (iid.partition("/")[2] == tail and getattr(item, "kind", "") == kind):
                raise err(409, "catalog_id_hijack", f"GitHub repo claims Warez Verified catalog ID {iid}")
    for item in catalog_items:
        iid = str(getattr(item, "id", "") or "")
        if getattr(item, "kind", "") == kind and iid.partition("/")[2] == name:
            raise err(409, "catalog_id_hijack", f"{name} matches Warez Verified catalog item {iid}")
    if kind == kinds.KIND_CPLUG:
        held = identity.lookup(state_dir, name)
        expected_id = f"{identity.GITHUB_PUBLISHER}/{name}"
        if held is not None:
            if held.catalog_id != expected_id:
                raise err(409, "catalog_id_hijack", f"{name} is already owned by {held.catalog_id}")
            if held.source and held.source != canonical_url:
                raise err(409, "name_taken", f"{name} is already installed from {held.source}")
    else:
        path = db_path_for(state_dir)
        if path.exists():
            with ledger_conn(state_dir) as ledger:
                for row in ledger.list():
                    if row.kind == kind and row.item_id.partition("/")[2] == name:
                        if row.item_id != f"{identity.GITHUB_PUBLISHER}/{name}" or row.publisher_key_id:
                            raise err(409, "catalog_id_hijack", f"{name} is already owned by Warez Verified item {row.item_id}")


def clone_for_preview_or_install(state_dir: Path, url: str, ref: Optional[str], parts: tuple) -> Tuple[Path, Path, str]:
    checkout = sideload_git.incoming(state_dir)
    try:
        commit = sideload_git.fetch(checkout, url, ref)
        source_dir = sideload_git.source_in(checkout, parts)
        return checkout, source_dir, commit
    except BaseException:
        shutil.rmtree(checkout, ignore_errors=True)
        raise


def preview_cplug_blocking(
    state_dir: Path,
    source_dir: Path,
    canonical_url: str,
    shipped_ids: Any,
    renamed_ids: Any,
    catalog_items: List[Any],
    given_name: Optional[str] = None,
) -> Dict[str, Any]:
    raw_id = raw_declared_id(source_dir)
    if isinstance(raw_id, str) and "/" in raw_id:
        candidate = given_name or raw_id.rpartition("/")[2]
        check_hijack(state_dir, candidate, raw_id, canonical_url, shipped_ids, renamed_ids, catalog_items, kind=kinds.KIND_CPLUG)
    name = sideload_routes.name_of(source_dir, given_name)
    check_hijack(state_dir, name, raw_id, canonical_url, shipped_ids, renamed_ids, catalog_items, kind=kinds.KIND_CPLUG)
    staging, files, manifest = sideload.stage(state_dir, name, source_dir, dev=True)
    try:
        install_gates.check_files(staging)
    except install_gates.CplugGateRefusal as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise err(409, exc.code, exc.detail) from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    manifest_gh = replace(manifest, tier=identity.TIER_UNVERIFIED_GITHUB, default_enabled=False)
    return {"name": name, "staging": staging, "files": files, "manifest": manifest_gh}


def agent_plugin_payload(
    name: str,
    staged: Path,
    digest: str,
    body_sha: str,
    scope: str,
    project_path: Optional[str],
    canonical_url: str,
    ref: Optional[str],
    commit: str,
    subdir: str,
) -> Dict[str, Any]:
    sheet = sideload_other._sheet(kinds.KIND_PLUGIN, name, staged, digest, body_sha, "direct GitHub agent-plugin install", frozenset())
    sheet["item_id"] = f"{identity.GITHUB_PUBLISHER}/{name}"
    sheet["publisher"] = identity.GITHUB_PUBLISHER
    manifest_json = sideload_kind._read_json(staged / ".claude-plugin" / "plugin.json") or {}
    gh = sideload_git.github_owner_repo(canonical_url)
    source_meta: Dict[str, Any] = {"url": canonical_url, "ref": ref, "commit": commit, "subdir": subdir}
    if gh is not None:
        source_meta["owner"], source_meta["repo"] = gh
    return {
        "id": name,
        "item_id": f"{identity.GITHUB_PUBLISHER}/{name}",
        "name": str(manifest_json.get("name") or name),
        "description": str(manifest_json.get("description") or ""),
        "version": str(manifest_json.get("version") or "0.0.0"),
        "kind": "agent-plugin",
        "trust_tier": "unverified_github",
        "trust_badge": "Unverified GitHub Repo",
        "unverified": True,
        "code_sha256": digest,
        "permissions": [],
        "risks": {},
        "warnings": [],
        "consent_sheet": sheet,
        "secrets": [],
        "scope": scope,
        "supported_scopes": [SCOPE_GLOBAL, SCOPE_PROJECT],
        "project_path": project_path,
        "runtime_active": True,
        "source": source_meta,
    }


def validate_inline_secrets(manifest: Any, secrets_payload: Optional[Dict[str, str]]) -> None:
    if not secrets_payload:
        return
    for secret_name, secret_val in secrets_payload.items():
        try:
            secret_store.SecretStore.validate_one(manifest, secret_name, secret_val)
        except secret_store.SecretError as exc:
            status = 404 if exc.code == "secret_unknown" else (503 if exc.code in ("keychain_refused", "secrets_unreadable", "secrets_unwritable") else 422)
            raise err(status, exc.code, str(exc)) from exc


def store_inline_secrets_tx(
    state_dir: Path,
    install_key: str,
    manifest: Any,
    secrets_payload: Optional[Dict[str, str]],
) -> Tuple[Dict[str, Dict[str, bool]], Optional[secret_store.SecretsSnapshot]]:
    store = secret_store.SecretStore(state_dir)
    snapshot: Optional[secret_store.SecretsSnapshot] = None
    if secrets_payload:
        try:
            snapshot = store.set_many(install_key, manifest, secrets_payload)
        except secret_store.SecretError as exc:
            status = 404 if exc.code == "secret_unknown" else (503 if exc.code in ("keychain_refused", "secrets_unreadable", "secrets_unwritable") else 422)
            raise err(status, exc.code, str(exc)) from exc
    out: Dict[str, Dict[str, bool]] = {}
    for s in manifest.network.secrets:
        st = store.status(install_key, manifest, s.name)
        out[s.name] = {"present": bool(st.get("secret_present")), "needs_reentry": bool(st.get("needs_reentry"))}
    return out, snapshot


def store_inline_secrets(
    state_dir: Path,
    install_key: str,
    manifest: Any,
    secrets_payload: Optional[Dict[str, str]],
) -> Dict[str, Dict[str, bool]]:
    out, _snap = store_inline_secrets_tx(state_dir, install_key, manifest, secrets_payload)
    return out


@dataclass
class GithubCommitTx:

    state_dir: Path
    name: str
    item_id: str
    install_key: str
    code_root: Path
    code_backup: Optional[Path]
    prev_identity: Optional[identity.InstallRecord]
    prev_ledger_row: Optional[InstalledItem]
    prev_git_record: Optional[Dict[str, Any]]
    checkout_backup: Optional[Path]
    prev_owner_entry: Optional[Dict[str, Any]]
    secrets_snapshot: Optional[secret_store.SecretsSnapshot] = None

    def finalize(self) -> None:
        if self.code_backup is not None and os.path.lexists(self.code_backup):
            if self.code_backup.is_dir() and not self.code_backup.is_symlink():
                shutil.rmtree(self.code_backup, ignore_errors=True)
            else:
                self.code_backup.unlink(missing_ok=True)
        if self.checkout_backup is not None and self.checkout_backup.exists():
            shutil.rmtree(self.checkout_backup, ignore_errors=True)

    def rollback(self) -> None:
        if self.secrets_snapshot is not None:
            secret_store.SecretStore(self.state_dir).restore_snapshot(self.secrets_snapshot)
        if self.prev_owner_entry is None:
            try:
                owner_state.forget(self.state_dir, self.name)
            except owner_state.StateWriteFailed:
                pass
        else:
            try:
                owner_state.restore_entry(self.state_dir, self.name, self.prev_owner_entry)
            except owner_state.StateWriteFailed:
                pass
        if self.prev_git_record is None:
            try:
                sideload_git.forget(self.state_dir, self.name)
            except sideload.SideloadRefused:
                shutil.rmtree(sideload_git.checkout_of(self.state_dir, self.name), ignore_errors=True)
        else:
            dest = sideload_git.checkout_of(self.state_dir, self.name)
            if self.checkout_backup is not None and self.checkout_backup.exists():
                shutil.rmtree(dest, ignore_errors=True)
                os.replace(self.checkout_backup, dest)
            try:
                sideload_git.restore_record(self.state_dir, self.name, self.prev_git_record)
            except sideload.SideloadRefused:
                pass
        if db_path_for(self.state_dir).exists():
            with ledger_conn(self.state_dir) as ledger:
                if self.prev_ledger_row is None:
                    ledger.delete(self.install_key)
                else:
                    cur = ledger.get(self.prev_ledger_row.install_id)
                    if cur is not None:
                        ledger.update(
                            cur.install_id,
                            expected_revision=cur.revision,
                            now=stamp(),
                            version=self.prev_ledger_row.version,
                            digest=self.prev_ledger_row.digest,
                        )
        if os.path.lexists(self.code_root):
            if self.code_root.is_dir() and not self.code_root.is_symlink():
                shutil.rmtree(self.code_root, ignore_errors=True)
            else:
                self.code_root.unlink(missing_ok=True)
        if self.code_backup is not None and os.path.lexists(self.code_backup):
            os.replace(self.code_backup, self.code_root)
        if self.prev_identity is None:
            try:
                identity.release_install(self.state_dir, self.name)
            except (identity.LedgerUnreadable, owner_state.StateWriteFailed):
                pass
        else:
            try:
                identity.restore_install(self.state_dir, self.prev_identity)
            except (identity.LedgerUnreadable, owner_state.StateWriteFailed):
                pass


def commit_cplug_github_tx(
    state_dir: Path,
    name: str,
    staging: Path,
    files: Dict[str, str],
    manifest: Any,
    canonical_url: str,
    source_dir: Path,
    checkout: Path,
    *,
    commit_sha: str = "",
    repo_slug: str = "",
) -> GithubCommitTx:
    del files, source_dir
    root = plugin_layout.code_root(state_dir, name)
    if os.path.lexists(root):
        sideload.contained(root, root.parent)
    root.parent.mkdir(parents=True, exist_ok=True)

    prev_identity = identity.lookup(state_dir, name)
    item_id = f"{identity.GITHUB_PUBLISHER}/{name}"
    prev_ledger_row: Optional[InstalledItem] = None
    if db_path_for(state_dir).exists():
        with ledger_conn(state_dir) as ledger:
            prev_ledger_row = ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
    prev_git_record = sideload_git.records(state_dir).get(name)
    prev_owner_entry = owner_state.stored_entry(state_dir, name)

    code_backup: Optional[Path] = None
    checkout_backup: Optional[Path] = None
    install_rec = identity.register_install(
        state_dir,
        name,
        item_id,
        runtime.reserved_plugin_ids(),
        commit_sha=commit_sha,
        source=canonical_url,
        github=True,
        renamed_ids=runtime.renamed_ids(),
    )
    tx = GithubCommitTx(
        state_dir=state_dir,
        name=name,
        item_id=item_id,
        install_key=install_rec.uuid,
        code_root=root,
        code_backup=code_backup,
        prev_identity=prev_identity,
        prev_ledger_row=prev_ledger_row,
        prev_git_record=prev_git_record,
        checkout_backup=checkout_backup,
        prev_owner_entry=prev_owner_entry,
    )
    try:
        if os.path.lexists(root):
            backup = root.parent / f".old-{name}-{os.getpid()}-{time.monotonic_ns()}"
            os.replace(root, backup)
            tx.code_backup = backup
        os.replace(staging, root)

        with ledger_conn(state_dir) as ledger:
            row = ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
            if row is None:
                ledger.insert(InstalledItem(
                    install_id=install_rec.uuid,
                    item_id=item_id,
                    kind=kinds.KIND_CPLUG,
                    publisher=identity.GITHUB_PUBLISHER,
                    name=f"cplug-{identity.GITHUB_PUBLISHER}-{name}",
                    version=manifest.version,
                    digest=manifest.code_digest,
                    scope=SCOPE_GLOBAL,
                    project_path=GLOBAL_PROJECT_PATH,
                    auto_update=False,
                    source_index_url=canonical_url,
                    consented_digest=manifest.code_digest,
                    consented_body_sha=None,
                    publisher_key_id="",
                    revision=1,
                    installed_at=stamp(),
                    updated_at=stamp(),
                    consent_via=CONSENT_SHEET,
                    provenance_repo=repo_slug,
                    commit_sha=commit_sha,
                ))
            else:
                ledger.update(
                    row.install_id,
                    expected_revision=row.revision,
                    now=stamp(),
                    version=manifest.version,
                    digest=manifest.code_digest,
                    provenance_repo=repo_slug,
                    commit_sha=commit_sha,
                )

        dest = sideload_git.checkout_of(state_dir, name)
        if dest.exists():
            c_backup = sideload_git.checkouts_root(state_dir) / f".old-tx-{name}-{os.getpid()}-{time.monotonic_ns()}"
            os.replace(dest, c_backup)
            tx.checkout_backup = c_backup
        sideload_git.adopt(state_dir, checkout, name)
        return tx
    except BaseException:
        tx.rollback()
        raise


def commit_cplug_github(
    state_dir: Path,
    name: str,
    staging: Path,
    files: Dict[str, str],
    manifest: Any,
    canonical_url: str,
    source_dir: Path,
    checkout: Path,
) -> str:
    tx = commit_cplug_github_tx(state_dir, name, staging, files, manifest, canonical_url, source_dir, checkout)
    tx.finalize()
    return tx.install_key


def install_agent_plugin_blocking(
    state_dir: Path,
    env: sideload_other.Env,
    source_dir: Path,
    name: str,
    scope: str,
    project_path: Optional[str],
    canonical_url: str,
    consent: Optional[Dict[str, Any]],
    *,
    commit_sha: str = "",
    repo_slug: str = "",
) -> Dict[str, Any]:
    plan = []
    for target in env.roots.targets_for(kinds.KIND_PLUGIN, scope, project_path):
        check = sideload_other.root_rules.check_root(target, name)
        if check.state == sideload_other.root_rules.ROOT_OK:
            plan.append((target, sideload_other.root_rules.target_dir(target, name), False))
        elif check.state == sideload_other.root_rules.TARGET_EXISTS:
            plan.append((target, sideload_other.root_rules.target_dir(target, name), True))
        elif check.state != sideload_other.root_rules.ROOT_ABSENT:
            raise sideload_other._refuse_root(check, name)
    if not plan:
        raise sideload.SideloadRefused("root_absent", "this computer has no agent-plugin folder for the chosen scope", 409)

    staged, files = sideload_other._stage(env.roots, source_dir)
    try:
        refusal = sideload_other.check_manifest(kinds.KIND_PLUGIN, staged, expected_id=name)
        if refusal is not None:
            raise sideload.SideloadRefused("manifest_invalid", refusal, 422)
        digest, entries = sideload_other.tree_digest(staged)
        body_sha = sideload_other._body_sha(staged, kinds.KIND_PLUGIN)
        if not consent or consent.get("digest") != digest or consent.get("body_sha") != body_sha:
            raise err(422, "consent_required", "explicit consent matching preview digest and body_sha is required")
        executable = frozenset(e.relpath for e in entries if e.mode == sideload_other.folder_digest.mode_string(True))
        done = sideload_other._write(plan, env.roots, staged, executable)
        item_id = f"{identity.GITHUB_PUBLISHER}/{name}"
        proj_key = project_path or GLOBAL_PROJECT_PATH
        try:
            with ledger_conn(state_dir) as ledger:
                row = ledger.find(item_id, scope, proj_key)
                install_id = row.install_id if row is not None else uuid.uuid4().hex
                targets = tuple(
                    InstallTarget(install_id=install_id, harness=t.harness, path=str(dest))
                    for t, dest, _r in plan
                )
                manifest_json = sideload_kind._read_json(staged / ".claude-plugin" / "plugin.json") or {}
                ver = str(manifest_json.get("version") or "0.0.0")
                if row is None:
                    ledger.insert(
                        InstalledItem(
                            install_id=install_id,
                            item_id=item_id,
                            kind=kinds.KIND_PLUGIN,
                            publisher=identity.GITHUB_PUBLISHER,
                            name=name,
                            version=ver,
                            digest=digest,
                            scope=scope,
                            project_path=proj_key,
                            auto_update=False,
                            source_index_url=canonical_url,
                            consented_digest=digest,
                            consented_body_sha=body_sha,
                            publisher_key_id="",
                            revision=1,
                            installed_at=stamp(),
                            updated_at=stamp(),
                            consent_via=CONSENT_SHEET,
                            provenance_repo=repo_slug,
                            commit_sha=commit_sha,
                        ),
                        targets,
                    )
                else:
                    ledger.update(
                        row.install_id,
                        expected_revision=row.revision,
                        now=stamp(),
                        version=ver,
                        digest=digest,
                        provenance_repo=repo_slug,
                        commit_sha=commit_sha,
                    )
                    ledger.replace_targets(row.install_id, targets)
        except BaseException:
            sideload_other._undo(done)
            raise
        return {
            "id": name,
            "install_id": install_id,
            "item_id": item_id,
            "kind": "agent-plugin",
            "trust_tier": "unverified_github",
            "trust_badge": "Unverified GitHub Repo",
            "unverified": True,
            "code_sha256": digest,
            "scope": scope,
            "supported_scopes": [SCOPE_GLOBAL, SCOPE_PROJECT],
            "project_path": project_path,
            "enabled": True,
            "targets": [t.harness for t, _d, _r in plan],
        }
    finally:
        shutil.rmtree(staged.parent, ignore_errors=True)
