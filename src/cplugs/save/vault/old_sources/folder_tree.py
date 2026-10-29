
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterator, Optional

from src.cplugs.save.vault.old_sources import model, names

NOT_TRANSCRIPTS = frozenset({"archive-metadata"})
_LAYER = "message-layer-"


def _opener(path: Path):
    def open_bytes():
        with open(path, "rb") as handle:
            while block := handle.read(model.READ_BLOCK):
                yield block
    return open_bytes


def _relative(root: Path, path: Path) -> str:
    parts = path.relative_to(root).parts
    for i, part in enumerate(parts):
        if part.startswith(_LAYER):
            return "/".join(parts[i + 1:])
    return "/".join(parts)


def iter_copies(root: Path, intake: model.Intake, name: str, recorded: Optional[Dict[str, str]] = None) -> Iterator[model.Copy]:
    root = Path(root)
    if not root.is_dir():
        raise model.SourceError(f"{root} is not a folder")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in NOT_TRANSCRIPTS)
        for filename in sorted(filenames):
            if not filename.endswith(".jsonl") and not filename.startswith("._"):
                continue
            path = Path(dirpath) / filename
            locator = str(path)
            if path.is_symlink() or names.is_appledouble(filename):
                intake.skipped.append(model.Refusal(name, locator, "appledouble" if filename.startswith("._") else "symlink"))
                continue
            ident = names.identify(_relative(root, path))
            if ident is None:
                intake.skipped.append(model.Refusal(name, locator, "not a transcript path"))
                continue
            copy = model.checked(intake, name, locator, ident, _opener(path), path.stat().st_mtime, want_sha=(recorded or {}).get(locator))
            if copy is not None:
                yield copy
