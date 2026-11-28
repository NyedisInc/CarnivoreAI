
from __future__ import annotations

import os
import re
from typing import Any, List, Optional, Tuple

from src.core.approvals.extract import BODY_MAX_BYTES, FAMILY_CUSTOM, KIND_TRUST, ROLE_OPTION, Dialog, Row, fingerprint_for, squash
from src.core.session_startup_gate import SCREEN_TRUST
from src.core.timers.redact import redact

CLI_COPILOT: str = "copilot"
CLI_AGY: str = "agy"
CLI_GEMINI: str = "gemini"
CLI_CURSOR: str = "cursor"
CLIS: Tuple[str, ...] = (CLI_COPILOT, CLI_AGY, CLI_GEMINI, CLI_CURSOR)

_EDGE = re.compile(r"^[\s│]+|[\s│]+$")
_ALNUM = re.compile(r"\w")
_CURSOR = "❯●▶>"
_NUMBERED = re.compile(r"^([❯●▶>])?\s*(\d+)\.\s+(\S.*)$")
_LETTERED = re.compile(r"^([❯●▶>])?\s*\[(\w)\]\s+(\S.*)$")
_PLAIN = re.compile(r"^([❯●▶>])?\s*(\S.*)$")

_COPILOT_TITLE = "Confirm folder trust"
_COPILOT_QUESTION = "Do you trust the files in this folder?"
_COPILOT_HINT = "↑/↓ to navigate"
_COPILOT_YES = "Yes"
_GEMINI_QUESTION = "Do you trust the files in this folder?"
_GEMINI_NO = "Don't trust"
_GEMINI_SESSION = re.compile(r"^Trust folder \((.+)\)$")
_CURSOR_TITLE = "⚠ Workspace Trust Required"
_CURSOR_QUESTION = "Do you trust the contents of this directory?"
_CURSOR_HINT = "Use arrow keys to navigate"
_CURSOR_YES = "Trust this workspace"
_CURSOR_QUIT = "Quit"
_AGY_QUESTION = "Do you trust the contents of this project?"
_AGY_YES = "Yes, I trust this folder"
_AGY_NO = "No, exit"
_AGY_ANCHOR = "Accessing workspace:"
_AGY_PERMISSION = "Antigravity CLI requires permission"
_AGY_HINT = "↑/↓ Navigate"
_AGY_TRAILING_LINES = 3


def _clean(text: str) -> List[str]:
    return [_EDGE.sub("", line) for line in (text or "").splitlines()]


def _last(lines: List[str], wanted: str, start: int = 0) -> Optional[int]:
    return next((i for i in range(len(lines) - 1, start - 1, -1) if lines[i] == wanted), None)


def _next_text(lines: List[str], at: int) -> Optional[int]:
    return next((i for i in range(at + 1, len(lines)) if lines[i].strip()), None)


def _quiet_after(lines: List[str], end: int, allowed: int = 0) -> bool:
    return sum(1 for ln in lines[end:] if _ALNUM.search(ln)) <= allowed


def _run(lines: List[str], start: int, pattern: "re.Pattern[str]") -> Tuple[List[Tuple[Optional[str], Optional[str], str]], int]:
    found: List[Tuple[Optional[str], Optional[str], str]] = []
    at = start
    while at < len(lines):
        hit = pattern.match(lines[at])
        if hit is None:
            break
        groups = hit.groups()
        found.append((groups[0], groups[1] if len(groups) == 3 else None, groups[-1].strip()))
        at += 1
    return found, at


def _build(lines: List[str], head: int, rows: List[str], cursor: int, question: str, shown: Optional[str]) -> Dialog:
    body_lines = [lines[head], question] + ([shown] if shown else [])
    body = redact("\n".join(body_lines)).encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
    substance = squash("".join(body_lines))
    return Dialog(
        family=FAMILY_CUSTOM, kind=KIND_TRUST, question=redact(question), body=body,
        rows=tuple(Row(label, ROLE_OPTION, None, squash(label)) for label in rows), cursor=cursor, multi_select=False,
        fingerprint=fingerprint_for(FAMILY_CUSTOM, KIND_TRUST, squash(question), [squash(r) for r in rows], substance),
        startup_kind=SCREEN_TRUST)


def _one_cursor(found: List[Tuple[Optional[str], Optional[str], str]]) -> Optional[int]:
    marked = [i for i, row in enumerate(found) if row[0]]
    return marked[0] if len(marked) == 1 else None


def _copilot(lines: List[str]) -> Optional[Dialog]:
    title = _last(lines, _COPILOT_TITLE)
    question = _last(lines, _COPILOT_QUESTION, title) if title is not None else None
    if title is None or question is None:
        return None
    shown = next((ln for ln in lines[title + 1:question] if re.search(r"[~/\w]", ln) and not ln.startswith("Copilot can")), None)
    start = _next_text(lines, question)
    if start is None:
        return None
    found, after = _run(lines, start, _NUMBERED)
    hint = _next_text(lines, after - 1)
    cursor = _one_cursor(found)
    if (len(found) != 3 or [r[1] for r in found] != ["1", "2", "3"] or cursor is None or hint is None
            or not lines[hint].startswith(_COPILOT_HINT) or not _quiet_after(lines, hint + 1) or shown is None):
        return None
    labels = [r[2] for r in found]
    if labels[0] != _COPILOT_YES or not labels[1].startswith("Yes, and remember") or not labels[2].startswith("No"):
        return None
    return _build(lines, title, labels, cursor, _COPILOT_QUESTION, shown)


