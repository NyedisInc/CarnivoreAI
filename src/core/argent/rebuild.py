
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import structlog

from src.core.argent import notices, row_state
from src.core.argent.runtime import get_runtime

logger = structlog.get_logger()

REASON = "cannot rebuild launch command"

_ALLOWED: Dict[str, Dict[str, frozenset]] = {
    "claude": {
        "valued": frozenset({"--model", "--permission-mode", "--effort"}),
        "dirs": frozenset({"--add-dir"}),
        "bare": frozenset({"--dangerously-skip-permissions", "--verbose"}),
        "skipped_valued": frozenset({"--resume", "-r", "--name", "-n"}),
        "skipped_bare": frozenset({"--continue", "-c"}),
    },
    "codex": {
        "valued": frozenset({"--model", "-m", "--sandbox", "-s", "--ask-for-approval", "-a"}),
        "dirs": frozenset({"--add-dir"}),
        "bare": frozenset({"--full-auto"}),
        "skipped_valued": frozenset(),
        "skipped_bare": frozenset(),
    },
}
_MODEL_FLAGS = frozenset({"--model", "-m"})


@dataclass(frozen=True)
class Rebuilt:

    family: str
    model: str
    flags: Tuple[str, ...]


@dataclass(frozen=True)
class Unrebuildable:

    cause: str


class CannotRebuild(ValueError):

    def __init__(self, cause: str) -> None:
        super().__init__(f"{REASON}: {cause}")
        self.cause = cause


def parse_flags(family: str, command_line: str) -> Union[Rebuilt, Unrebuildable]:
    from src.core.message_model_secrets import scan_text

    allowed = _ALLOWED.get(family)
    if allowed is None:
        return Unrebuildable("unknown agent family")
    if scan_text(command_line):
        return Unrebuildable("a secret-looking value on the command line")
    tokens = command_line.split()
    start = next((i for i, t in enumerate(tokens) if Path(t).name == family), None)
    if start is None:
        return Unrebuildable("the agent command line is unreadable")
    words, model, i, rest = [], "", start + 1, tokens
    while i < len(rest):
        token = rest[i]
        flag, eq, inline = token.partition("=") if token.startswith("--") else (token, "", "")
        if family == "codex" and token == "resume" and i == start + 1:
            i += 2
            continue
        if flag in allowed["bare"] and not eq:
            words.append(flag)
        elif flag in allowed["skipped_bare"] and not eq:
            pass
        elif flag in allowed["valued"] | allowed["dirs"] | allowed["skipped_valued"]:
            value = inline if eq else (rest[i + 1] if i + 1 < len(rest) else "")
            i += 0 if eq else 1
            if flag in allowed["skipped_valued"]:
                pass
            elif not value or value.startswith("-"):
                return Unrebuildable(f"flag {flag} has no readable value")
            elif flag in allowed["dirs"] and not (os.path.isabs(value) and os.path.isdir(value)):
                return Unrebuildable(f"flag {flag} names a folder that cannot be read")
            elif flag in _MODEL_FLAGS:
                model = value
            else:
                words += [flag, value]
        else:
            return Unrebuildable(f"unknown flag {flag[:40]}" if token.startswith("-") else "an unknown word on the command line")
        i += 1
    return Rebuilt(family=family, model=model, flags=tuple(words))


def _measure(socket: str, name: str) -> Tuple[Optional[str], str]:
    from src.core.claude_resume_argv import find_claude_commands_in_tree, list_process_table
    from src.core.codex_process_infer import find_codex_commands_in_tree
    from src.core.tmux_session_pane_pid import probe_session_pane_pid

    pid = probe_session_pane_pid(name, socket=socket)
    table = list_process_table()
    if pid is None or table is None:
        return None, "the pane process could not be read"
    claude, codex = find_claude_commands_in_tree(pid, table), find_codex_commands_in_tree(pid, table)
    if claude and not codex:
        return "claude", claude[0]
    if codex and not claude:
        return "codex", codex[0]
    return None, "no single claude or codex process in the pane" if not (claude and codex) else "both claude and codex run in the pane"


async def rebuild_pane(socket: str, name: str, *, conversation_uuid: Optional[str], working_dir: str) -> Union[Rebuilt, Unrebuildable]:
    from src.core.session_transcript_presence import CONVERSATION_PRESENT, family_conversation_presence

    if not conversation_uuid:
        return Unrebuildable("no conversation yet")
    family, command = await asyncio.to_thread(_measure, socket, name)
    if family is None:
        return Unrebuildable(command)
    rebuilt = parse_flags(family, command)
    if isinstance(rebuilt, Unrebuildable):
        return rebuilt
    presence = await asyncio.to_thread(family_conversation_presence, family, conversation_uuid, working_dir=working_dir or None)
    if presence.outcome != CONVERSATION_PRESENT:
        return Unrebuildable("the conversation transcript was not found")
    return rebuilt


def _list_sync(name: str, working_dir: str, cause: str) -> bool:
    login = get_runtime().store.get_login()
    tenant = str(login["tenant_id"]) if login else ""
    row_state.record_launch(tenant, name, working_dir=working_dir, tethered=False, reason=f"{REASON}: {cause}", key_id="")
    return row_state.claim_notice(tenant, name)


async def list_unrebuildable(name: str, working_dir: str, cause: str) -> None:
    import sqlite3

    from src.core.sessions import launch_overlay

    try:
        if await asyncio.to_thread(_list_sync, name, working_dir, cause):
            notices.untethered_launch(name, name, f"{REASON}: {cause}")
        await launch_overlay.confirm(name)
    except sqlite3.Error as exc:
        logger.warning("argent_unrebuildable_not_listed", error_type=type(exc).__name__)
