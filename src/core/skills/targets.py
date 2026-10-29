
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
