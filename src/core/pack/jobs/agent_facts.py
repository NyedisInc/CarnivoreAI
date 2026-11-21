
from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.pack.jobs import gitio
from src.core.pack.jobs.agent_types import (ACCOUNT_KEY_PATTERN, AGENT_NAME_PATTERN, CLAUDE_MODES, DEFINITION_MAX,
                                            definition_fits, valid_model)
from src.core.pack.jobs.types import JobError

log = structlog.get_logger(__name__)

TAIL_BYTES = 512 * 1024
FILE_MAX = 64 * 1024
CODEX_POSTURE = {"skip_all": "skip_all"}


@dataclass
class CallerFacts:

    family: str
    account_key: Optional[str] = None
    permission_mode: str = "default"
    model: Optional[str] = None
    profile_dir: Optional[str] = None
    account_identity: str = ""


@dataclass
class AgentDefinition:

    definition_json: str
    body: str
    model: Optional[str]
    path: str


def map_claude_mode(raw: Optional[str]) -> str:
    if raw in CLAUDE_MODES and raw != "plan":
        return str(raw)
    return "default"


def newest_permission_mode(path: Path, tail_bytes: int = TAIL_BYTES) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError as exc:
        log.info("pack_job_transcript_unreadable", error=type(exc).__name__)
        return None, None
    mode: Optional[str] = None
    model: Optional[str] = None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if mode is None and rec.get("type") in ("user", "permission-mode") and isinstance(rec.get("permissionMode"), str):
            mode = rec["permissionMode"]
        if model is None and rec.get("type") == "assistant" and isinstance(rec.get("message"), dict):
            got = rec["message"].get("model")
            model = got if isinstance(got, str) and got else None
        if mode is not None and model is not None:
            break
    return mode, model


def _caller_identity(family: str, profile_dir: Optional[str]) -> str:
    if family != "claude":
        return ""
    from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR
    from src.core.provider_ledger.credentials import read_claude_identity

    got = read_claude_identity(profile_dir or DEFAULT_CLAUDE_CONFIG_DIR)
    return got.email.strip().lower() if got is not None and got.email else ""


