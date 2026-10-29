
from __future__ import annotations

import json
from pathlib import Path
from typing import AbstractSet, Dict, Mapping, Optional, Set, Tuple

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.summary_disk import write_atomic

logger = structlog.get_logger()

FORMAT = 1

Signature = Tuple[int, int]


class Verified:

    def __init__(self) -> None:
        self.signatures: Dict[str, Signature] = {}
        self._owner: Dict[str, Tuple[str, str]] = {}
        self._paths: Dict[str, Set[str]] = {}
        self._root: Optional[Path] = None
        self._dirty = False
        self._warned = False

    def _hold(self, path: str, signature: Signature, unit: str, point_id: str) -> None:
        previous = self._owner.get(path)
        if previous is not None and previous[0] != unit:
            self._paths[previous[0]].discard(path)
        self.signatures[path] = signature
        self._owner[path] = (unit, point_id)
        self._paths.setdefault(unit, set()).add(path)

    def _forget(self, path: str) -> None:
        unit, _point_id = self._owner.pop(path)
        del self.signatures[path]
        self._paths[unit].discard(path)
        self._dirty = True

    def add(self, unit: str, point_id: str, found: Mapping[str, Signature]) -> None:
        for path, signature in found.items():
            if self.signatures.get(path) != signature or self._owner.get(path) != (unit, point_id):
                self._hold(path, signature, unit, point_id)
                self._dirty = True

    def prune(self, live_paths: AbstractSet[str]) -> None:
        for path in [p for p in self.signatures if p not in live_paths]:
            self._forget(path)

    def revalidate_unit(self, unit: str, newest_point: Optional[str]) -> None:
        for path in [p for p in self._paths.get(unit, ()) if self._owner[p][1] != newest_point]:
            self._forget(path)

    def is_bound_to(self, root: Path) -> bool:
        return self._root == Path(root)

    def load(self, root: Path) -> int:
        root = Path(root)
        if self._root == root:
            return len(self.signatures)
        self.signatures.clear()
        self._owner.clear()
        self._paths.clear()
        self._root, self._dirty, self._warned = root, False, False
        for unit, (point_id, files) in _read(root / K.VERIFIED_FILE).items():
            for path, signature in files.items():
                self._hold(path, signature, unit, point_id)
        return len(self.signatures)

    def save(self, root: Path) -> bool:
        if not self._dirty or self._root != Path(root):
            return False
        files: Dict[str, Dict[str, Signature]] = {}
        point_of: Dict[str, str] = {}
        for path, signature in self.signatures.items():
            unit, point_id = self._owner[path]
            point_of[unit] = point_id
            files.setdefault(unit, {})[path] = signature
        units = {unit: (point_of[unit], found) for unit, found in files.items()}
        blob = json.dumps({"v": FORMAT, "units": units}, separators=(",", ":")).encode("utf-8")
        try:
            write_atomic(Path(root) / K.VERIFIED_FILE, blob)
        except OSError as exc:
            if not self._warned:
                logger.warning("vault_verified_write_failed", error=str(exc))
                self._warned = True
            return False
        self._dirty = self._warned = False
        return True


def _read(path: Path) -> Dict[str, Tuple[str, Dict[str, Signature]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("vault_verified_unreadable", error=str(exc))
        return {}
    if not isinstance(data, dict) or data.get("v") != FORMAT or not isinstance(data.get("units"), dict):
        logger.warning("vault_verified_unknown_format")
        return {}
    units: Dict[str, Tuple[str, Dict[str, Signature]]] = {}
    for unit, row in data["units"].items():
        try:
            point_id, files = row
            units[str(unit)] = (str(point_id), {str(p): (int(s[0]), int(s[1])) for p, s in files.items()})
        except (TypeError, ValueError, IndexError, AttributeError):
            logger.warning("vault_verified_row_skipped", unit=str(unit))
    return units
