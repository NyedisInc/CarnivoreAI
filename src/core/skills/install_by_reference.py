
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.catalog import install_reporter, release_vouch
from src.core.catalog.verify import check_digest
from src.core.skills.consent_via_ddl import CONSENT_PACK
from src.core.skills.digest import hash_file
from src.core.skills.install_types import CHOICE_REPLACE, InstallRefusal
from src.core.skills.kinds import KIND_CPLUG, manifest_name
from src.core.skills.ledger_types import SCOPE_GLOBAL, AlreadyInstalled
from src.core.skills.records import SIDECAR_NAME, read_sidecar

logger = structlog.get_logger()

SYNC_OVERRIDDEN_REVIEWS = True
IN_SYNC, CONFLICT, UNKNOWN = "in sync", "conflict", "unknown"

REASONS = {
    "not_loaded": "catalog not loaded yet, will retry", "not_in_catalog": "not in this computer's catalog",
    "untrusted_key": "signed by a key this computer does not trust", "kind_changed": "catalog item changed kind",
    "cplug_by_hand": "a cplug is installed and updated by hand",
    "version_not_in_catalog": "version not in this computer's catalog, will retry",
    "digest_differs": "digest differs from this computer's catalog", "key_revoked": "key revoked",
    "version_revoked": "version revoked", "signature_failed": "signature check failed",
    "review_not_clean": "review not clean, install it there by hand", "unreachable": "catalog unreachable, will retry",
    "busy": "busy, will retry", "archive_refused": "archive refused", "consent_mismatch": "consent does not match these bytes",
    "fork_there": "kept as a fork there", "other_item_there": "another catalog item there",
    "orphan_record_there": "catalog folder with no install record here", "family_missing_here": "installed without {family} here",
    "scope_shadowed": "a project install of that name hides it", "root_missing": "skills folder missing",
    "root_link": "skills folder is a link", "name_taken": "name used by a skill this app cannot replace",
    "name_reserved": "name reserved", "no_harness": "{family} not on this computer", "bad_entry": "alpha sent a bad catalog entry",
    "keeps_changing": "keeps changing, held", "unknown": "unknown, will retry",
}
_PLANNER = {"scope_shadowed": "scope_shadowed", "root_absent": "root_missing", "root_is_symlink": "root_link",
            "root_parent_is_symlink": "root_link", "name_taken": "name_taken", "name_reserved": "name_reserved",
            "no_harness_present": "no_harness", "digest_mismatch": "digest_differs", "scripts_not_supported": "consent_mismatch"}


def reason_for(code: str, family: str = "") -> str:
    return REASONS.get(code, REASONS["unknown"]).format(family=family)


def is_transient(code: str) -> bool:
    return reason_for(code).endswith("will retry")


@dataclass(frozen=True)
class Ref:

    item_id: str
    kind: str
    version: str
    digest: str
    body_sha: str
    families: tuple[str, ...] = ("claude",)


@dataclass
class Outcome:

    state: str
    code: str = ""
    install_id: str = ""
    placed: bool = False
    changed: bool = False
    version_changed: bool = False
    replaced_edit: bool = False
    started: float = 0.0
    disk: str = ""
    missing_families: tuple[str, ...] = ()

    @property
    def retry(self) -> bool:
        return bool(self.code) and is_transient(self.code)


@dataclass
class _Survey:
    mine: Any = None
    forked: bool = False
    other: bool = False
    orphan: bool = False
    handmade: bool = False
    drifted: bool = False
    harnesses: frozenset = field(default_factory=frozenset)


