
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from src.core.catalog.default_items import DEFAULT_ITEM_IDS
from src.core.catalog.index_cache import IndexSnapshot
from src.core.catalog.publisher_rename import find_installed_item
from src.core.catalog.revocation import KIND_KEY, KIND_VERSION, version_subject
from src.core.skills.ledger_types import InstalledItem
from src.core.skills.updates import update_available
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_api import (
    CatalogItemView,
    IndexStatus,
    InstalledItemView,
    InstalledRef,
    RefusalBody,
)


def index_status(snapshot: IndexSnapshot) -> IndexStatus:
    verified = snapshot.verified
    stamp = None if verified is None else verified.generated_at.isoformat()
    refusal = None
    if snapshot.refusal is not None:
        refusal = RefusalBody(
            code=snapshot.refusal.code, detail=snapshot.refusal.detail
        )
    return IndexStatus(
        serial=None if verified is None else verified.serial,
        generated_at=stamp,
        as_of=stamp,
        degraded=snapshot.degraded,
        stale=snapshot.stale,
        fetched_at=snapshot.fetched_at,
        refusal=refusal,
    )


def latest_version(item: CatalogItem) -> Optional[ItemVersion]:
    for version in item.versions:
        if version.v == item.latest:
            return version
    return None


def find_item(
    snapshot: IndexSnapshot, item_id: str
) -> Tuple[Optional[CatalogItem], bool]:
    verified = snapshot.verified
    if verified is None:
        return None, False
    for item in verified.items:
        if item.id == item_id:
            return item, False
    for item in verified.untrusted_items:
        if item.id == item_id:
            return item, True
    return None, False


def badge_for(installed: InstalledItem, snapshot: IndexSnapshot) -> bool:
    item, _untrusted = find_installed_item(snapshot, installed.item_id, installed.kind)
    if item is None:
        return False
    version = latest_version(item)
    if version is None:
        return False
    return update_available(installed, version)


def warning_reasons_for_version(version: Optional[ItemVersion]) -> Optional[List[str]]:
    if version is None:
        return None
    raw = getattr(version, "warning_reasons", None)
    if raw:
        return list(raw)
    review = getattr(version, "review", None)
    warnings = getattr(review, "warnings", None) if review is not None else None
    if not warnings:
        return None
    reasons: List[str] = []
    for w in warnings:
        kind = w.get("kind") if isinstance(w, dict) else getattr(w, "kind", None)
        detail = w.get("detail") if isinstance(w, dict) else getattr(w, "detail", None)
        if kind:
            reasons.append(f"{kind}: {detail}"[:120] if detail else str(kind))
    return reasons[:12] if reasons else None


def is_version_flagged(version: Optional[ItemVersion]) -> bool:
    if version is None:
        return False
    if getattr(version, "requires_warning_ack", False):
        return True
    rev = getattr(version, "review", None)
    return bool(rev is not None and getattr(rev, "verdict", None) == "flagged")


