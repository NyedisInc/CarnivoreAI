
from __future__ import annotations

import pytest

from src.core.hosts.tmux_quote import TmuxQuoteError, command_line, literal, quote


@pytest.mark.parametrize("arg, expected", [
    ("plain", "'plain'"),
    ("", "''"),
    ("it's", "'it'\\''s'"),
    ("a b;c", "'a b;c'"),
    ("$HOME ~ {x} #{y} \\", "'$HOME ~ {x} #{y} \\'"),
])
def test_quote_single_quotes_every_argument(arg: str, expected: str) -> None:
    assert quote(arg) == expected


@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\0b", "\n", "\ud800"])
def test_quote_refuses_what_would_end_or_corrupt_the_line(bad: str) -> None:
    with pytest.raises(TmuxQuoteError):
        quote(bad)


def test_quote_refuses_a_non_string() -> None:
    with pytest.raises(TmuxQuoteError):
        quote(b"bytes")  # type: ignore[arg-type]


def test_literal_doubles_every_hash() -> None:
    assert literal("#(id) ##{x}") == "##(id) ####{x}"
    assert literal("plain") == "plain"


def test_command_line_quotes_args_and_allowlists_the_verb() -> None:
    assert command_line("has-session", ["-t", "=x"]) == "has-session '-t' '=x'"
    assert command_line("list-sessions") == "list-sessions"
    for verb in ["", "Kill", "kill-server;", "a b", "new-session\n", "-t", "run-shell", "run",
                 "wait-for", "wait", "attach-session", "attach", "if-shell", "command-prompt",
                 "display-popup", "kill-s"]:
        with pytest.raises(TmuxQuoteError):
            command_line(verb, [])
    with pytest.raises(TmuxQuoteError):
        command_line("send-keys", "abc")
    with pytest.raises(TmuxQuoteError):
        command_line("send-keys", ["-l", "x\ny"])