def _survey(services: Any, ref: Ref) -> _Survey:
    from src.core.skill_watch import sentinel
    from src.core.skill_watch.store import default_watch_store

    name, out = ref.item_id.split("/", 1)[1], _Survey()
    leaves = [t.leaf_dir for t in services.install_roots.targets_for(ref.kind, SCOPE_GLOBAL, None) if t.harness in ref.families]
    with services.catalog.ledger() as ledger:
        rows = [r for r in ledger.list() if r.scope == SCOPE_GLOBAL]
        out.mine = next((r for r in rows if r.item_id == ref.item_id), None)
        out.forked = out.mine is not None and out.mine.install_id in ledger.forked_ids()
        mine_paths = []
        if out.mine is not None:
            targets = ledger.targets(out.mine.install_id)
            mine_paths = [t.path for t in targets]
            out.harnesses = frozenset(t.harness for t in targets)
        theirs = {str(Path(t.path)) for r in rows if r.item_id != ref.item_id for t in ledger.targets(r.install_id)}
    for leaf in leaves:
        folder = leaf / name
        if str(folder) in theirs:
            out.other = True
        if folder.is_symlink() or not folder.is_dir() or str(folder) in mine_paths:
            continue
        record = read_sidecar(folder)
        if record is None and not (folder / SIDECAR_NAME).exists():
            out.handmade = True
        elif record is None or f"{record.publisher}/{record.name}" != ref.item_id:
            out.other = True
        elif out.mine is None:
            out.orphan = True
    if out.mine is not None and mine_paths:
        out.drifted = sentinel.check_row(default_watch_store(), out.mine.install_id, out.mine.digest, mine_paths).state == sentinel.STATE_DRIFTED
    return out


async def _gates(services: Any, ref: Ref) -> tuple[Any, Any, Optional[str]]:
    from src.api.catalog_consent import carries_scripts  # noqa: F401
    from src.api.catalog_one_click import review_is_clean
    from src.api.catalog_views import find_item

    cache = services.catalog.index_cache
    snapshot = cache.snapshot()
    if snapshot.verified is None:
        snapshot = await cache.get()
    if snapshot.verified is None:
        return None, None, "not_loaded"
    item, untrusted = find_item(snapshot, ref.item_id)
    if item is None:
        snapshot = await cache.get()
        item, untrusted = find_item(snapshot, ref.item_id)
    if item is None:
        return None, None, "not_in_catalog"
    if untrusted:
        return None, None, "untrusted_key"
    if item.kind != ref.kind:
        return None, None, "kind_changed"
    if item.kind == KIND_CPLUG:
        return None, None, "cplug_by_hand"
    version = next((v for v in item.versions if v.v == ref.version), None)
    if version is None:
        snapshot = await cache.get()
        item, _ = find_item(snapshot, ref.item_id)
        version = next((v for v in item.versions if v.v == ref.version), None) if item is not None else None
        if version is None:
            return None, None, "version_not_in_catalog"
    if version.digest != ref.digest:
        return None, None, "digest_differs"
    revoked = await asyncio.to_thread(cache.revoked_sets, snapshot.verified)
    key = services.catalog.trust_root.publisher_key
    code = release_vouch.vouch(item, version, ref.digest, revoked, publisher_key=key,
                               pinned_key_id=key.key_id.strip().upper() if key is not None else None)
    if code is not None:
        return None, None, {"not_pinned": "untrusted_key", "digest_differs": "digest_differs"}.get(code, code)
    review = version.review
    overridden = SYNC_OVERRIDDEN_REVIEWS and review is not None and review.status == "reviewed" and review.override is not None
    if not review_is_clean(version) and not overridden:
        return None, None, "review_not_clean"
    return item, version, None


async def _fetch(services: Any, item: Any, version: Any) -> tuple[Any, Any, Optional[str]]:
    from fastapi import HTTPException

    from src.api.catalog_consent import carries_scripts
    from src.api.catalog_install_support import fetch_and_stage_with
    from src.core.skills.installer import STAGING_BUSY
    from src.core.skills.validate import ArchiveRefused

    try:
        staging, staged = await fetch_and_stage_with(services, item, version, allow_scripts=carries_scripts(version))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return None, None, "busy" if detail.get("code") == STAGING_BUSY else ("unreachable" if exc.status_code >= 500 else "archive_refused")
    except (ArchiveRefused, OSError) as exc:
        logger.info("pack_ref_fetch_refused", item_id=item.id, error=type(exc).__name__)
        return None, None, "archive_refused" if isinstance(exc, ArchiveRefused) else "unreachable"
    return staging, staged, None


def _plan_and_apply(services: Any, item: Any, version: Any, staged: Any, body_sha: str, allow: bool, families: frozenset,
                    choice: Optional[str], listing: tuple, present: frozenset) -> Any:
    from src.core.skills.install_plan import plan_install
    from src.core.skills.installer import apply_install

    with services.catalog.ledger() as ledger:
        decided = plan_install(item=item, version=version, staged=staged, scope=SCOPE_GLOBAL, project_path=None, ledger=ledger,
                               roots=services.install_roots, discovery_listing=listing, choice=choice, allow_scripts=allow,
                               harnesses=present & families, create_roots=True)
        if isinstance(decided, InstallRefusal):
            return decided
        return apply_install(decided, ledger=ledger, roots=services.install_roots, clock=services.clock,
                             source_index_url=services.catalog.index_url(), publisher_key_id=services.catalog.publisher_key_id,
                             consent_via=CONSENT_PACK)


