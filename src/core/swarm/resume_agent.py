
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence

import structlog

logger = structlog.get_logger(__name__)

PLAIN_SESSION_AGENT = "claude"
AGENT_FLAG = "--agent"
RESUME_FLAG = "--resume"
_AGENT_SETTING_TYPE = "agent-setting"
_AGENT_SETTING_MARKER = b'"agent-setting"'


def resume_uuid(args: Optional[Sequence[str]]) -> Optional[str]:
    items = list(args or [])
    for i, token in enumerate(items[:-1]):
        if token == RESUME_FLAG:
            return str(items[i + 1])
    return None


def names_agent(args: Optional[Sequence[str]]) -> bool:
    return any(t == AGENT_FLAG or str(t).startswith(AGENT_FLAG + "=") for t in (args or []))


def last_agent_setting(path: Path) -> Optional[str]:
    found: Optional[str] = None
    try:
        with open(path, "rb") as handle:
            for line in handle:
                if _AGENT_SETTING_MARKER not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("type") == _AGENT_SETTING_TYPE:
                    name = record.get("agentSetting")
                    found = name.strip() if isinstance(name, str) and name.strip() else None
    except OSError as exc:
        logger.info("resume_agent_transcript_unreadable", path=str(path), error=type(exc).__name__)
        return None
    return found


def plain_resume_override(args: Optional[Sequence[str]], working_dir: Optional[str] = None) -> List[str]:
    uuid = resume_uuid(args)
    if not uuid or names_agent(args):
        return []
    from src.core.session_transcript_presence import conversation_presence

    path = conversation_presence(uuid, working_dir=working_dir).path
    if path is None:
        logger.info("resume_agent_no_transcript", conversation=uuid)
        return []
    saved = last_agent_setting(Path(path))
    if not saved:
        return []
    logger.info("resume_agent_cleared", conversation=uuid, saved_agent=saved)
    return [AGENT_FLAG, PLAIN_SESSION_AGENT]
