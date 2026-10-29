
from __future__ import annotations

from pathlib import Path
from typing import List

from src.core.skills.digest import MODE_REGULAR, DigestEntry, digest_entries, hash_file

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "extensions"
SCHEMA_SET_DIGEST = "201fd58f8299b30df70ee17d891e519180cfa3e9cba76f4b6d0e4f7b69f052be"


def schema_set_digest(root: Path = SCHEMA_DIR) -> str:
    entries: List[DigestEntry] = []
    for path in root.rglob("*.json"):
        if path.is_file() and not path.is_symlink():
            entries.append(DigestEntry(relpath=path.relative_to(root).as_posix(), mode=MODE_REGULAR, sha256=hash_file(path)[0]))
    return digest_entries(sorted(entries, key=lambda e: e.relpath.encode("utf-8")))


if __name__ == "__main__":
    print(schema_set_digest())
