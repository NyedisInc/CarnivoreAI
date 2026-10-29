"""The ONE rule for a plain yes or no on a permission prompt, and the one-line summary of what it approves.

Pure, no I/O. Three callers share it: the dialog answer driver (``choice: {"plain": "yes"|"no"}``,
resolved against the FRESH pane at the write), the approvals inbox (``plain_yes``, ``plain_no`` and
``summary`` on a dialog item, so the questions tab can draw approve and deny), and Beast Mode's
prompts scope (``src/core/beast_prompts/engine.py``), which answers only what :func:`auto_approvable`
admits.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from src.core.approvals.extract import FAMILY_CLAUDE, FAMILY_CODEX, KIND_CODEX, KIND_PERMISSION, Dialog

APPROVABLE_KINDS: Tuple[str, ...] = (KIND_PERMISSION, KIND_CODEX)

YES_LABELS: Tuple[str, ...] = ("yes", "yes, proceed")

SUMMARY_COMMAND_CHARS: int = 80
SUMMARY_TOOL_CHARS: int = 40

PLAIN_YES = "yes"
PLAIN_NO = "no"

_KEY_HINT = re.compile(r"\s*\((?:[a-z]|esc)\)\s*$")
_SHELL_LINE = re.compile(r"^\s*\$\s+(\S.*)$")
_TIP = re.compile(r"^\s*tip:", re.I)


def _norm(label: str) -> str:
    return " ".join(_KEY_HINT.sub("", label).split()).lower()


def plain_yes_label(dialog: Optional[Dialog]) -> Optional[str]:
    if dialog is None or dialog.kind not in APPROVABLE_KINDS or dialog.multi_select or dialog.tabs:
        return None
    for label in dialog.options:
        if _norm(label) in YES_LABELS:
            return label
    return None


def plain_no_label(dialog: Optional[Dialog]) -> Optional[str]:
    if plain_yes_label(dialog) is None:
        return None
    for label in dialog.options:  # type: ignore[union-attr]
        text = _norm(label)
        if text == "no" or text.startswith("no,") or text.startswith("no "):
            return label
    return None


def plain_label(dialog: Optional[Dialog], answer: str) -> Optional[str]:
    if answer == PLAIN_YES:
        return plain_yes_label(dialog)
    if answer == PLAIN_NO:
        return plain_no_label(dialog)
    return None


def _cut(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: max(limit - 3, 0)] + "..."


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def summarize(dialog: Optional[Dialog]) -> Tuple[str, str]:
    if dialog is None:
        return "", ""
    lines = (dialog.body or "").splitlines()
    if dialog.family == FAMILY_CODEX:
        for line in lines:
            shell = _SHELL_LINE.match(line)
            if shell:
                return "command", _cut(shell.group(1), SUMMARY_COMMAND_CHARS)
        return _cut(dialog.question, SUMMARY_TOOL_CHARS), ""
    question = " ".join(dialog.question.split())
    tool_line: Optional[str] = None
    command = ""
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if question and (text == question or question.startswith(text) and len(text) >= 12):
            break
        if tool_line is None:
            tool_line = line
            continue
        if _TIP.match(line) or _indent(line) <= _indent(tool_line):
            continue
        command = text
        break
    tool = tool_line.strip() if tool_line is not None else (dialog.question if dialog.family == FAMILY_CLAUDE else "")
    return _cut(tool, SUMMARY_TOOL_CHARS), _cut(command, SUMMARY_COMMAND_CHARS)


def summary_line(dialog: Optional[Dialog]) -> str:
    tool, command = summarize(dialog)
    return f"{tool}: {command}" if tool and command else tool or command
