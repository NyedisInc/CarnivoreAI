
from __future__ import annotations

import os
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, List, Tuple

from src.core.backup_health import vault_record
from src.core.inventory import plugin_stores, registry, registry_side
from src.core.inventory.claims import ClaimBook
from src.core.inventory.entry_claims import RENAME_STORE
from src.core.inventory.locations import PINNED_THEMES_FILE, UNREAD_STATE_FILE, Locations
from src.core.inventory.side_trace import JOURNAL

DATA_SUFFIXES: Tuple[str, ...] = (".db", ".json", ".jsonl")
MAIN_DB_FILE = "carnivore.db"
CLAIMED_STATE_FILES: Tuple[str, ...] = (UNREAD_STATE_FILE, PINNED_THEMES_FILE, f"{JOURNAL}/journal.json", RENAME_STORE,
                                        "swarm/settings/*.json", vault_record.HEALTH_FILE)
CLAIMED_STATE_DIRS: Tuple[str, ...] = ("time-machine", vault_record.DEFAULT_DIR_NAME, "deepsearch-backup-copies", "cplugs/huddle/files", "swarm/desk", "swarm/hooks")


def core_patterns(book: ClaimBook) -> List[str]:
    return [MAIN_DB_FILE, *registry_side.SIDE_DBS.values(), *CLAIMED_STATE_FILES, *CLAIMED_STATE_DIRS,
            *(excluded.store for excluded in book.stores)]


def accounted(rel: str, patterns: Iterable[str]) -> bool:
    parts = rel.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    return any(fnmatch(prefix, pattern) for prefix in prefixes for pattern in patterns)


def unaccounted(state_dir: Path, book: ClaimBook | None = None) -> List[str]:
    root = Path(state_dir)
    patterns = core_patterns(book or registry.book()) + plugin_stores.declared_state_rels(Locations(state_dir=root, config_path=root / "config.json"))
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if here == "." else here + "/"
        dirnames[:] = sorted(d for d in dirnames if not accounted(prefix + d, patterns))
        found += [prefix + f for f in sorted(filenames) if f.endswith(DATA_SUFFIXES) and not accounted(prefix + f, patterns)]
    return sorted(found)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 -m src.core.inventory.state_files <state folder>", file=sys.stderr)
        return 2
    root = Path(argv[1])
    if not root.is_dir():
        print(f"not a folder: {root}", file=sys.stderr)
        return 2
    missing = unaccounted(root)
    for rel in missing:
        print(rel)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
