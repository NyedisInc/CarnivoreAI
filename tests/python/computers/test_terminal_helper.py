
from __future__ import annotations

import os
import stat
import types

import pytest

from src.core.computers import join_helper, join_job, terminal_helper


def test_command_file_is_private_and_carries_no_secret(tmp_path) -> None:
    fed = tmp_path / "fed"
    path = terminal_helper.write_command(fed, terminal_helper.command_text("/v/py'x", "/srv/dir", "/fed/door-225fde27.sock"))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o700 and stat.S_IMODE(os.stat(fed).st_mode) == 0o700
    text = path.read_text()
    assert text.startswith("#!/bin/sh\nexec '/v/py'\\''x' -I -c ") and text.endswith("'/srv/dir' --attach --door '/fed/door-225fde27.sock'\n")
    assert [p.name for p in fed.iterdir()] == [terminal_helper.COMMAND_NAME]
    fed.chmod(0o777)
    with pytest.raises(OSError):
        terminal_helper.write_command(fed, "x")


@pytest.mark.asyncio
async def test_a_failed_open_ends_the_job_helper_not_started(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(join_helper, "fed_dir", lambda: tmp_path / "fed")
    seen = []

    async def refuse(path):
        seen.append(path)
        return False

    monkeypatch.setattr(terminal_helper, "_open_terminal", refuse)
    monkeypatch.setattr(terminal_helper.runtime, "active", lambda: types.SimpleNamespace(door=types.SimpleNamespace(path=str(tmp_path / "fed" / "door-225fde27.sock"))))
    job = join_job.JoinJob(state="waiting_relay", running=True)
    monkeypatch.setattr(join_job, "_job", job)
    assert await terminal_helper.open_attach(job, created=True) is False
    assert (job.state, job.error) == ("failed", "helper_not_started") and seen[0].name == terminal_helper.COMMAND_NAME
    assert await terminal_helper.open_attach(job, created=True) is False and len(seen) == 1
