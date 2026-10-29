
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import structlog

from src.core.session_transcript_presence import (
    CONVERSATION_PRESENT,
    family_conversation_presence,
)
from src.core.transcript_source import constants as C

logger = structlog.get_logger()

SUBAGENTS_DIR: str = "subagents"


@dataclass(frozen=True)
class SourceSet:

    family: str
    conversation_id: str
    transcript: Path
    subagent_root: Optional[Path]
    subagent_files: Tuple[Path, ...]


def list_subagent_files(root: Path) -> Tuple[Path, ...]:
    found = []
    try:
        for path in root.rglob("*"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue
            found.append(path)
    except OSError as exc:
        logger.warning("transcript_source_subagents_unreadable", root=str(root), error=str(exc))
        return ()
    return tuple(sorted(found))


def locate(
    family: Optional[str],
    conversation_id: Optional[str],
    working_dir: Optional[str] = None,
    *,
    corpus_root: Optional[Path] = None,
    codex_home: Optional[str] = None,
    manifest_conn: Optional[Any] = None,
    with_subagents: bool = True,
) -> Optional[SourceSet]:
    fam = family or "claude"
    manifest_path = None
    if corpus_root is None and codex_home is None:
        from src.core.transcript_manifest.lookup import transcript_path

        manifest_path = transcript_path(conversation_id, fam, conn=manifest_conn)
    if manifest_path is not None:
        transcript = manifest_path
    elif fam != C.FAMILY_CODEX and corpus_root is None:
        from src.core.session_token_usage.claude_reader import locate_transcript

        presence = locate_transcript(conversation_id, working_dir=working_dir)
    else:
        presence = family_conversation_presence(
            fam, conversation_id, working_dir=working_dir,
            corpus_root=corpus_root, codex_home=codex_home,
        )
    if manifest_path is None:
        if presence.outcome != CONVERSATION_PRESENT or presence.path is None:
            return None
        transcript = Path(presence.path)
    sub_root: Optional[Path] = None
    files: Tuple[Path, ...] = ()
    if fam != C.FAMILY_CODEX and with_subagents:
        candidate = transcript.parent / str(conversation_id) / SUBAGENTS_DIR
        try:
            if candidate.is_dir():
                sub_root = candidate
                files = list_subagent_files(candidate)
        except OSError:
            sub_root = None
    return SourceSet(fam, str(conversation_id), transcript, sub_root, files)
