
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Sequence

SYNCED_ROOTS: Sequence[str] = ("~/Library/Mobile Documents", "~/Library/CloudStorage", "~/Dropbox")


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def refusals(value: str) -> List[str]:
    text = os.path.expanduser(value.strip())
    if not text:
        return []
    if not os.path.isabs(text):
        return [f"{value} is not an absolute folder path"]
    out: List[str] = []
    real = os.path.realpath(text)
    # does not exist yet
    # does not exist yet
    probe = os.path.normpath(text)
    while not os.path.lexists(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    if os.path.lexists(probe) and os.path.realpath(probe) != probe:
        out.append(f"{text} is a symlink or passes through one ({real}); name the real folder")
    for root in SYNCED_ROOTS:
        base = os.path.realpath(os.path.expanduser(root))
        if _inside(real, base) or _inside(os.path.normpath(text), os.path.normpath(os.path.expanduser(root))):
            out.append(f"{text} is inside {root}, a synced folder that can make a backup dataless or copy a half written file")
            break
    return out


def _device(path: Path) -> Optional[int]:
    current = path
    while True:
        try:
            return os.stat(current).st_dev
        except OSError:
            if current.parent == current:
                return None
            current = current.parent


def same_disk_warning(destination: str, protected: Path) -> Optional[str]:
    text = os.path.expanduser(destination.strip())
    if not text:
        return None
    here, there = _device(Path(text)), _device(protected)
    if here is None or there is None or here != there:
        return None
    return f"{text} is on the same disk as {protected}, so these copies are lost together if the disk fails; choose another disk"
