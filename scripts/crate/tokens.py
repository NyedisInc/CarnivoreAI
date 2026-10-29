
from __future__ import annotations

import os
import subprocess
from typing import Callable, Mapping, Optional, Protocol, Sequence

from scripts.crate.errors import AuthError

OP_TIMEOUT_S = 60.0


class TokenSource(Protocol):

    def token(self) -> str:
        ...


class StaticToken:

    def __init__(self, value: str) -> None:
        self._value = value

    def token(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "StaticToken(<hidden>)"


class EnvToken:

    def __init__(self, name: str, environ: Optional[Mapping[str, str]] = None) -> None:
        self.name = name
        self._environ = os.environ if environ is None else environ

    def token(self) -> str:
        value = (self._environ.get(self.name) or "").strip()
        if not value:
            raise AuthError(f"environment variable {self.name} is not set or is empty")
        return value

    def __repr__(self) -> str:
        return f"EnvToken({self.name!r})"


Runner = Callable[[Sequence[str], float], "subprocess.CompletedProcess[str]"]


def _run_op(argv: Sequence[str], timeout: float) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)


class OnePasswordToken:

    def __init__(self, reference: str, runner: Runner = _run_op) -> None:
        if not reference.startswith("op://"):
            raise AuthError("a 1Password reference starts with op://")
        self.reference = reference
        self._runner = runner

    def token(self) -> str:
        try:
            done = self._runner(["op", "read", "--no-newline", self.reference], OP_TIMEOUT_S)
        except FileNotFoundError as exc:
            raise AuthError("the 1Password CLI (op) is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise AuthError(f"op read timed out after {OP_TIMEOUT_S:.0f}s (is 1Password locked?)") from exc
        value = (done.stdout or "").strip()
        if done.returncode != 0 or not value:
            raise AuthError(f"op could not read {self.reference} (exit {done.returncode})")
        return value

    def __repr__(self) -> str:
        return f"OnePasswordToken({self.reference!r})"
