
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Set, Tuple

import structlog

from src.core.catalog.trust_root import production_trust_root
from src.core.skill_watch.measure import MAX_FILES, TooLarge, measure_bounded
from src.core.skills.digest import digest_entries
from src.core.skills.kinds import KIND_THEME
from src.core.skills.ledger_types import SCOPE_GLOBAL, InstalledItem
from src.models.catalog_names import FIRST_PARTY_HANDLES, is_first_party_publisher
from src.models.themes import ThemeManifest

logger = structlog.get_logger(__name__)

_Key = Tuple[Tuple[Tuple[object, ...], ...], str, str]
_cache: Dict[str, Tuple[_Key, bool]] = {}
_MAX_CACHE = 256


def pinned_key_id() -> Optional[str]:
    key = production_trust_root().publisher_key
    return key.key_id.strip().upper() if key is not None else None


def _fingerprint(theme_dir: Path) -> Optional[Tuple[Tuple[object, ...], ...]]:
    entries = []
    try:
        for dirpath, dirnames, filenames in os.walk(theme_dir, followlinks=False):
            for name in dirnames + filenames:
                full = os.path.join(dirpath, name)
                st = os.lstat(full)
                entries.append((os.path.relpath(full, theme_dir), st.st_mode, st.st_size,
                                st.st_mtime_ns, st.st_ctime_ns, st.st_ino))
            if len(entries) > MAX_FILES:
                return None
    except OSError:
        return None
    return tuple(sorted(entries))


def first_party_installed(theme_dir: Path, manifest_id: str, row: InstalledItem,
                          key_id: Optional[str]) -> bool:
    if (key_id is None or row.kind != KIND_THEME or row.scope != SCOPE_GLOBAL
            or not is_first_party_publisher(row.publisher)
            or not (row.name == theme_dir.name == manifest_id)
            or row.item_id not in {f"{handle}/{row.name}" for handle in FIRST_PARTY_HANDLES}
            or row.publisher_key_id.strip().upper() != key_id
            or theme_dir.is_symlink() or not theme_dir.is_dir()):
        return False
    fingerprint = _fingerprint(theme_dir)
    if fingerprint is None:
        return False
    cache_key: _Key = (fingerprint, row.digest, key_id)
    cached = _cache.get(str(theme_dir))
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    try:
        entries, anomalies = measure_bounded(str(theme_dir))
        verdict = not anomalies and digest_entries(entries) == row.digest
    except (TooLarge, OSError) as exc:
        logger.warning("theme_first_party_measure_failed", theme=theme_dir.name,
                       error_type=type(exc).__name__)
        verdict = False
    if len(_cache) >= _MAX_CACHE:
        _cache.clear()
    _cache[str(theme_dir)] = (cache_key, verdict)
    return verdict


def trusted_ids(user_root: Optional[Path], user_manifests: Sequence[ThemeManifest],
                installs: Iterable[InstalledItem], key_id: Optional[str]) -> Set[str]:
    if user_root is None or key_id is None:
        return set()
    by_name = {i.name: i for i in installs if i.kind == KIND_THEME and i.scope == SCOPE_GLOBAL}
    return {
        m.id for m in user_manifests
        if m.effects and m.id in by_name
        and first_party_installed(user_root / m.id, m.id, by_name[m.id], key_id)
    }
