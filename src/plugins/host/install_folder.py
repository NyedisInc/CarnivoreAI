
from __future__ import annotations

from pathlib import Path

from src.plugins.host import sideload


def deciding_folder(state_dir: Path, item_id: str) -> Path:
    name = item_id.partition("/")[2]
    if sideload.is_local(item_id):
        source = sideload.items(state_dir).get(name, {}).get("source")
        if isinstance(source, str) and source:
            return Path(source)
    return sideload.code_root_of(state_dir, name)
