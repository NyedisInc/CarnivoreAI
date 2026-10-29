
from __future__ import annotations

from typing import Any, Awaitable, Callable, List, NamedTuple, Sequence, Tuple

import structlog

from src.core.debug_trace import fingerprint, is_secret_name
from src.core.hosts.tmux_quote import TmuxQuoteError, script_line

logger = structlog.get_logger()

STDIN_SCRIPT_ARGS: Tuple[str, ...] = ("source-file", "-")

COMMAND_SEPARATOR: str = ";"

TmuxCommand = Sequence[str]


class BatchOutcome(NamedTuple):

    batched: bool
    failures: Tuple[Tuple[Tuple[str, ...], int, str], ...]


EMPTY_BATCH: BatchOutcome = BatchOutcome(batched=True, failures=())


def build_batch_argv(commands: Sequence[TmuxCommand]) -> List[str]:
    if not commands:
        raise ValueError("build_batch_argv needs at least one command")
    argv: List[str] = []
    for command in commands:
        tokens = list(command)
        if not tokens:
            raise ValueError("build_batch_argv was given an empty command")
        for token in tokens:
            if token == COMMAND_SEPARATOR or (
                token.endswith(COMMAND_SEPARATOR)
                and not token.endswith("\\" + COMMAND_SEPARATOR)
            ):
                raise ValueError(
                    f"token {token!r} would be read by tmux as a command "
                    f"separator and cannot travel inside a batch"
                )
        if argv:
            argv.append(COMMAND_SEPARATOR)
        argv.extend(tokens)
    return argv


async def run_optional_batch(
    run_tmux: Callable[..., Awaitable[Tuple[int, bytes, bytes]]],
    commands: Sequence[TmuxCommand],
    *,
    note: str,
) -> BatchOutcome:
    if not commands:
        return EMPTY_BATCH

    if len(commands) > 1:
        try:
            argv = build_batch_argv(commands)
        except ValueError as exc:
            logger.warning(
                "tmux_batch_refused", note=note, error=str(exc)
            )
            return await _run_individually(run_tmux, commands, note=note)

        rc, _, err = await run_tmux(*argv, check=False)
        if rc == 0:
            return BatchOutcome(batched=True, failures=())

        logger.warning(
            "tmux_batch_degraded",
            note=note,
            returncode=rc,
            stderr=err.decode("utf-8", errors="replace").strip()[:300],
            commands=len(commands),
        )

    return await _run_individually(run_tmux, commands, note=note)


async def _run_individually(
    run_tmux: Callable[..., Awaitable[Tuple[int, bytes, bytes]]],
    commands: Sequence[TmuxCommand],
    *,
    note: str,
) -> BatchOutcome:
    failures: List[Tuple[Tuple[str, ...], int, str]] = []
    for command in commands:
        tokens = tuple(command)
        rc, _, err = await run_tmux(*tokens, check=False)
        if rc != 0:
            stderr = err.decode("utf-8", errors="replace").strip()
            failures.append((tokens, rc, stderr))
            logger.warning(
                "tmux_batch_command_failed",
                note=note,
                command=loggable_command(tokens),
                returncode=rc,
                stderr=stderr[:200],
            )
    return BatchOutcome(batched=False, failures=tuple(failures))


def environment_commands(
    target: str, spawn_env: Any
) -> List[TmuxCommand]:
    if not spawn_env:
        return []
    return [
        ("set-environment", "-t", target, "-r", str(var))
        if val is None
        else ("set-environment", "-t", target, str(var), str(val))
        for var, val in spawn_env.items()
    ]


def stdin_script(args: Sequence[str]) -> bytes:
    return (script_line(list(args)) + "\n").encode("utf-8")


async def run_on_stdin(
    run_tmux: Callable[..., Awaitable[Tuple[int, bytes, bytes]]],
    *args: str,
    check: bool = True,
) -> Tuple[int, bytes, bytes]:
    try:
        script = stdin_script(args)
    except TmuxQuoteError as exc:
        logger.warning("tmux_stdin_script_refused", verb=args[0] if args else "", error=str(exc))
        return 1, b"", str(exc).encode("utf-8")
    return await run_tmux(*STDIN_SCRIPT_ARGS, stdin_bytes=script, check=check)


def loggable_command(tokens: Sequence[str]) -> str:
    out: List[str] = []
    command: List[str] = []
    for word in map(str, tokens):
        if word == COMMAND_SEPARATOR:
            out.extend(_redacted(command) + [word])
            command = []
        else:
            command.append(word)
    out.extend(_redacted(command))
    return " ".join(out)


def _redacted(words: List[str]) -> List[str]:
    words = list(words)
    if words[:1] == ["set-environment"]:
        index = 1
        while index < len(words) and words[index].startswith("-") and words[index] != "--":
            index += 2 if words[index] == "-t" else 1
        index += 1 if index < len(words) and words[index] == "--" else 0
        if index + 1 < len(words) and is_secret_name(words[index]):
            words[index + 1] = fingerprint(words[index + 1])
        return words
    for index in range(1, len(words)):
        if words[index - 1] == "-e":
            words[index] = redact_env_pair(words[index])
    return words


def redact_env_pair(pair: str) -> str:
    name, sep, value = pair.partition("=")
    return f"{name}={fingerprint(value)}" if sep and is_secret_name(name) else pair
