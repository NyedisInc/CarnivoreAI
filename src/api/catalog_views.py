
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from src.core.catalog.index_cache import IndexSnapshot
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
    item, _untrusted = find_item(snapshot, installed.item_id)
    if item is None:
        return False
    version = latest_version(item)
    if version is None:
        return False
    return update_available(installed, version)


def installed_ref(
    installed: InstalledItem, snapshot: IndexSnapshot
) -> InstalledRef:
    return InstalledRef(
        install_id=installed.install_id,
        scope=installed.scope,
        project_path=installed.project_path,
        version=installed.version,
        update_available=badge_for(installed, snapshot),
    )


def installed_view(
    installed: InstalledItem, snapshot: IndexSnapshot
) -> InstalledItemView:
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
) -> CatalogItemView:
    raw: Dict[str, Any] = item.model_dump(mode="json")
    featured = () if snapshot.verified is None else snapshot.verified.featured
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
        versions=raw.get("versions") or [],
        cost=raw.get("cost"),
        installed=(
            None if installed is None else installed_ref(installed, snapshot)
        ),
        untrusted=untrusted,
    )


def item_views(
    items: Iterable[CatalogItem],
    *,
    rows: Dict[str, InstalledItem],
    snapshot: IndexSnapshot,
    untrusted: bool,
) -> List[CatalogItemView]:
    views: List[CatalogItemView] = [
        item_view(
            item,
            installed=rows.get(item.id),
            snapshot=snapshot,
            untrusted=untrusted,
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
