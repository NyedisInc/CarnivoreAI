
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import structlog

from src.api.skills_manager_routes import _inventory_now, _profiles
from src.core.skill_manager import card_art

logger = structlog.get_logger()

MAX_LOCATIONS = card_art.MAX_LOCATIONS
_lock = threading.Lock()
_state: Dict[str, Any] = {"state": "idle", "total": 0, "done": 0, "generated": 0, "failed": 0, "skipped": 0}


def status() -> Dict[str, Any]:
    with _lock:
        return dict(_state)


def _run(locations: List[Dict[str, Any]]) -> None:

    def one(loc: Dict[str, Any]) -> None:
        key = card_art.art_id(loc["harness"], loc["name"], loc["location_id"])
        try:
            result = card_art.generate(key, loc["name"], loc.get("description") or "", regenerate=True)["status"]
        except Exception as exc:
            logger.warning("skill_card_art_bulk_item_failed", error=type(exc).__name__)
            result = "failed"
        with _lock:
            _state["done"] += 1
            bucket = result if result in ("generated", "failed") else "skipped"
            _state[bucket] += 1

    try:
        with ThreadPoolExecutor(max_workers=card_art.WORKERS, thread_name_prefix="skill-art-bulk") as pool:
            list(pool.map(one, locations))
        final = "done"
    except Exception as exc:
        logger.warning("skill_card_art_bulk_failed", error=type(exc).__name__)
        final = "error"
    with _lock:
        _state["state"] = final


async def start(app: Any) -> Dict[str, Any]:
    with _lock:
        if _state["state"] == "running":
            raise RuntimeError("a bulk card art job is already running")
        _state.update(state="running", total=0, done=0, generated=0, failed=0, skipped=0)
    try:
        profiles = await asyncio.to_thread(_profiles, Path.home())
        snapshot = await app.state.services.catalog.index_cache.get()
        inventory = await asyncio.to_thread(_inventory_now, SimpleNamespace(app=app), profiles, None, None, snapshot)
        locations = [loc for group in inventory["skills"] for loc in group["locations"] if not loc.get("shadowed_by")][:MAX_LOCATIONS]
    except Exception:
        with _lock:
            _state["state"] = "error"
        raise
    with _lock:
        _state["total"] = len(locations)
    threading.Thread(target=_run, args=(locations,), name="skill-art-bulk-job", daemon=True).start()
    return status()
