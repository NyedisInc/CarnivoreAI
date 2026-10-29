
from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from src.cplugs.reviewboard import checkout
from src.cplugs.reviewboard.errors import NoRoot
from src.cplugs.reviewboard.scan import MARKER
from src.cplugs.sdk import task_folders
from src.cplugs.sdk.data_decl import default_store_root, is_default_value

SETTING = "boardsRoot"
DEFAULT_FOLDER = "review-boards"
APP_COPY_NAMES = frozenset({"Carnivore Menubar", "cloude-code-menubar"})

REASONS = {
    "unset": "set the boards folder first (the setting boardsRoot)",
    "not_absolute": "the boards folder must be an absolute path",
    "missing": "the boards folder does not exist",
    "not_a_folder": "the boards folder is not a folder",
    "symlink": "the boards folder, or a folder above it, is a symlink; name the real folder",
    "no_marker": f"the boards folder has no {MARKER} marker file, so the board will not write there",
    "no_checkout": "the boards folder is not inside a git checkout (no .git at or above it)",
    "default_unavailable": "the default boards folder could not be made; set the boards folder to a folder you own",
    "forbidden": "the boards folder is inside the plugin's state folder, the derived app copy or an app bundle",
}


@dataclass(frozen=True)
class RootStatus:

    ok: bool
    path: Optional[str] = None
    reason: Optional[str] = None
    message: str = ""
    warnings: List[checkout.CheckoutWarning] = field(default_factory=list)
    is_default: bool = False


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _in_checkout(path: Path) -> bool:
    return any((folder / ".git").exists() for folder in (path, *path.parents))


def _forbidden(path: Path, state_dir: Optional[Path]) -> bool:
    if state_dir is not None and _inside(path, state_dir):
        return True
    return any(part in APP_COPY_NAMES or part.endswith(".app") for part in path.parts)


def check_root(value: Any, state_dir: Optional[Path] = None) -> Path:
    def refuse(reason: str) -> NoRoot:
        return NoRoot(reason, REASONS[reason])

    if not isinstance(value, str) or not value.strip():
        raise refuse("unset")
    text = value.strip()
    if not os.path.isabs(text):
        raise refuse("not_absolute")
    path = Path(os.path.normpath(text))
    try:
        st = path.lstat()
    except OSError as exc:
        raise refuse("missing") from exc
    if os.path.realpath(path) != str(path):
        raise refuse("symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise refuse("not_a_folder")
    if _forbidden(path, state_dir.resolve() if state_dir is not None else None):
        raise refuse("forbidden")
    try:
        marker = (path / MARKER).lstat()
    except OSError as exc:
        raise refuse("no_marker") from exc
    if not stat.S_ISREG(marker.st_mode):
        raise refuse("no_marker")
    if not _in_checkout(path):
        raise refuse("no_checkout")
    return path


def default_root(state_dir: Path) -> Path:
    return default_store_root(state_dir, DEFAULT_FOLDER)


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def resolve_root(value: Any, state_dir: Path) -> Tuple[Path, bool]:
    if not _blank(value) and not is_default_value(state_dir, DEFAULT_FOLDER, value):
        return check_root(value, state_dir), False
    path = default_root(state_dir)
    try:
        task_folders.ensure_root(path)
        marker = (path / MARKER).lstat()
    except OSError as exc:
        raise NoRoot("default_unavailable", REASONS["default_unavailable"]) from exc
    if not stat.S_ISREG(marker.st_mode):
        raise NoRoot("default_unavailable", REASONS["default_unavailable"])
    return path, True


def root_status(value: Any, state_dir: Path) -> RootStatus:
    try:
        path, is_default = resolve_root(value, state_dir)
        return RootStatus(ok=True, path=str(path), warnings=[] if is_default else checkout.warnings_for(path), is_default=is_default)
    except NoRoot as exc:
        return RootStatus(ok=False, reason=exc.reason, message=str(exc))


def state_dir_of(storage_folder: Path) -> Path:
    return Path(storage_folder).parent.parent
