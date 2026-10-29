
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from src.core.federation.peer_fanout import PeerAnswer
from src.core.federation.project_folder_browse import FolderListing

_REFUSED = {"http_400": "invalid_path", "http_404": "not_found", "http_409": "unreadable"}


def path_for(path: Optional[str]) -> str:
    base = "/filesystem/project-folders"
    return base + "?" + urllib.parse.urlencode({"path": path}) if path is not None else base


def shown_for(answers: List[PeerAnswer]) -> Dict[str, Any]:
    if not answers:
        return {"status": "unavailable", "reason": "not_paired"}
    answer = answers[0]
    if answer.data is not None:
        try:
            return {"status": "ok", **FolderListing.model_validate(answer.data).model_dump()}
        except ValidationError:
            return {"status": "unavailable", "reason": "bad_answer"}
    reason = answer.reason or "no_answer"
    if reason == "http_403":
        return {"status": "refused", "code": "outside_allowed_roots"} if answer.code == "outside_allowed_roots" \
            else {"status": "unavailable", "reason": "one_way" if answer.code == "computer_one_way" else "refused"}
    if reason == "http_503":
        return {"status": "unavailable", "reason": "busy"}
    if reason in _REFUSED:
        return {"status": "refused", "code": _REFUSED[reason]}
    return {"status": "unavailable", "reason": reason}
