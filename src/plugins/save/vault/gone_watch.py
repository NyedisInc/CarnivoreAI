
from __future__ import annotations

import json
from pathlib import Path
from typing import AbstractSet, Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.plugins.save.engine import layout
from src.plugins.save.vault import constants as K

logger = structlog.get_logger()


def _read(root: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads((Path(root) / K.GONE_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("vault_gone_memory_unreadable", error=str(exc))
        return None
    return data if isinstance(data, dict) else None


def frozen(root: Path) -> Optional[Dict[str, Any]]:
    path = Path(root) / K.FREEZE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.error("vault_freeze_unreadable", error=str(exc), error_type=type(exc).__name__, path=str(path))
        return {"unreadable": True}
    return data if isinstance(data, dict) else {"unreadable": True}


def freeze(root: Path, report: Mapping[str, Any]) -> bool:
    try:
        layout.atomic_write_json(Path(root) / K.FREEZE_FILE, dict(report))
    except OSError as exc:
        logger.error("vault_freeze_unwritable", error=str(exc), error_type=type(exc).__name__, path=str(root))
        return False
    logger.error("vault_frozen", count=report.get("count"), step=report.get("step"),
                 note="pruning, retention and supersede are frozen until the owner clears it")
    return True


def clear_freeze(root: Path) -> bool:
    try:
        (Path(root) / K.FREEZE_FILE).unlink()
    except FileNotFoundError:
        return False
    logger.warning("vault_freeze_cleared", note="the owner cleared the mass-gone freeze; pruning resumes")
    return True


def carry_freeze(old_root: Path, new_root: Path) -> bool:
    standing = frozen(old_root)
    if standing is None or frozen(new_root) is not None:
        return False
    try:
        layout.atomic_write_json(Path(new_root) / K.FREEZE_FILE, standing)
    except OSError as exc:
        logger.error("vault_freeze_not_carried", error=str(exc), error_type=type(exc).__name__, old=str(old_root), new=str(new_root))
        return False
    logger.warning("vault_freeze_carried", old=str(old_root), new=str(new_root))
    return True


def _recent(memory: Optional[Mapping[str, Any]], cutoff: float) -> List[List[Any]]:
    rows = (memory or {}).get("events") or []
    return [row for row in rows if isinstance(row, list) and len(row) == 3 and isinstance(row[0], (int, float)) and row[0] >= cutoff]


def _step_of(memory: Optional[Mapping[str, Any]], count: int) -> Tuple[int, int, bool]:
    if count < K.MASS_GONE_THRESHOLD:
        return 0, 0, False
    level, step = int((memory or {}).get("level") or 0), int((memory or {}).get("step") or 0)
    if level == 0:
        return count, 0, True
    if count >= level + K.MASS_GONE_THRESHOLD:
        return count, step + 1, True
    return level, step, True


def observe(root: Path, gone_now: Mapping[str, str], now: float, *,
            intentional: AbstractSet[str] = frozenset(), seen_on_disk: Optional[AbstractSet[str]] = None) -> Optional[Dict[str, Any]]:
    memory = _read(root)
    events = _recent(memory, now - K.MASS_GONE_WINDOW_SECONDS)
    if memory is not None:
        before = set(memory.get("gone") or [])
        events += [[now, unit, folder] for unit, folder in sorted(gone_now.items())
                   if unit not in before and unit not in intentional and (seen_on_disk is None or unit in seen_on_disk)]
    units = {row[1] for row in events}
    level, step, reported = _step_of(memory, len(units))
    fresh = reported and (int((memory or {}).get("level") or 0) == 0 or step > int((memory or {}).get("step") or 0))
    report = None
    if reported:
        folders = sorted({row[2] for row in events if row[2]})
        report = {"count": len(units), "samples": folders[: K.MASS_GONE_SAMPLES], "at": now, "step": step}
        if fresh and not freeze(root, report):
            level, step = 0, 0
    try:
        layout.atomic_write_json(Path(root) / K.GONE_FILE, {"gone": sorted(gone_now), "events": events, "level": level, "step": step})
    except OSError as exc:
        logger.error("vault_gone_memory_unwritable", error=str(exc), error_type=type(exc).__name__, path=str(root))
    if report is not None:
        logger.warning("vault_mass_gone", count=report["count"], step=report["step"], samples=report["samples"],
                       note="many originals vanished together; the vault is frozen until the owner clears it")
    return report
