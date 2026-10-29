
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import structlog

logger = structlog.get_logger()

_Record = Tuple[str, str, str, int]

_lock = threading.Lock()
_records: Optional[List[_Record]] = None
_generation = 0
_guides: Dict[str, Tuple[int, Tuple[Tuple[int, str], ...]]] = {}
_memo: Dict[Tuple[str, int], Tuple[int, List[Dict[str, Any]]]] = {}


def register_guide(extends: str, rev: int, changelog: Sequence[Tuple[int, str]]) -> None:
    global _generation
    with _lock:
        _guides[extends] = (rev, tuple((entry[0], entry[1]) for entry in changelog))
        _generation += 1


def parse_extension(front: Mapping[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    raw_extends = front.get("extends")
    extends = raw_extends.strip().lower() if isinstance(raw_extends, str) and raw_extends.strip() else None
    raw_rev = front.get("guide_rev")
    if isinstance(raw_rev, str) and raw_rev.strip().isdigit():
        raw_rev = int(raw_rev.strip())
    rev = raw_rev if isinstance(raw_rev, int) and not isinstance(raw_rev, bool) and raw_rev >= 0 else None
    return extends, rev


def _record_of(root_key: str, name: str, extends: Optional[str], rev: Optional[int]) -> Optional[_Record]:
    if extends is None:
        return None
    return (root_key, name, extends, rev if rev is not None else 0)


def behind_rules(extends: Optional[str], guide_rev: Optional[int]) -> Optional[Dict[str, object]]:
    guide = _guides.get(extends or "")
    written = guide_rev or 0
    if guide is None or written >= guide[0]:
        return None
    return {"written_for": written, "current": guide[0],
            "changes": [{"rev": rev, "summary": text} for rev, text in guide[1] if rev > written]}


def refresh(locations: Iterable[Any], scanned_root_keys: Iterable[str]) -> None:
    global _records, _generation
    scanned = set(scanned_root_keys)
    fresh = [r for r in (_record_of(l.root_key, l.name, l.extends, l.guide_rev) for l in locations) if r is not None]
    with _lock:
        kept = [r for r in (_records or []) if r[0] not in scanned]
        _records = kept + fresh
        _generation += 1


def _seed(home: Path) -> List[_Record]:
    from src.config import settings
    from src.config.provider_accounts import MANAGED_ROOT
    from src.core.skill_manager.roots import configured_profiles, enumerate_roots, profile_groups
    from src.core.skill_manager.scan import scan_root
    from src.core.skill_manager.types import CLAUDE, SCOPE_PERSONAL

    out: List[_Record] = []
    for group in profile_groups(configured_profiles(home, Path(settings.auth_config_file).expanduser(), MANAGED_ROOT)):
        roots = enumerate_roots(group=group, project_path=None, home=home, codex_home=home / ".codex", plugin_scope=dict)
        for root in (r for r in roots if r.harness == CLAUDE and r.scope == SCOPE_PERSONAL):
            for skill in scan_root(root)[0]:
                record = _record_of(root.root_key, skill.name, skill.extends, skill.guide_rev)
                if record is not None:
                    out.append(record)
    return out


def stale_extensions(extends: str, current: Optional[int] = None, *, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    global _records
    with _lock:
        if current is None:
            guide = _guides.get(extends)
            if guide is None:
                return []
            current = guide[0]
        if _records is None:
            try:
                _records = _seed(home or Path.home())
            except OSError as exc:
                logger.warning("skill_extensions_seed_failed", error=type(exc).__name__)
                _records = []
        hit = _memo.get((extends, current))
        if hit is not None and hit[0] == _generation:
            return [dict(row) for row in hit[1]]
        lowest: Dict[str, int] = {}
        for _root, name, kind, rev in _records:
            if kind == extends:
                lowest[name] = min(rev, lowest.get(name, rev))
        rows = [{"name": n, "written_for": rev, "current": current} for n, rev in sorted(lowest.items()) if rev < current]
        _memo[(extends, current)] = (_generation, rows)
        return [dict(row) for row in rows]


def reset_for_tests() -> None:
    global _records, _generation
    with _lock:
        _records = None
        _memo.clear()
        _generation += 1
