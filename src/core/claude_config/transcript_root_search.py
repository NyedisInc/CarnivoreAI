
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import structlog

from src.core.session_transcript_presence import (
    CONVERSATION_ABSENT,
    CONVERSATION_PRESENT,
    CONVERSATION_UNCHECKED,
    ConversationPresence,
    _forget_root_listing,
    _remembered_path,
    _scan_children,
    root_children,
)

logger = structlog.get_logger()


def corpus_roots(corpus_root: Optional[Path]) -> Tuple[Path, ...]:
    if corpus_root is not None:
        return (Path(corpus_root),)
    from src.core.claude_config.transcript_roots import claude_transcript_roots

    return claude_transcript_roots()


def measure_in_root(
    root: Path, claude_session_uuid: str, working_dir: Optional[str]
) -> ConversationPresence:
    from src.core.claude_transcript_correlate import slugify_project_dir

    filename = f"{claude_session_uuid}.jsonl"

    if working_dir:
        fast = root / slugify_project_dir(str(working_dir)) / filename
        try:
            if fast.is_file():
                return ConversationPresence(CONVERSATION_PRESENT, path=fast)
        except OSError as exc:
            logger.debug(
                "conversation_presence_fast_path_unreadable",
                path=str(fast),
                error=str(exc),
            )

    remembered = _remembered_path(root, filename)
    if remembered is not None:
        return ConversationPresence(CONVERSATION_PRESENT, path=remembered)

    for _attempt in (0, 1):
        try:
            children, from_cache = root_children(root)
        except OSError as exc:
            return ConversationPresence(
                CONVERSATION_UNCHECKED,
                detail=(
                    f"the transcript corpus at {root} could not be read "
                    f"({exc.strerror or exc}), so whether this conversation "
                    "still exists could not be determined"
                ),
            )
        found, unreadable = _scan_children(children, filename, root)
        if found is not None:
            return ConversationPresence(CONVERSATION_PRESENT, path=found)
        if not (unreadable and from_cache):
            break
        _forget_root_listing(root)

    return ConversationPresence(CONVERSATION_ABSENT, detail=f"not under {root}", unreadable=unreadable)
