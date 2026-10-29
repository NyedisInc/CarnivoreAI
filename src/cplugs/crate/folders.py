
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.cplugs.crate import constants as K
from src.cplugs.crate.env import CrateEnv
from src.cplugs.sdk.destination_rules import SYNCED_ROOTS


class FolderUnavailable(Exception):

    def __init__(self, detail: str, state: str = K.FOLDER_UNAVAILABLE) -> None:
        super().__init__(detail)
        self.code, self.detail, self.state = K.B_FOLDER, detail, state


@dataclass(frozen=True)
class FoundCrate:

    name: str
    size: int
    mtime: float
    sha256_sidecar: Optional[str]
    share: bool


def _refused_roots() -> List[str]:
    return [os.path.realpath(os.path.expanduser(p)) for p in SYNCED_ROOTS]


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def check(path: Path) -> Path:
    text = os.path.expanduser(str(path))
    if not os.path.isabs(text):
        raise FolderUnavailable(f"{path} is not an absolute folder path")
    parts = Path(text).parts
    if len(parts) >= 3 and parts[1] == K.VOLUMES_ROOT.strip("/"):
        volume = os.path.join(K.VOLUMES_ROOT, parts[2])
        if not os.path.ismount(volume):
            raise FolderUnavailable(f"{volume} is not mounted", K.FOLDER_UNMOUNTED)
    if not os.path.isdir(text):
        raise FolderUnavailable(f"{text} does not exist or is not a folder")
    real = os.path.realpath(text)
    if real != os.path.normpath(text):
        raise FolderUnavailable(f"{text} is a symlink or passes through one ({real}); name the real folder")
    for root in _refused_roots():
        if _inside(real, root):
            raise FolderUnavailable(f"{text} is inside {root}, a synced folder that can make a crate dataless or copy a half written file")
    if not os.access(real, os.W_OK):
        raise FolderUnavailable(f"{text} is not writable")
    return Path(real)


def resolve(env: CrateEnv, which: str) -> Path:
    if which == K.FOLDER_PRIMARY:
        chosen = str(env.setting("folder", "") or "").strip()
        if not chosen:
            default = Path(env.state) / K.DEFAULT_FOLDER
            default.mkdir(mode=K.FOLDER_MODE, exist_ok=True)
            return check(default)
        return check(Path(chosen))
    if which == K.FOLDER_SECOND:
        chosen = str(env.setting("secondFolder", "") or "").strip()
        if not chosen:
            raise FolderUnavailable("no second folder is set")
        return check(Path(chosen))
    raise ValueError(f"unknown folder {which!r}")


def share_folder(folder: Path) -> Path:
    sub = Path(folder) / K.SHARE_SUBFOLDER
    sub.mkdir(mode=K.FOLDER_MODE, exist_ok=True)
    if sub.is_symlink() or not sub.is_dir():
        raise FolderUnavailable(f"{sub} is not a real folder")
    return sub


def free_bytes(path: Path) -> int:
    return int(shutil.disk_usage(str(path)).free)


def _sidecar(path: Path) -> Optional[str]:
    try:
        first = Path(f"{path}.sha256").read_text(encoding="ascii").split()
    except (OSError, UnicodeDecodeError):
        return None
    return first[0].lower() if first and len(first[0]) == 64 else None


def scan(path: Path) -> List[FoundCrate]:
    out: List[FoundCrate] = []
    for folder, share in ((Path(path), False), (Path(path) / K.SHARE_SUBFOLDER, True)):
        try:
            entries = list(os.scandir(folder))
        except FileNotFoundError:
            continue
        for entry in entries:
            if not K.CRATE_NAME_RE.match(entry.name) or entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            st = entry.stat(follow_symlinks=False)
            out.append(FoundCrate(entry.name, st.st_size, st.st_mtime, _sidecar(Path(entry.path)), share))
    return sorted(out, key=lambda c: (c.share, c.name))
