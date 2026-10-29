
from __future__ import annotations

from pathlib import Path

from src.core.work.importer import ready
from src.core.work.importer.errors import WorkImportDeferred
from src.core.work.storage import storage_for


def prepare(state_dir: Path, core_healthy: bool) -> bool:
    storage = storage_for(Path(state_dir))
    if not core_healthy:
        ready.hold(storage.db_path, "carnivore.db is degraded, so the work store is not opened this boot")
        return False
    try:
        storage.ensure_ready()
    except WorkImportDeferred:
        return False
    return True