def _gemini(lines: List[str]) -> Optional[Dialog]:
    question = _last(lines, _GEMINI_QUESTION)
    if question is None:
        return None
    first = next((i for i in range(question + 1, len(lines)) if (m := _NUMBERED.match(lines[i])) and m.group(2) == "1"), None)
    if first is None:
        return None
    found, after = _run(lines, first, _NUMBERED)
    labels = [r[2] for r in found]
    cursor = _one_cursor(found)
    if (cursor is None or not 2 <= len(found) <= 3 or [r[1] for r in found] != [str(i + 1) for i in range(len(found))]
            or _GEMINI_SESSION.match(labels[0]) is None or labels[-1] != _GEMINI_NO
            or (len(found) == 3 and not labels[1].startswith("Trust parent folder")) or not _quiet_after(lines, after)):
        return None
    return _build(lines, question, labels, cursor, _GEMINI_QUESTION, None)


def _cursor(lines: List[str]) -> Optional[Dialog]:
    title = _last(lines, _CURSOR_TITLE)
    question = _last(lines, _CURSOR_QUESTION, title) if title is not None else None
    if title is None or question is None:
        return None
    where = _next_text(lines, question)
    start = _next_text(lines, where) if where is not None else None
    if where is None or start is None:
        return None
    found, after = _run(lines, start, _LETTERED)
    hint = _next_text(lines, after - 1)
    labels = [r[2] for r in found]
    cursor = _one_cursor(found)
    if (cursor is None or not 2 <= len(found) <= 4 or labels.count(_CURSOR_YES) != 1 or labels.count(_CURSOR_QUIT) != 1
            or hint is None or not lines[hint].startswith(_CURSOR_HINT) or not _quiet_after(lines, hint + 1)):
        return None
    return _build(lines, title, labels, cursor, _CURSOR_QUESTION, lines[where])


def _agy(lines: List[str]) -> Optional[Dialog]:
    anchor = _last(lines, _AGY_ANCHOR)
    question = _last(lines, _AGY_QUESTION, anchor) if anchor is not None else None
    if anchor is None or question is None:
        return None
    shown = _next_text(lines, anchor)
    first = _next_text(lines, question)
    if shown is None or shown >= question or first is None:
        return None
    if lines[first].startswith(_AGY_PERMISSION):
        first = _next_text(lines, first)
    second = _next_text(lines, first) if first is not None else None
    hint = _next_text(lines, second) if second is not None else None
    if second is None or hint is None or second != first + 1 or not lines[hint].startswith(_AGY_HINT):
        return None
    found, _ = _run(lines, first, _PLAIN)
    pair = [(row[0], None, row[2]) for row in found[:2]]
    cursor = _one_cursor(pair)
    labels = [row[2] for row in pair]
    if cursor is None or labels != [_AGY_YES, _AGY_NO] or not _quiet_after(lines, hint + 1, _AGY_TRAILING_LINES):
        return None
    return _build(lines, anchor, labels, cursor, _AGY_QUESTION, lines[shown])


def decode(text: str) -> Optional[Dialog]:
    lines = _clean(text)
    for reader in (_copilot, _gemini, _cursor, _agy):
        found = reader(lines)
        if found is not None:
            return found
    return None


def cli_of(dialog: Any) -> Optional[str]:
    if dialog is None or getattr(dialog, "family", None) != FAMILY_CUSTOM or getattr(dialog, "kind", None) != KIND_TRUST:
        return None
    labels = [str(r.label) for r in dialog.rows]
    if len(labels) == 3 and labels[0] == _COPILOT_YES:
        return CLI_COPILOT
    if labels and _GEMINI_SESSION.match(labels[0]) and labels[-1] == _GEMINI_NO:
        return CLI_GEMINI
    if _CURSOR_YES in labels:
        return CLI_CURSOR
    if labels == [_AGY_YES, _AGY_NO]:
        return CLI_AGY
    return None


def safe_label(dialog: Any) -> Optional[str]:
    cli = cli_of(dialog)
    if cli == CLI_CURSOR:
        return _CURSOR_YES
    return str(dialog.rows[0].label) if cli in (CLI_COPILOT, CLI_GEMINI, CLI_AGY) else None


def shown_folder(dialog: Any) -> Optional[str]:
    lines = str(getattr(dialog, "body", "")).splitlines()
    return lines[2] if cli_of(dialog) in (CLI_COPILOT, CLI_CURSOR, CLI_AGY) and len(lines) > 2 else None


def shown_name(dialog: Any) -> Optional[str]:
    hit = _GEMINI_SESSION.match(str(dialog.rows[0].label)) if cli_of(dialog) == CLI_GEMINI else None
    return hit.group(1) if hit else None


def shows_folder(dialog: Any, folder: str) -> Optional[bool]:
    shown = shown_folder(dialog)
    if shown is None:
        return None
    expanded = os.path.expanduser(shown.strip())
    return os.path.isabs(expanded) and os.path.realpath(expanded) == folder


def row_cli(info: Any) -> Optional[str]:
    if getattr(info, "agent_family", None) in ("claude", "codex"):
        return None
    from src.core.agent_manifests.engine import manifests  # noqa: PLC0415
    from src.core.attention.pane_agent_proof import _manifest_names  # noqa: PLC0415

    agent_type = getattr(info, "agent_type", None) or getattr(getattr(info, "session", None), "agent_type", None)
    names = _manifest_names(agent_type)
    ids = {m.id for m in manifests() if names & set(m.names)}
    return next(iter(ids)) if len(ids) == 1 and next(iter(ids)) in CLIS else None
