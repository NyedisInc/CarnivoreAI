
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

from src.plugins.save.offload.chain import build
from src.plugins.sdk.session_chains import ChainSnapshot, SessionFacts
from src.plugins.sdk.transcript_files import slugify_project_dir

LOCAL_HOST: str = "local"


def _rank(facts: SessionFacts, conversation_id: str) -> Tuple[int, float, str]:
    current = 0 if facts.claude_session_uuid == conversation_id else 1
    return (current, -(facts.last_active_epoch or 0.0), facts.session_uuid)


def resume_folder_of(working_dir: Optional[str]) -> Optional[str]:
    if not working_dir or not os.path.isabs(working_dir):
        return None
    return slugify_project_dir(os.path.normpath(working_dir))


def resume_folders(snapshot: ChainSnapshot, conversation_ids: Iterable[str]) -> Dict[str, str]:
    chains = build(snapshot)
    out: Dict[str, str] = {}
    for conversation in dict.fromkeys(conversation_ids):
        holders: List[SessionFacts] = [chains.sessions[s] for s in chains.owners_of(conversation)]
        local = sorted((f for f in holders if f.host_key == LOCAL_HOST and f.working_dir), key=lambda f: _rank(f, conversation))
        folder = resume_folder_of(str(local[0].working_dir)) if local else None
        if folder is not None:
            out[conversation] = folder
    return out

