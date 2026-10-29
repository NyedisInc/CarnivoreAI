
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.crosstalk.fork.replay import ReplayPart


def rows(parts: list[ReplayPart], *, conversation: str, cwd: str) -> bytes:
    now = datetime.now(timezone.utc)
    previous: str | None = None
    lines: list[str] = []
    for index, part in enumerate(parts):
        ident = str(uuid.uuid4())
        role = part.role if part.role in ('user', 'assistant') else 'assistant'
        content = part.text if role == 'user' else [{'type': 'text', 'text':
            part.text if part.role == 'assistant' else f'[historical {part.role}]\n{part.text}'}]
        message: dict = {'role': role, 'content': content}
        if role == 'assistant':
            message.update({'model': 'claude-sonnet-4-5-20250929', 'id': 'msg_fork_' + ident.replace('-', '')})
        lines.append(json.dumps({
            'parentUuid': previous, 'isSidechain': False, 'type': role,
            'message': message, 'uuid': ident,
            'timestamp': (now + timedelta(milliseconds=index)).isoformat(),
            'userType': 'external', 'cwd': cwd, 'sessionId': conversation,
            'version': '2.1.288', 'gitBranch': '',
        }, ensure_ascii=False, separators=(',', ':')))
        previous = ident
    return ('\n'.join(lines) + '\n').encode('utf-8')


def write(parts: list[ReplayPart], *, cwd: str, profile: str | None = None) -> tuple[str, Path]:
    from src.core.claude_transcript_correlate import default_projects_dir, slugify_project_dir

    if not Path(cwd).is_dir() or not Path(cwd).is_absolute():
        raise ValueError('fork working directory must exist')
    root = Path(profile).expanduser() / 'projects' if profile else default_projects_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    project = root / slugify_project_dir(cwd)
    project.mkdir(mode=0o700, exist_ok=True)
    if not project.resolve().is_relative_to(root.resolve()):
        raise ValueError('Claude project directory escapes transcript corpus')
    conversation = str(uuid.uuid4())
    path = project / f'{conversation}.jsonl'
    data = rows(parts, conversation=conversation, cwd=cwd)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return conversation, path
