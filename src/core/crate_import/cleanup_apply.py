
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

import structlog

from src.core.crate_import import files_apply, undo
from src.core.crate_import.cleanup_guard import KEEP_DAYS, KEY, period_days, read_settings, settings_path
from src.core.crate_import.hooks import ApplyHooks
from src.core.crate_import.model import ImportFailed

logger = structlog.get_logger()


def _free_backup(path: Path) -> Path:
    bak = path.with_name(path.name + ".bak")
    n = 1
    while os.path.lexists(bak):
        n += 1
        bak = path.with_name(f"{path.name}.bak{n}")
    return bak


def apply(home: Path, hooks: ApplyHooks, placed: files_apply.PlacedFiles) -> Dict[str, Any]:
    path = settings_path(home)
    settings, refused = read_settings(home)
    if refused is not None:
        raise ImportFailed(files_apply.E_FILE_CHANGED, f"{path.name}: is no longer a settings object", rolled_back=False)
    was = period_days(settings)
    if was >= KEEP_DAYS:
        return {"was": was, "set_to": was, "backup": None}
    new = {**settings, KEY: KEEP_DAYS}
    data = (json.dumps(new, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    existed = os.path.lexists(path)
    bak = _free_backup(path) if existed else None
    files_apply.record_undo(hooks, placed, undo.settings_entry(path, bak, hashlib.sha256(data).hexdigest(), existed))
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        if bak is not None:
            with open(path, "rb") as src, open(bak, "xb") as out:
                out.write(src.read())
                out.flush()
                os.fsync(out.fileno())
        with open(temp, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    except OSError as exc:
        raise ImportFailed(files_apply.E_IO, f"{path.name}: {type(exc).__name__}", rolled_back=False) from exc
    finally:
        temp.unlink(missing_ok=True)
    logger.info("crate_import_cleanup_period_set", was=was, set_to=KEEP_DAYS, backup=str(bak) if bak else None)
    return {"was": was, "set_to": KEEP_DAYS, "backup": str(bak) if bak else None}
