
from __future__ import annotations

import re
from typing import Sequence

_REFUSED = ("\n", "\r", "\0")

_SCRIPT_REFUSED = ("\0",)

_VERB_RE = re.compile(r"[a-z][a-z-]*")

SCRIPT_SEPARATOR = ";"

ALLOWED_VERBS = frozenset({
    "bind-key", "capture-pane", "clear-history", "delete-buffer", "display-message", "has-session",
    "kill-pane", "kill-server", "kill-session", "kill-window", "list-buffers", "list-clients",
    "list-keys", "list-panes", "list-sessions", "list-windows", "load-buffer", "new-session",
    "new-window", "paste-buffer", "pipe-pane", "refresh-client", "rename-session",
    "rename-window", "resize-pane", "resize-window", "respawn-pane", "respawn-window",
    "select-pane", "select-window", "send-keys", "set-buffer", "set-environment", "set-hook",
    "set-option", "set-window-option", "show-buffer", "show-environment", "show-hooks",
    "show-options", "show-window-options", "source-file", "split-window",
})


class TmuxQuoteError(ValueError):
    pass


def quote(arg: str) -> str:
    return _quoted(arg, _REFUSED)


def _quoted(arg: str, refused: Sequence[str]) -> str:
    if not isinstance(arg, str):
        raise TmuxQuoteError(f"a tmux argument must be str, not {type(arg).__name__}")
    for char in refused:
        if char in arg:
            raise TmuxQuoteError(f"a tmux argument cannot contain {char!r}: it would end the line")
    try:
        arg.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TmuxQuoteError("a tmux argument must be valid UTF-8") from exc
    return "'" + arg.replace("'", "'\\''") + "'"


def literal(text: str) -> str:
    return text.replace("#", "##")


_VALUE_FLAGS = {
    "new-session": ("cefFnstxy", "cns"),
    "new-window": ("ceFnt", "cn"),
    "split-window": ("celFt", "c"),
    "respawn-pane": ("cet", "c"),
    "respawn-window": ("cet", "c"),
    "rename-session": ("t", ""),
    "rename-window": ("t", ""),
    "pipe-pane": ("t", ""),
}

_LAST_WORD_EXPANDED = frozenset({"rename-session", "rename-window", "pipe-pane"})


def escape_expanded(verb: str, args: Sequence[str]) -> list:
    out = list(args)
    flags = _VALUE_FLAGS.get(verb)
    if flags is None:
        return out
    takes_value, expanded = flags
    index = 0
    while index < len(out):
        word = out[index]
        if word == "--" or not word.startswith("-") or word == "-":
            break
        for position, flag in enumerate(word[1:], start=1):
            if flag in takes_value:
                attached = word[position + 1:]
                if attached:
                    if flag in expanded:
                        out[index] = word[:position + 1] + literal(attached)
                elif index + 1 < len(out):
                    index += 1
                    if flag in expanded:
                        out[index] = literal(out[index])
                break
        index += 1
    if verb in _LAST_WORD_EXPANDED and index < len(out):
        if out[index] == "--":
            index += 1
        if index == len(out) - 1:
            out[index] = literal(out[index])
    return out


def command_line(verb: str, args: Sequence[str] = ()) -> str:
    if verb not in ALLOWED_VERBS:
        raise TmuxQuoteError(f"{verb!r} is not a command the control channel may send")
    if isinstance(args, str):
        raise TmuxQuoteError("args must be a sequence of words, not one str")
    return " ".join([verb, *(quote(arg) for arg in args)])


def script_line(tokens: Sequence[str]) -> str:
    if isinstance(tokens, str):
        raise TmuxQuoteError("tokens must be a sequence of words, not one str")
    words: list = []
    expect_verb = True
    for token in tokens:
        if token == SCRIPT_SEPARATOR:
            if expect_verb:
                raise TmuxQuoteError("a script command cannot be empty")
            words.append(SCRIPT_SEPARATOR)
            expect_verb = True
        elif expect_verb:
            if not isinstance(token, str) or not _VERB_RE.fullmatch(token):
                raise TmuxQuoteError("a script command must start with a tmux verb")
            words.append(token)
            expect_verb = False
        else:
            words.append(_quoted(token, _SCRIPT_REFUSED))
    if expect_verb:
        raise TmuxQuoteError("a script command cannot be empty")
    return " ".join(words)
