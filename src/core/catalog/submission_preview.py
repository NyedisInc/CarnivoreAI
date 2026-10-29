
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.core.catalog import submission_rules as rules

logger = structlog.get_logger()

MAX_MANIFEST_BYTES = 64 * 1024


class FolderUnreadable(Exception):
    """The named folder could not be read at all.

    Description: DISTINCT FROM A REFUSAL, and the distinction is the
      whole reason this class exists. "This folder would be refused" is
      an answer about a folder that was read; "this folder could not be
      read" is not an answer about the folder at all. Collapsing them
      would show somebody an empty file list and let them conclude their
      skill has nothing in it.
    """


@dataclass
class FolderPreview:

    name: str
    version: str
    files: List[Tuple[str, int]] = field(default_factory=list)
    total_bytes: int = 0
    refusals: List[rules.Refusal] = field(default_factory=list)


def _resolve(folder_path: str) -> Path:
    """Turn the requested path into a directory, or refuse to.

    Description: ``expanduser`` then ``realpath``, and NOT ``expanduser``
      alone. ``realpath`` resolves symlinks, so a folder reached by its
      short spelling is recorded by its long one; that is gotcha 6 in
      this repository, where one directory became two projects because a
      path was expanded and not resolved.
    Inputs: folder_path (str) - whatever the client sent.
    Output: Path - an existing directory.
    Raises: FolderUnreadable - blank, missing, or not a directory.
    Example: _resolve("~/skills/mine")
    """
    raw = (folder_path or "").strip()
    if not raw:
        raise FolderUnreadable("no folder was named")
    resolved = Path(os.path.realpath(Path(raw).expanduser()))
    if not resolved.exists():
        raise FolderUnreadable(f"there is no folder at {raw}")
    if not resolved.is_dir():
        raise FolderUnreadable(f"{raw} is not a folder")
    return resolved


def _read_manifest(folder: Path) -> Optional[str]:
    manifest = folder / rules.MANIFEST_NAME
    if manifest.is_symlink() or not manifest.is_file():
        return None
    try:
        with open(manifest, "rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES)
    except OSError as exc:
        logger.warning(
            "catalog_submission_manifest_unreadable",
            folder=str(folder),
            error=str(exc),
        )
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.info("catalog_submission_manifest_not_utf8", folder=str(folder))
        return None


def _walk(folder: Path, preview: FolderPreview) -> List[str]:
    seen: dict = {}
    accepted: List[str] = []
    for parent, dir_names, file_names in os.walk(folder, followlinks=False):
        parent_path = Path(parent)
        for dir_name in list(dir_names):
            if (parent_path / dir_name).is_symlink():
                relpath = (parent_path / dir_name).relative_to(folder).as_posix()
                preview.refusals.append(
                    rules.Refusal(
                        rules.SUBMISSION_INVALID,
                        "a symlink cannot be submitted, and it was not followed",
                        relpath,
                    )
                )
                dir_names.remove(dir_name)

        for file_name in file_names:
            absolute = parent_path / file_name
            relpath = absolute.relative_to(folder).as_posix()

            if absolute.is_symlink():
                preview.refusals.append(
                    rules.Refusal(
                        rules.SUBMISSION_INVALID,
                        "a symlink cannot be submitted, and it was not followed",
                        relpath,
                    )
                )
                continue

            refusal = rules.refuse_member_path(relpath, seen)
            if refusal is not None:
                preview.refusals.append(refusal)
                continue

            try:
                stat = absolute.lstat()
            except OSError as exc:
                preview.refusals.append(
                    rules.Refusal(
                        rules.SUBMISSION_INVALID,
                        f"this file could not be measured: {exc.strerror or exc}",
                        relpath,
                    )
                )
                continue

            if stat.st_nlink > 1:
                preview.refusals.append(
                    rules.Refusal(
                        rules.SUBMISSION_INVALID,
                        "a hard-linked file cannot be submitted",
                        relpath,
                    )
                )
                continue

            if not os.path.isfile(absolute) or stat.st_size < 0:
                preview.refusals.append(
                    rules.Refusal(
                        rules.SUBMISSION_INVALID,
                        "only ordinary files can be submitted",
                        relpath,
                    )
                )
                continue

            if stat.st_size > rules.MAX_FILE_BYTES:
                preview.refusals.append(
                    rules.Refusal(
                        rules.BODY_TOO_LARGE,
                        f"this file is larger than {rules.MAX_FILE_BYTES} bytes",
                        relpath,
                    )
                )
                continue

            accepted.append(relpath)
            preview.files.append((relpath, stat.st_size))
            preview.total_bytes += stat.st_size

    preview.files.sort(key=lambda entry: entry[0])
    return accepted


def preview_folder(folder_path: str) -> FolderPreview:
    folder = _resolve(folder_path)
    preview = FolderPreview(name=folder.name, version=rules.DEFAULT_VERSION)

    name_refusal = rules.refuse_name(folder.name)
    if name_refusal is not None:
        preview.refusals.append(name_refusal)

    accepted = _walk(folder, preview)

    if len(accepted) > rules.MAX_MEMBERS:
        preview.refusals.append(
            rules.Refusal(
                rules.SUBMISSION_INVALID,
                f"a folder may carry at most {rules.MAX_MEMBERS} files",
            )
        )
    if preview.total_bytes > rules.MAX_SUBMISSION_BYTES:
        preview.refusals.append(
            rules.Refusal(
                rules.BODY_TOO_LARGE,
                f"the folder is larger than {rules.MAX_SUBMISSION_BYTES} bytes",
            )
        )

    scripts = rules.refuses_for_scripts(accepted)
    if scripts is not None:
        preview.refusals.append(scripts)

    nested = [path for path in accepted if path.endswith("/" + rules.MANIFEST_NAME)]
    if nested:
        preview.refusals.append(
            rules.Refusal(
                rules.SUBMISSION_INVALID,
                f"{rules.MANIFEST_NAME} must be at the folder root",
                nested[0],
            )
        )

    preview.refusals.extend(
        rules.refuse_manifest(folder.name, _read_manifest(folder))
    )

    logger.info(
        "catalog_submission_previewed",
        files=len(preview.files),
        total_bytes=preview.total_bytes,
        refusals=len(preview.refusals),
    )
    return preview
