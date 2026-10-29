
from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from src.core.crosstalk.fork.replay import ReplayPart

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}$")
logger = structlog.get_logger()
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def _safe_file(path: Path, root: Path) -> bool:
    return path.is_file() and path.resolve().is_relative_to(root.resolve()) and path.suffix == '.jsonl'


def transcript_bytes(provider: str, conversation: str, working_dir: str) -> tuple[bytes, Path | None]:
    if not _UUID.fullmatch(conversation):
        raise ValueError('source conversation id is invalid')
    if provider == 'claude':
        from src.core.claude_config.profile_roots import PROJECTS_DIRNAME, profile_subdir_roots
        from src.core.claude_transcript_correlate import default_projects_dir
        roots = profile_subdir_roots(default_projects_dir(), PROJECTS_DIRNAME)
        candidates = [(p, root) for root in roots for p in root.glob(f'*/{conversation}.jsonl')]
    elif provider == 'codex':
        from src.config import settings
        from src.config.provider_accounts import profile_dir_for
        from src.core.codex_corpus_discover import default_codex_root
        from src.core.provider_ledger import accounts_store
        roots = [default_codex_root()]
        try:
            accounts = accounts_store.list_accounts(settings.auth_config_file)
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.warning('crosstalk_fork_accounts_unavailable', error_type=type(exc).__name__)
            accounts = []
        for account in accounts:
            if account.provider == 'codex':
                roots.append(Path(profile_dir_for(account)) / 'sessions')
        candidates = [(p, root) for root in roots for p in root.glob(f'*/*/*/rollout-*-{conversation}.jsonl')]
    else:
        raise ValueError('fork supports claude and codex conversations')
    candidates = list(dict.fromkeys(p for p, root in candidates if _safe_file(p, root)))
    if len(candidates) > 1:
        raise ValueError('several live transcripts match this conversation')
    if candidates:
        with candidates[0].open('rb') as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError('fork source exceeds the 64 MiB conversion limit')
        if data.strip():
            return data, candidates[0]
    raise ValueError(f'no unambiguous live transcript for {conversation}')


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(_text(part) for part in value if part is not None)
    if isinstance(value, dict):
        kind = value.get('type')
        if kind == 'text':
            return str(value.get('text', ''))
        return f'[{kind or "content"}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}]'
    return str(value)


def replay_parts(provider: str, data: bytes) -> list[ReplayPart]:
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError('fork source exceeds the 64 MiB conversion limit')
    parts: list[ReplayPart] = []
    for raw in data.splitlines():
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError('source transcript contains an invalid record') from exc
        if provider == 'claude':
            kind = row.get('type')
            if kind not in ('user', 'assistant') or row.get('isSidechain'):
                continue
            content = (row.get('message') or {}).get('content', '')
            if isinstance(content, list):
                for item in content:
                    item_kind = item.get('type') if isinstance(item, dict) else None
                    role = ('tool_call' if item_kind == 'tool_use' else
                            'tool_output' if item_kind == 'tool_result' else kind)
                    text = _text(item)
                    if text.strip():
                        parts.append(ReplayPart(role, text))
            elif _text(content).strip():
                parts.append(ReplayPart(kind, _text(content)))
        elif provider == 'codex':
            payload = row.get('payload') or {}
            if row.get('type') == 'response_item' and payload.get('type') == 'message':
                role = payload.get('role')
                if role in ('user', 'assistant'):
                    text = _text(payload.get('content', []))
                    if text.strip():
                        parts.append(ReplayPart(role, text))
            elif row.get('type') == 'response_item' and payload.get('type') in ('function_call', 'function_call_output'):
                parts.append(ReplayPart('tool_output' if payload['type'].endswith('output') else 'tool_call', _text(payload)))
            elif row.get('type') == 'response_item' and payload.get('type') not in (None, 'message'):
                parts.append(ReplayPart('assistant', f'[historical {payload["type"]}] {_text(payload)}'))
    if not any(part.role == 'user' for part in parts):
        raise ValueError('source transcript has no user conversation')
    return parts
