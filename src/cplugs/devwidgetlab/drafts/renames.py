
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.cplugs.sdk import app_info

logger = structlog.get_logger()

ID_FIELDS = ("widget", "target")
BACKUP_NAME = "draft.json.bak-before-rename"


def current_record(record: Dict[str, Any]) -> Dict[str, Any]:
    swapped = {name: app_info.renamed_widget_key(record[name]) for name in ID_FIELDS if isinstance(record.get(name), str)}
    changed = {name: key for name, key in swapped.items() if key != record[name]}
    return {**record, **changed} if changed else record


def migrate_records(storage_path: Path) -> List[str]:
    root = Path(storage_path) / "drafts"
    done: List[str] = []
    for folder in (sorted(root.iterdir()) if root.is_dir() else []):
        record_path = folder / "draft.json"
        if folder.name.startswith(".") or not record_path.is_file():
            continue
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("not an object")
            updated = current_record(record)
            if updated is record:
                continue
            backup = folder / BACKUP_NAME
            if not backup.exists():
                shutil.copy2(record_path, backup)
            tmp = record_path.with_name(record_path.name + ".tmp")
            tmp.write_text(json.dumps(updated, indent=2, sort_keys=False) + "\n", encoding="utf-8")
            os.replace(tmp, record_path)
        except (OSError, ValueError) as exc:
            logger.warning("widget_lab_draft_rename_skipped", slug=folder.name, error_type=type(exc).__name__)
            continue
        done.append(folder.name)
        logger.info("widget_lab_draft_ids_renamed", slug=folder.name, widget=updated.get("widget"))
    return done
