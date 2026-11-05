from __future__ import annotations

from typing import Any, Iterable

from src.core.session_git.pr_status import PR_WATCH
from src.models.sessions import SessionInfo


def mark_pr(infos: Iterable[Any]) -> None:
    for info in infos:
        if not isinstance(info, SessionInfo) or (info.host_key or "local") != "local":
            continue
        info.pr = PR_WATCH.badge(getattr(info.session, "working_dir", None))
