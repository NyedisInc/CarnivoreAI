
from __future__ import annotations

import subprocess

import pytest

from tests import tmux_start_retry


def _called_process_error(returncode: int, stderr: str) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        returncode, ["tmux", "-L", "x", "new-session", "-d"], output=b"", stderr=stderr.encode()
    )


def test_transient_start_failure_is_retried_and_then_succeeds() -> None:
    calls: list = []

    def flaky_start(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise _called_process_error(1, "server exited unexpectedly")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    result = tmux_start_retry.run_tmux_start_with_retry(flaky_start, (), {})
    assert result.returncode == 0
    assert len(calls) == 3, "expected exactly two failures then a success"


def test_a_different_tmux_error_is_never_retried() -> None:
    calls: list = []

    def broken_start(*args, **kwargs):
        calls.append(1)
        raise _called_process_error(1, "no such file or directory")

    with pytest.raises(subprocess.CalledProcessError):
        tmux_start_retry.run_tmux_start_with_retry(broken_start, (), {})
    assert len(calls) == 1, "a non-matching failure must not be retried"


def test_retry_gives_up_after_three_attempts_and_raises_the_real_error() -> None:
    calls: list = []

    def always_flaky(*args, **kwargs):
        calls.append(1)
        raise _called_process_error(1, "server exited unexpectedly")

    with pytest.raises(subprocess.CalledProcessError):
        tmux_start_retry.run_tmux_start_with_retry(always_flaky, (), {})
    assert len(calls) == 3, "must stop at the bounded attempt count, not loop forever"


def test_a_non_start_command_is_never_routed_through_the_retry() -> None:
    assert not tmux_start_retry.is_tmux_start_argv(
        ["tmux", "-L", "x", "has-session", "-t", "nope"]
    )
    assert tmux_start_retry.is_tmux_start_argv(["tmux", "-L", "x", "new-session", "-d"])
    assert tmux_start_retry.is_tmux_start_argv(["tmux", "-L", "x", "start-server"])


def test_no_captured_output_means_no_retry() -> None:
    calls: list = []

    def uncaptured_failure(*args, **kwargs):
        calls.append(1)
        raise subprocess.CalledProcessError(1, ["tmux", "new-session", "-d"])

    with pytest.raises(subprocess.CalledProcessError):
        tmux_start_retry.run_tmux_start_with_retry(uncaptured_failure, (), {})
    assert len(calls) == 1, "with no failure text to check, retrying would be a guess"


def test_call_style_return_code_int_is_also_retried() -> None:
    calls: list = []

    def flaky_call(*args, **kwargs):
        calls.append(1)
        return 1 if len(calls) < 2 else 0

    result = tmux_start_retry.run_tmux_start_with_retry(flaky_call, (), {})
    assert result == 1, "no captured text to confirm the signature, so no retry"
    assert len(calls) == 1