def _clean_model(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and valid_model(value) and value != "inherit" else None


def _transcript_facts(sm: Any, info: Any, family: str) -> Tuple[Optional[str], Optional[str]]:
    from src.core.session_token_usage import claude_reader

    tmux = info.tmux_session
    uuid = sm.claude_uuid_for_tmux_name(tmux) if tmux else None
    if not uuid:
        return None, None
    where = claude_reader.locate_transcript(uuid, working_dir=info.session.working_dir if info.session is not None else None)
    return newest_permission_mode(where.path) if where.path is not None else (None, None)


async def info_for_caller(sm: Any, caller_session: Optional[str]) -> Any:
    if sm is None or not caller_session:
        return None
    for info in await sm.list_session_infos():
        if caller_session in (info.session_uuid, info.session.id if info.session is not None else None):
            return info
    return None


async def caller_launch_facts(app: Any, caller_session: Optional[str]) -> CallerFacts:
    from src.config import settings
    from src.core.account_switch import pane_account
    from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
    from src.core.session_token_usage.account_resolve import resolve_session_account

    sm = getattr(app.state, "session_manager", None)
    info = await info_for_caller(sm, caller_session)
    if info is None:
        raise JobError("bad_request", "the calling session is not known, so its launch facts cannot be read", 422)
    family = info.agent_family or ""
    if family not in ("claude", "codex"):
        raise JobError("bad_request", "an agent job needs a claude or codex session to copy", 422)
    profile_dir: Optional[str] = None
    if info.tmux_session:
        pane = await pane_account.read_pane_profile(sm.tmux_socket_name(), info.tmux_session, PROFILE_ENV_VARS[family])
        profile_dir = pane.value if pane.readable else None
    acct = await asyncio.to_thread(resolve_session_account, Path(settings.auth_config_file).expanduser(), agent_family=family, profile_dir=profile_dir)
    key = acct.id if acct is not None and re.fullmatch(ACCOUNT_KEY_PATTERN, acct.id or "") else None
    model = _clean_model(info.running_model)
    posture = (info.launched_with or {}).get("permissions")
    ident = await asyncio.to_thread(_caller_identity, family, profile_dir)
    if family == "claude":
        raw, seen = await asyncio.to_thread(_transcript_facts, sm, info, family)
        mode = map_claude_mode(raw)
        if mode == "bypassPermissions" and posture != "skip_all":
            mode = "default"
        return CallerFacts("claude", key, mode, model or _clean_model(seen), profile_dir, ident)
    return CallerFacts("codex", key, CODEX_POSTURE.get(str(posture), "ask"), model, profile_dir, ident)




def parse_agent_file(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text.strip()
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text.strip()
    fields: Dict[str, str] = {}
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep or line[:1] in " \t-#" or not key.strip():
            continue
        value = value.strip()
        if value[:1] == '"':
            try:
                value = str(json.loads(value))
            except ValueError:
                value = value.strip('"')
        fields[key.strip()] = value.strip("'") if value[:1] == "'" else value
    return fields, text[end + 4:].strip()


def _names(value: Optional[str]) -> List[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _read_definition_text(path: Path, name: str) -> str:
    try:
        real, folder = path.resolve(), path.parent.resolve()
        if folder not in real.parents:
            raise JobError("bad_request", f"the agent definition {name} is a link that leaves its agents folder", 422)
        fd = os.open(real, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise JobError("bad_request", f"the agent definition {name} is not a plain file", 422)
            data = handle.read(FILE_MAX + 1)
    except OSError as exc:
        raise JobError("bad_request", f"the agent definition {name} could not be read ({type(exc).__name__})", 422) from exc
    if len(data) > FILE_MAX:
        raise JobError("definition_too_large", f"the agent definition {name} is too large to start a worker with", 422)
    return data.decode("utf-8", "replace")


def definition_from_file(path: Path, name: str) -> AgentDefinition:
    fields, body = parse_agent_file(_read_definition_text(path, name))
    obj: Dict[str, Any] = {"description": fields.get("description") or name, "prompt": body}
    for key in ("tools", "disallowedTools"):
        if fields.get(key):
            obj[key] = _names(fields[key])
    model = _clean_model(fields.get("model"))
    if model:
        obj["model"] = model
    if fields.get("effort"):
        obj["effort"] = fields["effort"]
    text = json.dumps(obj, ensure_ascii=False)
    if len(text.encode("utf-8")) > DEFINITION_MAX or not definition_fits(name, text):
        raise JobError("definition_too_large", f"the agent definition {name} is too large to start a worker with (8 KiB, and about 10 KB once quoted)", 422)
    return AgentDefinition(text, body, model, str(path))


def search_places(caller_dir: str, name: str, profile_dir: Optional[str] = None, home: Optional[Path] = None) -> List[Path]:
    places: List[Path] = []
    top = gitio.run(["rev-parse", "--show-toplevel"], cwd=caller_dir, check=False)
    if top.returncode == 0 and gitio.out(top):
        places.append(Path(gitio.out(top)) / ".claude" / "agents" / f"{name}.md")
    if profile_dir:
        places.append(Path(profile_dir).expanduser() / "agents" / f"{name}.md")
    places.append((home or Path.home()) / ".claude" / "agents" / f"{name}.md")
    return list(dict.fromkeys(places))


def read_definition(caller_dir: str, name: str, *, profile_dir: Optional[str] = None, home: Optional[Path] = None) -> AgentDefinition:
    if not re.fullmatch(AGENT_NAME_PATTERN, name or ""):
        raise JobError("bad_request", "agent_type must be a lowercase slug (letters, digits, hyphens)", 422)
    places = search_places(caller_dir, name, profile_dir, home)
    for place in places:
        if place.is_file():
            return definition_from_file(place, name)
    raise JobError("unknown_agent_type", f"no agent type named {name}; looked in {', '.join(str(p) for p in places)}", 422)