def revocation_lookup(
    snapshot: Optional[IndexSnapshot] = None,
    cache: Any = None,
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    if snapshot is None and cache is not None and hasattr(cache, "snapshot"):
        snapshot = cache.snapshot()
    revoked_keys: Dict[str, str] = {}
    revoked_versions: Dict[str, str] = {}
    refused_items: Dict[str, str] = {}
    verified = getattr(snapshot, "verified", None)
    if cache is not None and hasattr(cache, "_floor_and_revocations"):
        try:
            _floor, seen = cache._floor_and_revocations()
            for ref in seen:
                if ref.kind == KIND_KEY:
                    revoked_keys.setdefault(ref.subject.strip().upper(), ref.since)
                elif ref.kind == KIND_VERSION:
                    revoked_versions.setdefault(ref.subject, ref.since)
        except Exception:
            pass
    if verified is not None:
        for ref in getattr(verified, "revocations", ()) or ():
            if ref.kind == KIND_KEY:
                revoked_keys.setdefault(ref.subject.strip().upper(), ref.since)
            elif ref.kind == KIND_VERSION:
                revoked_versions.setdefault(ref.subject, ref.since)
        if cache is not None and hasattr(cache, "revoked_sets"):
            try:
                keys, versions = cache.revoked_sets(verified)
                for k in keys:
                    revoked_keys.setdefault(str(k).strip().upper(), "")
                for v in versions:
                    revoked_versions.setdefault(str(v), "")
            except Exception:
                pass
        for item_refusal in getattr(verified, "refused", ()) or ():
            if item_refusal.code in ("version_revoked", "key_untrusted"):
                refused_items.setdefault(item_refusal.item_id, item_refusal.code)
    return revoked_keys, revoked_versions, refused_items


def item_revocation_status(
    *,
    item_id: str,
    version: str,
    publisher_key_id: str,
    snapshot: Optional[IndexSnapshot] = None,
    cache: Any = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    revoked_keys, revoked_versions, refused_items = revocation_lookup(snapshot, cache)
    subj = version_subject(item_id, version) if item_id and version else ""
    if subj and subj in revoked_versions:
        since = revoked_versions[subj] or None
        return True, "version_revoked", since
    norm_key = publisher_key_id.strip().upper() if publisher_key_id else ""
    if norm_key and norm_key in revoked_keys:
        since = revoked_keys[norm_key] or None
        return True, "key_revoked", since
    if item_id in refused_items:
        return True, refused_items[item_id], None
    return False, None, None


def installed_ref(
    installed: InstalledItem, snapshot: IndexSnapshot, *, cache: Any = None
) -> InstalledRef:
    revoked, _reason, _since = item_revocation_status(
        item_id=installed.item_id,
        version=installed.version,
        publisher_key_id=installed.publisher_key_id,
        snapshot=snapshot,
        cache=cache,
    )
    return InstalledRef(
        install_id=installed.install_id,
        scope=installed.scope,
        project_path=installed.project_path,
        version=installed.version,
        update_available=badge_for(installed, snapshot),
        revoked=revoked,
    )


def installed_view(
    installed: InstalledItem, snapshot: IndexSnapshot, *, cache: Any = None
) -> InstalledItemView:
    revoked, revocation_reason, revoked_since = item_revocation_status(
        item_id=installed.item_id,
        version=installed.version,
        publisher_key_id=installed.publisher_key_id,
        snapshot=snapshot,
        cache=cache,
    )
    return InstalledItemView(
        install_id=installed.install_id,
        item_id=installed.item_id,
        kind=installed.kind,
        publisher=installed.publisher,
        name=installed.name,
        version=installed.version,
        digest=installed.digest,
        scope=installed.scope,
        project_path=installed.project_path,
        auto_update=installed.auto_update,
        source_index_url=installed.source_index_url,
        publisher_key_id=installed.publisher_key_id,
        revision=installed.revision,
        installed_at=installed.installed_at,
        updated_at=installed.updated_at,
        update_available=badge_for(installed, snapshot),
        consent_via=installed.consent_via,
        revoked=revoked,
        revocation_reason=revocation_reason,
        revoked_since=revoked_since,
    )


def first_published_at(item: CatalogItem) -> Optional[str]:
    stamps = [v.published_at for v in item.versions]
    if not stamps:
        return None
    try:
        return min(
            stamps,
            key=lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc),
        )
    except ValueError:
        return min(stamps)


def item_view(
    item: CatalogItem,
    *,
    installed: Optional[InstalledItem],
    snapshot: IndexSnapshot,
    untrusted: bool,
    cache: Any = None,
) -> CatalogItemView:
    raw: Dict[str, Any] = item.model_dump(mode="json")
    featured = () if snapshot.verified is None else snapshot.verified.featured
    latest_ver = latest_version(item)
    versions_out: List[Dict[str, Any]] = []
    raw_versions = raw.get("versions") or []
    for idx, ver_dict in enumerate(raw_versions):
        ver_obj = item.versions[idx] if idx < len(item.versions) else None
        ver_flagged = is_version_flagged(ver_obj)
        ver_reasons = warning_reasons_for_version(ver_obj)
        ver_revoked, ver_rev_reason, ver_rev_since = item_revocation_status(
            item_id=item.id,
            version=str(ver_dict.get("v", "")),
            publisher_key_id=str((ver_dict.get("sig") or {}).get("key_id", "")),
            snapshot=snapshot,
            cache=cache,
        )
        enriched = dict(ver_dict)
        enriched["flagged"] = ver_flagged
        enriched["requires_warning_ack"] = ver_flagged
        if ver_reasons is not None:
            enriched["warning_reasons"] = ver_reasons
        enriched["revoked"] = ver_revoked
        enriched["revocation_reason"] = ver_rev_reason
        enriched["revoked_since"] = ver_rev_since
        versions_out.append(enriched)

    latest_flagged = is_version_flagged(latest_ver)
    latest_reasons = warning_reasons_for_version(latest_ver)
    latest_review = (
        latest_ver.review.model_dump(mode="json")
        if latest_ver is not None and latest_ver.review is not None
        else None
    )
    latest_revoked, latest_rev_reason, latest_rev_since = item_revocation_status(
        item_id=item.id,
        version=latest_ver.v if latest_ver is not None else item.latest,
        publisher_key_id=latest_ver.sig.key_id if latest_ver is not None else "",
        snapshot=snapshot,
        cache=cache,
    )
    return CatalogItemView(
        featured_rank=featured.index(item.id) if item.id in featured else None,
        first_published_at=first_published_at(item),
        id=item.id,
        kind=item.kind,
        name=item.name,
        publisher=item.publisher,
        latest=item.latest,
        card=raw.get("card") or {},
        fm=raw.get("fm") or {},
        versions=versions_out,
        cost=raw.get("cost"),
        installed=(
            None if installed is None else installed_ref(installed, snapshot, cache=cache)
        ),
        untrusted=untrusted,
        installed_by_default=item.id in DEFAULT_ITEM_IDS,
        flagged=latest_flagged,
        requires_warning_ack=latest_flagged,
        warning_reasons=latest_reasons,
        review=latest_review,
        revoked=latest_revoked,
        revocation_reason=latest_rev_reason,
        revoked_since=latest_rev_since,
    )


def item_views(
    items: Iterable[CatalogItem],
    *,
    rows: Dict[str, InstalledItem],
    snapshot: IndexSnapshot,
    untrusted: bool,
    cache: Any = None,
) -> List[CatalogItemView]:
    views: List[CatalogItemView] = [
        item_view(
            item,
            installed=rows.get(item.id),
            snapshot=snapshot,
            untrusted=untrusted,
            cache=cache,
        )
        for item in items
    ]
    return views


def ledger_rows_by_item(rows: Iterable[InstalledItem]) -> Dict[str, InstalledItem]:
    by_item: Dict[str, InstalledItem] = {}
    for row in rows:
        existing = by_item.get(row.item_id)
        if existing is None or (
            existing.scope != "global" and row.scope == "global"
        ):
            by_item[row.item_id] = row
    return by_item


def host_of(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    return parsed.hostname or None
