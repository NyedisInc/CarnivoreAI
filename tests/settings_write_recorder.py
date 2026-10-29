
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple

__all__ = ["install", "remove", "write_was_recorded", "canary_verdict"]

_watched: Dict[Path, bool] = {}

_originals: list = []


def install(path: Path) -> None:
    resolved = path.resolve()
    _watched[resolved] = False
    if not _originals:
        _install_patches()


def _install_patches() -> None:

    def _os_wrapper(original):
        def wrapper(src, dst, *args, **kwargs):
            result = original(src, dst, *args, **kwargs)
            _note_if_watched(dst)
            return result

        wrapper.__name__ = getattr(original, "__name__", "wrapped")
        return wrapper

    for attr in ("replace", "rename"):
        original = getattr(os, attr)
        _originals.append((os, attr, original))
        setattr(os, attr, _os_wrapper(original))

    def _os_single_path_wrapper(original):
        def wrapper(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            _note_if_watched(path)
            return result

        wrapper.__name__ = getattr(original, "__name__", "wrapped")
        return wrapper

    for attr in ("remove", "unlink"):
        original = getattr(os, attr)
        _originals.append((os, attr, original))
        setattr(os, attr, _os_single_path_wrapper(original))

    def _path_write_wrapper(original):
        def wrapper(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            _note_if_watched(self)
            return result

        wrapper.__name__ = getattr(original, "__name__", "wrapped")
        return wrapper

    for attr in ("write_text", "write_bytes", "unlink"):
        original = getattr(Path, attr)
        _originals.append((Path, attr, original))
        setattr(Path, attr, _path_write_wrapper(original))


def _note_if_watched(candidate) -> None:
    if not _watched:
        return
    try:
        raw = os.fspath(candidate)
    except TypeError:
        return
    basename = os.path.basename(raw)
    if not any(basename == watched.name for watched in _watched):
        return
    try:
        resolved = Path(raw).resolve()
    except OSError:
        return
    if resolved in _watched:
        _watched[resolved] = True


def remove(path: Path) -> None:
    _watched.pop(path.resolve(), None)
    if not _watched and _originals:
        for holder, attr, original in _originals:
            setattr(holder, attr, original)
        _originals.clear()


def write_was_recorded(path: Path) -> bool:
    return _watched.get(path.resolve(), False)


def canary_verdict(
    before: Tuple[str, str], after: Tuple[str, str], write_seen: bool
) -> Tuple[str, str]:
    if before[0] == "unreadable":
        return (
            "fail",
            f"could not read the settings file before the session ({before[1]}). "
            "The canary cannot vouch for the file, which is a failure, not a pass.",
        )
    if after[0] == "unreadable":
        return (
            "fail",
            f"could not read the settings file after the session ({after[1]}). "
            "The canary cannot vouch for the file, which is a failure, not a pass.",
        )
    if before == after:
        return ("ok", "")
    if write_seen:
        return (
            "fail",
            f"THE TEST SUITE MODIFIED the settings file. Before={before} After={after}. "
            "This process's own os.replace/os.rename/write_text/write_bytes reached it - "
            "find the writer and give it an explicit temp destination; see "
            "src/core/test_write_guard.py.",
        )
    return (
        "warn",
        f"the settings file changed during this run (Before={before} After={after}) but "
        "no write from this test process was recorded, so this is attributed to an "
        "unrelated process (for example a live Claude Code session) and does not fail "
        "the suite.",
    )
