
from __future__ import annotations

import json
from pathlib import Path
from typing import AbstractSet, Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K

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
            intentional: AbstractSet[str] = frozenset()) -> Optional[Dict[str, Any]]:
    memory = _read(root)
    events = _recent(memory, now - K.MASS_GONE_WINDOW_SECONDS)
    if memory is not None:
        before = set(memory.get("gone") or [])
        events += [[now, unit, folder] for unit, folder in sorted(gone_now.items()) if unit not in before and unit not in intentional]
    units = {row[1] for row in events}
    level, step, reported = _step_of(memory, len(units))
    try:
        layout.atomic_write_json(Path(root) / K.GONE_FILE, {"gone": sorted(gone_now), "events": events, "level": level, "step": step})
    except OSError as exc:
        logger.error("vault_gone_memory_unwritable", error=str(exc))
    if not reported:
        return None
    folders = sorted({row[2] for row in events if row[2]})
    report = {"count": len(units), "samples": folders[: K.MASS_GONE_SAMPLES], "at": now, "step": step}
    logger.warning("vault_mass_gone", count=report["count"], step=step, samples=report["samples"],
                   note="many originals vanished together; the vault keeps every copy and nothing is pruned")
    return report
