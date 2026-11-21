
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from src.core.hosts.tmux_control import _Block
from src.core.tmux_control.names import is_control_input_session

READ_VERBS = frozenset({"list-panes", "list-sessions", "capture-pane", "show-options", "show-environment",
                        "display-message", "has-session"})

ERROR_PARITY_VERBS = READ_VERBS - {"display-message"}

PARSE_ERROR_PREFIX = b"parse error: "

ERROR_RETURNCODE = 1

Answer = Tuple[int, bytes, bytes]

Shaped = Tuple[List[str], bool]

SERVER_WIDE_FORMATS = frozenset({"#{version}"})

SESSION_SEP = "\x1f"


def segments(args: Sequence[str]) -> Optional[List[List[str]]]:
    parts: List[List[str]] = [[]]
    for word in args:
        if word == ";":
            parts.append([])
        else:
            parts[-1].append(word)
    return parts if all(parts) else None


def has_flag(words: Sequence[str], letter: str) -> bool:
    return any(w.startswith("-") and w[1:].isalpha() and letter in w[1:] for w in words)


def display_message(args: Sequence[str]) -> Optional[List[str]]:
    rest = list(args[1:])
    if "-p" not in rest:
        return None
    if "-t" not in rest and rest.count("-p") == 1 and len(rest) == 2:
        return list(args) if [w for w in rest if w != "-p"][0] in SERVER_WIDE_FORMATS else None
    if rest.count("-t") != 1:
        return None
    rest.remove("-p")
    at = rest.index("-t")
    if at + 1 >= len(rest):
        return None
    target = rest[at + 1]
    positional = rest[:at] + rest[at + 2:]
    if len(positional) != 1 or positional[0].startswith("-") or not target:
        return None
    return ["display-message", "-p", "-t", target, f"#{{session_name}}{SESSION_SEP}{positional[0]}"]


def strip_session(out: bytes) -> Optional[bytes]:
    name, sep, rest = out.partition(SESSION_SEP.encode())
    text = name.decode("utf-8", "replace")
    if not sep or not text or is_control_input_session(text):
        return None
    return rest


def shape(args: List[str]) -> Optional[Shaped]:
    if not args or args[0] not in READ_VERBS or any(a.endswith(";") for a in args):
        return None
    verb, rest = args[0], args[1:]
    if verb == "display-message":
        rewritten = display_message(args)
        if not rewritten:
            return None
        return (rewritten, "-t" in rewritten)
    if verb == "list-panes" and "-a" not in rest and "-t" not in rest:
        return None
    if verb == "has-session" and "-t" not in rest:
        return None
    if verb == "capture-pane" and not has_flag(rest, "p"):
        return None
    if verb in ("capture-pane", "show-options", "show-environment") and "-t" not in rest and not any(
            a.startswith("-") and not a.startswith("--") and "g" in a for a in rest):
        return None
    return args, False


def block_stdout(block: _Block) -> bytes:
    return b"".join(line + b"\n" for line in block.lines)


def error_answer(blocks: Sequence[_Block], commands: Sequence[Sequence[str]]) -> Optional[Answer]:
    if len(blocks) != 1 or commands[0][0] not in ERROR_PARITY_VERBS or not blocks[0].lines:
        return None
    if blocks[0].lines[0].startswith(PARSE_ERROR_PREFIX):
        return None
    return ERROR_RETURNCODE, b"", block_stdout(blocks[0])


def answer_of(blocks: Sequence[_Block], shaped: Sequence[Shaped]) -> Optional[Answer]:
    if any(b.overflow for b in blocks):
        return None
    if not all(b.ok for b in blocks):
        return error_answer(blocks, [words for words, _ in shaped])
    done = []
    for block, (_, strip) in zip(blocks, shaped):
        out = strip_session(block_stdout(block)) if strip else block_stdout(block)
        if out is None:
            return None
        done.append(out)
    return 0, b"".join(done), b""
