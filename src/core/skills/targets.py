
from __future__ import annotations

import os
import shutil
from functools import partial
from pathlib import Path

import structlog

from src.core.skills.stage import DIR_MODE, EXEC_FILE_MODE, FILE_MODE
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()


class SymlinkInTree(ValueError):
    pass


class TrashFolderIsLink(OSError):
    pass


def _refuse_symlinks(directory: str, names: list[str]) -> set[str]:
    for name in names:
        entry = Path(directory) / name
        if entry.is_symlink():
            raise SymlinkInTree(
                f"refusing to copy {entry}: it is a symlink, and an "
                "installed skill is a real copy of real files"
            )
    return set()


def _copy_file(
    source: str | os.PathLike,
    destination: str | os.PathLike,
    *,
    root: Path,
    exec_paths: frozenset[str],
) -> None:
    destination_path = Path(destination)
    assert_test_write_allowed(destination_path)
    shutil.copyfile(source, destination_path)
    relpath = os.path.relpath(str(source), str(root))
    mode = EXEC_FILE_MODE if relpath in exec_paths else FILE_MODE
    os.chmod(destination_path, mode)


def copy_tree(
    src: Path,
    dst: Path,
    *,
    exec_paths: frozenset[str] = frozenset(),
    skip_names: frozenset[str] = frozenset(),
) -> None:
    """Copy a staged folder into a destination that must not yet exist.

    Description: a REAL copy. Every directory lands at 0o700 and every
      file at 0o644, neither taken from the source, EXCEPT the files named
      in ``exec_paths``, which land at 0o755. ``symlinks=False`` would
      make ``copytree`` follow a link; it never gets the chance, because
      :func:`_refuse_symlinks` raises on the first one. Both are passed
      because the filter is the guard and the flag is the backstop. On ANY
      failure the partial destination is removed whole, so a refusal never
      leaves a half-written folder a later pass could mistake for a
      complete install.
    Inputs: src (Path) - the verified staging directory. dst (Path) - the
      install directory, which MUST NOT EXIST. exec_paths
      (frozenset[str]) - keyword only, POSIX paths relative to ``src``
      that are executable content the user consented to. DEFAULTS TO
      EMPTY, so a caller makes a file executable by naming it and never
      by forgetting to say otherwise. skip_names (frozenset[str]) - keyword
      only, entry names left out of the copy when they sit directly in
      ``src`` (the catalog install's sidecar); a symlink among them is
      still refused first.
    Output: None.
    Raises:
        FileExistsError: dst already exists. Merging into it would mean
            merging with whatever a previous failed attempt left behind.
        SymlinkInTree: the source tree contains a symlink.
        OutsideTempWriteError: a test run aimed this at a real path.
    Example: copy_tree(staging / "sme", claude_skills / "sme")
    """
    assert_test_write_allowed(dst)

    def ignore(directory: str, names: list[str]) -> set[str]:
        _refuse_symlinks(directory, names)
        return {n for n in names if n in skip_names} if directory == str(src) else set()

    try:
        shutil.copytree(
            src,
            dst,
            symlinks=False,
            ignore=ignore,
            copy_function=partial(_copy_file, root=src, exec_paths=exec_paths),
            dirs_exist_ok=False,
        )
        os.chmod(dst, DIR_MODE)
        for parent, dir_names, _file_names in os.walk(dst):
            for dir_name in dir_names:
                os.chmod(Path(parent) / dir_name, DIR_MODE)
    except BaseException:
        try:
            remove_tree(dst)
        except OSError as cleanup_error:
            logger.warning(
                "skill_copy_tree_cleanup_failed",
                destination=str(dst),
                error=str(cleanup_error),
            )
        raise
    logger.info("skill_copy_tree_written", source=str(src), destination=str(dst))


TRASH_GITIGNORE = "*\n"


def ensure_trash_gitignore(trash_root: Path) -> None:
    path = trash_root / ".gitignore"
    assert_test_write_allowed(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(TRASH_GITIGNORE)


def move_to_trash(target: Path, trash_root: Path, stamp: str) -> Path:
    """Rename an existing folder out of a harness root into the trash.

    Description: ``os.replace`` into ``<trash_root>/<name>-<stamp>``. The
      trash is created 0o700 if it is absent. The destination must NOT
      already exist: two displacements sharing a stamp would otherwise
      have the second silently overwrite the first, and the thing being
      overwritten is the user's own folder.
    Inputs: target (Path) - the folder being displaced. trash_root (Path) -
      from ``InstallRoots.trash_dir``. stamp (str) - a caller-supplied
      uniquifier with no path separator in it.
    Output: Path - where the folder now lives, so the caller can name it.
    Raises:
        ValueError: the stamp contains a path separator or a NUL, either
            of which would aim the rename outside the trash root.
        FileExistsError: the trash destination is already occupied.
        TrashFolderIsLink: ``trash_root`` is a symlink (checked before any mkdir or chmod).
        OutsideTempWriteError: a test run aimed this at a real path.
    Example: move_to_trash(skills / "sme", trash, "20260915T101500")
    """
    if "/" in stamp or "\\" in stamp or "\0" in stamp or not stamp.strip():
        raise ValueError(
            f"unusable trash stamp {stamp!r}: it is joined to a directory "
            "name, so a separator in it would aim the rename elsewhere"
        )

    if os.path.lexists(trash_root) and trash_root.is_symlink():
        raise TrashFolderIsLink(f"{trash_root} is a symlink; refusing to move anything through it")
    assert_test_write_allowed(trash_root)
    trash_root.mkdir(parents=True, exist_ok=True)
    os.chmod(trash_root, DIR_MODE)
    ensure_trash_gitignore(trash_root)

    destination = trash_root / f"{target.name}-{stamp}"
    if os.path.lexists(destination):
        raise FileExistsError(
            f"{destination} is already occupied; a second displacement "
            "under one stamp would overwrite the first"
        )

    assert_test_write_allowed(target)
    assert_test_write_allowed(destination)
    os.replace(target, destination)
    logger.info(
        "skill_moved_to_trash", target=str(target), destination=str(destination)
    )
    return destination


def swap_in(
    staged: Path, target: Path, *, trash_root: Path, stamp: str
) -> Path:
    if not os.path.lexists(target):
        raise FileNotFoundError(
            f"{target} does not exist; a swap replaces something, and an "
            "install of something absent is a copy, not a swap"
        )

    displaced = move_to_trash(target, trash_root, stamp)

    assert_test_write_allowed(staged)
    assert_test_write_allowed(target)
    os.replace(staged, target)
    logger.info(
        "skill_swapped_in",
        staged=str(staged),
        target=str(target),
        displaced=str(displaced),
    )
    return displaced


def remove_tree(path: Path) -> None:
    assert_test_write_allowed(path)
    if not os.path.lexists(path):
        return
    if path.is_symlink() or not path.is_dir():
        os.unlink(path)
        logger.debug("skill_tree_removed", path=str(path), shape="file")
        return
    shutil.rmtree(path)
    logger.debug("skill_tree_removed", path=str(path), shape="directory")
