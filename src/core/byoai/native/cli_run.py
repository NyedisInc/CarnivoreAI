
from __future__ import annotations

import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import structlog

from src.core.byoai.contracts import (
    ByoaiError, ByoaiUnreachable, ChatMessage, Connection, LoginExpired, NotConfigured, ProviderTimeout,
)
from src.core.provider_ledger import refresh_poke

logger = structlog.get_logger()

LOGIN_LABELS = frozenset({"invalid_grant", "not_logged_in", "logged_out", "unauthorized"})


_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\[\]-]{0,127}")
_TOOL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.*-]{0,127}(\([^\x00-\x1f]{0,256}\))?")


def check_model(model: Optional[str]) -> Optional[str]:
    if model is not None and not _MODEL_ID.fullmatch(model):
        raise ByoaiError("the model id has characters a CLI argument may not carry")
    return model


def check_tool_names(names: Tuple[str, ...]) -> Tuple[str, ...]:
    for name in names:
        if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name):
            raise ByoaiError("a tool name must look like Bash, Bash(git log:*) or mcp__server__tool")
    return tuple(names)


def check_choice(value: Optional[str], allowed: Tuple[str, ...], what: str) -> Optional[str]:
    if value is not None and value not in allowed:
        raise ByoaiError(f"{what} must be one of {', '.join(allowed)}")
    return value


def check_budget(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ByoaiError("max_budget_usd must be a number above zero")
    return value


def check_cwd(cwd: Optional[str]) -> Optional[str]:
    if cwd is not None and (not cwd.startswith("/") or re.search(r"[\x00-\x1f]", cwd)):
        raise ByoaiError("the working directory must be an absolute path")
    return cwd


def isolated(connection: Connection) -> bool:
    return not bool(connection.options.get("load_user_config"))

def render_prompt(messages: Tuple[ChatMessage, ...]) -> str:
    if len(messages) == 1 and messages[0].role == "user":
        return messages[0].content
    return "\n\n".join(f"{m.role}: {m.content}" for m in messages)


async def spawn(argv: List[str], env: dict, *, stdin: bytes, cwd: Optional[str], timeout: float,
                what: str) -> refresh_poke.ChildResult:
    """Run one CLI call through the ledger's spawn and return its captured result.

    Inputs: argv, env (the allow-listed environment), stdin (the prompt bytes), cwd,
      timeout (seconds), what (a log label such as ``claude``).
    Raises: ByoaiUnreachable (binary missing or not runnable), ProviderTimeout (the
      process group was stopped), ByoaiError (the working directory is not a directory).
    Example: result = await spawn(argv, env, stdin=b"say ok", cwd=None, timeout=60.0, what="claude")
    """
    if cwd is not None and not os.path.isdir(cwd):
        raise ByoaiError("the working directory does not exist")
    result = await refresh_poke.run_child(argv, env, timeout=timeout, stdin=stdin, cwd=cwd)
    if not result.ran:
        raise ByoaiUnreachable(f"{what} could not be started ({result.spawn_error})")
    if result.timed_out:
        logger.warning("byoai_cli_timed_out", cli=what, timeout=timeout)
        raise ProviderTimeout(f"{what} did not finish in {timeout:g}s")
    logger.info("byoai_cli_ran", cli=what, exit_code=result.exit_code,
                stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr))
    return result


def failure(what: str, result: refresh_poke.ChildResult) -> ByoaiError:
    labels = refresh_poke.classify_output(result.stdout, result.stderr)
    if LOGIN_LABELS.intersection(labels):
        return LoginExpired(f"{what} reports its login is not usable")
    return ByoaiError(f"{what} exited {result.exit_code} ({', '.join(labels) or 'no signal'})")


def profile_dir(provider: str, account_id: str) -> Optional[str]:
    if not account_id:
        return None
    from src.config import settings
    from src.core.provider_ledger import accounts_store
    from src.core.provider_ledger.login_command import login_profile_dir

    try:
        accounts = accounts_store.list_accounts(Path(settings.auth_config_file))
    except (OSError, ValueError):
        accounts = []
    for account in accounts:
        if account.id == account_id and account.provider == provider:
            return login_profile_dir(account)
    raise NotConfigured(f"no {provider} account named {account_id!r} in the provider ledger")


@contextmanager
def private_file(text: str, suffix: str = ".txt") -> Iterator[str]:
    fd, path = tempfile.mkstemp(prefix="byoai-", suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        yield path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
