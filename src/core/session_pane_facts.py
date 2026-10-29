
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import structlog

from src.core.tmux_discovery import tmux_argv_prefix
from src.models.session_pane_facts import SessionPaneFacts

logger = structlog.get_logger()

READ_TIMEOUT_SECONDS = 2.0

MAX_GIT_DEPTH = 40

_FORMAT = "\t".join(
    ("#{session_name}", "#{pane_current_path}", "#{pane_current_command}", "#{pane_width}", "#{pane_height}")
)


def positive_int(text: str) -> Optional[int]:
    return int(text) if text.isdigit() and int(text) > 0 else None


def parse_display(stdout: str, tmux_name: str) -> SessionPaneFacts:
    parts = stdout.rstrip("\n").split("\t")
    if len(parts) != 5 or parts[0] != tmux_name:
        return SessionPaneFacts()
    _, cwd, command, cols, rows = parts
    return SessionPaneFacts(
        cwd=cwd or None,
        cwd_display=display_path(cwd) if cwd else None,
        command=command or None,
        cols=positive_int(cols),
        rows=positive_int(rows),
    )


def display_path(path: str, home: Optional[str] = None) -> str:
    home = home if home is not None else str(Path.home())
    if home and (path == home or path.startswith(home.rstrip("/") + "/")):
        return "~" + path[len(home.rstrip("/")):]
    return path


def find_git_head(cwd: str) -> Optional[Path]:
    try:
        here = Path(cwd)
        for folder in (here, *here.parents)[:MAX_GIT_DEPTH]:
            dot_git = folder / ".git"
            if dot_git.is_dir():
                return dot_git / "HEAD"
            if dot_git.is_file():
                line = dot_git.read_text(encoding="utf-8", errors="replace").strip()
                if not line.startswith("gitdir:"):
                    return None
                gitdir = Path(line[len("gitdir:"):].strip())
                return (gitdir if gitdir.is_absolute() else folder / gitdir) / "HEAD"
    except OSError as exc:
        logger.debug("pane_facts_git_head_unreadable", error=type(exc).__name__)
    return None


def read_head_branch(head: Path) -> Optional[str]:
    try:
        text = head.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        logger.debug("pane_facts_git_head_unreadable", error=type(exc).__name__)
        return None
    if text.startswith("ref: refs/heads/"):
        return text[len("ref: refs/heads/"):] or None
    return text[:7] if len(text) >= 7 and all(c in "0123456789abcdef" for c in text) else None


def git_branch(cwd: str) -> Optional[str]:
    head = find_git_head(cwd)
    return read_head_branch(head) if head is not None else None


async def read_pane_facts(socket: str, tmux_name: str) -> SessionPaneFacts:
    """Ask tmux about one session's active pane. Never raises.

    Inputs: socket (str) - the ``-L`` socket name; tmux_name (str) - the
      session's STORED tmux name, never one derived from its id.
    Output: SessionPaneFacts - all None when tmux could not be read.
    Example: await read_pane_facts('cloude', 'cloude_x')
    """
    argv = tmux_argv_prefix(socket) + ["display-message", "-p", "-t", f"={tmux_name}:", _FORMAT]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.debug("pane_facts_read_failed", error=type(exc).__name__)
        return SessionPaneFacts()
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), READ_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.debug("pane_facts_read_failed", error="TimeoutError")
        return SessionPaneFacts()
    if proc.returncode != 0:
        return SessionPaneFacts()
    facts = parse_display(stdout.decode("utf-8", errors="replace"), tmux_name)
    if facts.cwd:
        facts.git_branch = await asyncio.to_thread(git_branch, facts.cwd)
    return facts
