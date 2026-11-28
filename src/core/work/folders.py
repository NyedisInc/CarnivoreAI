
from __future__ import annotations

from pathlib import Path
from typing import Tuple

OLD_ID = "huddle"
NEW_ID = "taskmanager"
CURRENT_ID = NEW_ID
PLUGINS_FOLDER = "cplugs"
FILES_DIR_NAME = "files"
IDS_NEWEST_FIRST: Tuple[str, ...] = (NEW_ID, OLD_ID)


def files_rel(plugin_id: str) -> str:
    return f"{PLUGINS_FOLDER}/{plugin_id}/{FILES_DIR_NAME}"


FILES_RELS: Tuple[str, ...] = tuple(files_rel(i) for i in IDS_NEWEST_FIRST)


def files_roots(state_dir: Path) -> Tuple[Path, ...]:
    return tuple(Path(state_dir).joinpath(*rel.split("/")) for rel in FILES_RELS)


def archive_rel(rel: str) -> str:
    new_prefix, old_prefix = files_rel(NEW_ID) + "/", files_rel(OLD_ID) + "/"
    return old_prefix + rel[len(new_prefix):] if rel.startswith(new_prefix) else rel
