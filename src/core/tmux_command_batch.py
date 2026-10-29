
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
    """Flatten several tmux commands into one argv, ``;`` separated.

    Args:
        commands: the commands, each an argv fragment with no ``tmux -L``
            prefix. Must be non-empty and contain no empty command.

    Returns:
        list[str]: the flattened argv fragment.

    Raises:
        ValueError: when a command is empty, or when any token would be
            read by tmux as a command separator - a token that IS ``;``
            or ENDS in an unescaped ``;``. Such a token would split the
            batch at a place the caller did not intend, running half a
            command with the rest of it as arguments to something else.
            Refusing loudly is the only safe answer; a semicolon in the
            MIDDLE of a token is fine and is passed through.

    Example:
        >>> build_batch_argv([("set-option", "-g", "mouse", "on"),
        ...                   ("set-option", "-s", "escape-time", "0")])
        ['set-option', '-g', 'mouse', 'on', ';', 'set-option', '-s', 'escape-time', '0']
    """
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
    """Run a tmux command with its arguments on stdin, never on argv.

    WHY. Any local process can list every other process's command line
    (``ps -axww``, any user, on macOS), while a process's environment and
    pipes are readable only by its own user. A hook token passed as
    ``set-environment ... CLOUDECODE_HOOK_TOKEN <value>`` or
    ``new-session -e CLOUDECODE_HOOK_TOKEN=<value>`` was on the command
    line of the tmux client for the life of the call, and on the tmux
    SERVER's for the life of the socket when that call started it. Here the
    tmux client's argv is only ``source-file -``.

    A drop-in for ``run_tmux`` (same signature, same return), so it also
    serves as the ``run_tmux`` of :func:`run_optional_batch`.

    Args:
        run_tmux: ``TmuxBackend._run_tmux`` (must accept ``stdin_bytes``).
        *args: the command, as it would follow ``tmux -L <socket>``.
        check: passed through.

    Returns:
        tuple: (returncode, stdout, stderr). An argument that cannot be
        encoded answers rc 1 with the reason (never the value) as stderr,
        and nothing is run.
    """
    try:
        script = stdin_script(args)
    except TmuxQuoteError as exc:
        logger.warning("tmux_stdin_script_refused", verb=args[0] if args else "", error=str(exc))
        return 1, b"", str(exc).encode("utf-8")
    return await run_tmux(*STDIN_SCRIPT_ARGS, stdin_bytes=script, check=check)


def loggable_command(tokens: Sequence[str]) -> str:
    """A command as one log string, with every secret-named value redacted.

    Description: a ``set-environment`` value and a ``-e KEY=VALUE`` value
      whose variable NAME is secret-shaped (``debug_trace.is_secret_name``:
      token, secret, key, password ...) are replaced by
      ``debug_trace.fingerprint`` (length and an 8-hex hash). Everything
      else is kept, so the line still answers which command failed.

    Args:
        tokens: one command (or a ``;`` batch) as argv words.

    Returns:
        str: the words joined by spaces.

    Example:
        >>> loggable_command(["set-environment", "-t", "s", "CLOUDECODE_HOOK_TOKEN", "abc"])
        'set-environment -t s CLOUDECODE_HOOK_TOKEN len=3 fp=ba7816bf'
    """
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
