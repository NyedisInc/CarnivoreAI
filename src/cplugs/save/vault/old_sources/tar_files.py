
from __future__ import annotations

import os
import tarfile
from pathlib import Path, PurePosixPath
from typing import Iterator

from src.cplugs.save.vault.old_sources import model, names


def _span(tar_path: Path, offset: int, size: int) -> Iterator[bytes]:
    with open(tar_path, "rb") as handle:
        handle.seek(offset)
        left = size
        while left > 0:
            block = handle.read(min(model.READ_BLOCK, left))
            if not block:
                raise OSError(f"{tar_path} ends inside a member")
            left -= len(block)
            yield block


def iter_copies(root: Path, intake: model.Intake, name: str = "swarmtar") -> Iterator[model.Copy]:
    root = Path(root)
    if not root.is_dir():
        raise model.SourceError(f"{root} is not a folder")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for filename in sorted(f for f in filenames if f.endswith(".tar")):
            tar_path = Path(dirpath) / filename
            try:
                with tarfile.open(tar_path, "r:") as tar:
                    members = [(m.name, float(m.mtime), m.offset_data, m.size) for m in tar if m.isfile() and m.name.endswith(".jsonl")]
            except (OSError, tarfile.TarError) as exc:
                intake.refused.append(model.Refusal(name, str(tar_path), f"unreadable: {type(exc).__name__}"))
                continue
            for member_name, mtime, offset, size in members:
                locator = f"tar:{tar_path}::{member_name}"
                pure = PurePosixPath(member_name)
                if names.is_appledouble(member_name):
                    intake.skipped.append(model.Refusal(name, locator, "appledouble"))
                    continue
                ident = None if pure.is_absolute() or ".." in pure.parts else names.identify(member_name)
                if ident is None:
                    intake.skipped.append(model.Refusal(name, locator, "not a transcript path"))
                    continue
                copy = model.checked(intake, name, locator, ident, lambda t=tar_path, o=offset, z=size: _span(t, o, z), mtime)
                if copy is not None:
                    yield copy
