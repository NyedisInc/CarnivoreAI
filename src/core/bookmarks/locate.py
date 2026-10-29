
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import structlog

from src.core.bookmarks.errors import TranscriptUnavailable
from src.core.session_transcript_presence import CONVERSATION_PRESENT, conversation_presence

logger = structlog.get_logger()


def _roots() -> Sequence[Path]:
    from src.core.claude_config.profile_roots import PROJECTS_DIRNAME, profile_subdir_roots
    from src.core.claude_transcript_correlate import default_projects_dir

    return profile_subdir_roots(default_projects_dir(), PROJECTS_DIRNAME)


def find_transcript(conversation: str, working_dir: Optional[str], roots: Optional[Sequence[Path]] = None) -> Path:
    for root in roots if roots is not None else _roots():
        found = conversation_presence(conversation, working_dir=working_dir, corpus_root=root)
        if found.outcome == CONVERSATION_PRESENT and found.path is not None:
            return found.path
    raise TranscriptUnavailable("this conversation's transcript is not on this computer")


def resolve_transcript(conversation: str, working_dir: Optional[str], roots: Optional[Sequence[Path]] = None) -> Path:
    try:
        return find_transcript(conversation, working_dir, roots)
    except TranscriptUnavailable:
        restore_from_points(conversation)
        return find_transcript(conversation, working_dir, roots)


def restore_from_points(conversation: str) -> Path:
    from src.cplugs.sdk import restore_points  # noqa: PLC0415

    port = restore_points.get()
    if port is None:
        raise TranscriptUnavailable(
            "this conversation's transcript is not on this computer; its copy may be in a restore point, and the "
            "restore points plugin must be on to restore it")
    try:
        path = port.restore_newest(conversation, _roots()[0])
    except restore_points.NoRestorePoint as exc:
        raise TranscriptUnavailable(
            "this conversation's transcript is not on this computer and no restore point holds it") from exc
    except (restore_points.RestoreFailed, ValueError, OSError) as exc:
        raise TranscriptUnavailable(
            f"this conversation's transcript is missing and its restore point could not be restored: {exc}") from exc
    logger.info("bookmark_transcript_restored_from_point", conversation=conversation, path=str(path))
    return path


def destination_dir(source: Path, working_dir: Optional[str]) -> Path:
    from src.core.claude_transcript_correlate import slugify_project_dir

    if not working_dir:
        return source.parent
    return source.parent.parent / slugify_project_dir(str(working_dir))