async def install_exact(services: Any, ref: Ref, *, families: Optional[tuple[str, ...]] = None) -> Outcome:
    from fastapi import HTTPException

    from src.api.catalog_consent import install_consent_satisfied, staged_plugin_declares_code
    from src.api.catalog_install_support import discovery_listing
    from src.api.catalog_installed_support import apply_update_with
    from src.core.skills.installer import discard_staging
    from src.models.catalog_api import InstallConsent

    started = time.time()
    fams = tuple(families or ref.families)
    ref = Ref(ref.item_id, ref.kind, ref.version, ref.digest, ref.body_sha, fams)
    try:
        item, version, code = await _gates(services, ref)
        if code is not None:
            return Outcome(UNKNOWN if code == "not_loaded" else CONFLICT, code, started=started)
        state = await asyncio.to_thread(_survey, services, ref)
        for flag, why in ((state.forked, "fork_there"), (state.other, "other_item_there"), (state.orphan, "orphan_record_there")):
            if flag:
                return Outcome(CONFLICT, why, started=started)
        missing = tuple(f for f in fams if state.mine is not None and f not in state.harnesses)
        if state.mine is not None and state.mine.version == ref.version and not state.drifted:
            return Outcome(IN_SYNC, install_id=state.mine.install_id, missing_families=missing, started=started)
        staging, staged, code = await _fetch(services, item, version)
        if code is not None:
            return Outcome(UNKNOWN if is_transient(code) else CONFLICT, code, started=started)
        try:
            if check_digest(version.digest, staged.digest) is not None:
                return Outcome(CONFLICT, "digest_differs", started=started)
            body_sha = (await asyncio.to_thread(hash_file, staged.path / manifest_name(item.kind)))[0]
            allow = version.scripts > 0 or await asyncio.to_thread(staged_plugin_declares_code, item.kind, staged.path)
            if allow and not install_consent_satisfied(InstallConsent(digest=ref.digest, body_sha=ref.body_sha, scripts=True),
                                                       digest=staged.digest, body_sha=body_sha):
                return Outcome(CONFLICT, "consent_mismatch", started=started)
            if state.mine is not None:
                row = state.mine
                try:
                    done = await asyncio.to_thread(apply_update_with, services, row=row, version=version, staged=staged,
                                                   body_sha=body_sha, expected_revision=row.revision)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    with services.catalog.ledger() as ledger:
                        now = ledger.get(row.install_id)
                    if now is not None and now.version == ref.version:
                        return Outcome(IN_SYNC, install_id=row.install_id, changed=True, started=started)
                    return Outcome(UNKNOWN, "unknown", install_id=row.install_id, changed=True, disk=ref.digest, started=started)
                install_reporter.schedule_for(services, done.item_id, done.version)
                return Outcome(IN_SYNC, install_id=done.install_id, changed=True, version_changed=row.version != ref.version,
                               replaced_edit=state.drifted, missing_families=missing, started=started)
            listing = await asyncio.to_thread(discovery_listing, services.install_roots)
            present = frozenset(await asyncio.to_thread(services.install_roots.present_harnesses))
            result = await asyncio.to_thread(_plan_and_apply, services, item, version, staged, body_sha, allow, frozenset(fams),
                                             CHOICE_REPLACE if state.handmade else None, listing, present)
        finally:
            await asyncio.to_thread(discard_staging, staging)
        if isinstance(result, InstallRefusal):
            if result.code == "already_installed":
                return Outcome(UNKNOWN, "unknown", started=started)
            return Outcome(CONFLICT, _PLANNER.get(result.code, "unknown"), started=started)
        install_reporter.schedule_for(services, result.item_id, result.version)
        return Outcome(IN_SYNC, install_id=result.install_id, placed=True, changed=True, version_changed=True, started=started)
    except AlreadyInstalled:
        return Outcome(UNKNOWN, "unknown", started=started)
    except (HTTPException, OSError) as exc:
        logger.warning("pack_ref_install_failed", item_id=ref.item_id, error=type(exc).__name__)
        return Outcome(UNKNOWN, "unknown", started=started)
