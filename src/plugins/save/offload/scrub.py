
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

from src.plugins.save.engine import layout
from src.plugins.save.offload import alerts, chunk_check
from src.plugins.save.offload import constants as C
from src.plugins.save.offload.ledger import Ledger
from src.plugins.save.vault.manifest import ManifestError
from src.plugins.save.vault.store import Vault
from src.plugins.sdk.blob_codec import Throttle

logger = structlog.get_logger()

SCRUB_FILE = "vault-offload-scrub.json"


@dataclass
class ScrubResult:

    finished: bool
    units: int = 0
    bad: List[str] = field(default_factory=list)
    unreadable: List[str] = field(default_factory=list)


def _read(root: Path) -> Dict[str, Any]:
    try:
        data = json.loads((Path(root) / SCRUB_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("offload_scrub_memory_unreadable", error=str(exc)[:200])
        return {}
    return data if isinstance(data, dict) else {}


def _write(root: Path, data: Dict[str, Any]) -> None:
    try:
        layout.atomic_write_json(Path(root) / SCRUB_FILE, data)
    except OSError as exc:
        logger.error("offload_scrub_memory_unwritable", error=str(exc)[:200])


def last_done(root: Path) -> Optional[float]:
    value = _read(root).get("last_done_at")
    return float(value) if isinstance(value, (int, float)) else None


def due(root: Path, now: float) -> bool:
    memory = _read(root)
    if memory.get("pass"):
        return True
    last = memory.get("last_done_at")
    return not isinstance(last, (int, float)) or now - last >= C.SCRUB_DAYS * C.SECONDS_PER_DAY


def run_scrub(vault: Vault, ledger: Ledger, *, now: float, pace: Optional[Throttle] = None) -> ScrubResult:
    root = vault.root
    memory = _read(root)
    progress = memory.get("pass") if isinstance(memory.get("pass"), dict) else {"started_at": now, "done": [], "bad": [], "unreadable": []}
    done: Set[str] = set(progress.get("done") or [])
    bad: Set[str] = set(progress.get("bad") or [])
    unreadable: Set[str] = set(progress.get("unreadable") or [])
    pending = sorted(c for c in ledger.read() if c not in done)
    result = ScrubResult(finished=False)
    for conv in pending:
        entry = ledger.get(conv)
        if entry is None:
            done.add(conv)
            continue
        try:
            found = chunk_check.bad_chunks(vault.blobs, vault.manifests.read(entry.unit, entry.point_id), pace)
        except ManifestError as exc:
            logger.error("offload_scrub_manifest_unreadable", conversation_id=conv, error=str(exc)[:200])
            unreadable.add(conv)
            found = []
        except chunk_check.CheckIncomplete:
            break
        bad.update(found)
        done.add(conv)
        result.units += 1
        if pace is not None and pace.expired() and set(pending) - done:
            break
    complete = not (set(pending) - done)
    result.bad, result.unreadable, result.finished = sorted(bad), sorted(unreadable), complete
    if not complete:
        _write(root, {**memory, "pass": {"started_at": progress.get("started_at", now), "done": sorted(done), "bad": sorted(bad), "unreadable": sorted(unreadable)}})
        return result
    alerts.record(ledger.state_dir, alerts.SCRUB, blobs=bad, conversations=unreadable, now=now)
    _write(root, {"last_done_at": now})
    logger.info("offload_scrub_done", rows=len(done), bad=len(bad), unreadable=len(unreadable))
    return result
