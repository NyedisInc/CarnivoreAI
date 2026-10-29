
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Dict, List

import pytest

from src.core.hosts import ssh_exec, ssh_forward
from src.core.hosts.ssh_exec import ExecResult, SshDestination


class FakeMaster:

    def __init__(self) -> None:
        self.held: Dict[str, asyncio.AbstractServer] = {}
        self.verbs: List[str] = []

    async def run(self, argv) -> None:
        verb, spec = argv[argv.index("-O") + 1], argv[argv.index("-O") + 3]
        self.verbs.append(verb)
        path = spec.split(":", 1)[0]
        if verb == "forward" and spec not in self.held:
            self.held[spec] = await asyncio.start_unix_server(lambda r, w: w.close(), path=path)
        elif verb == "cancel" and spec in self.held:
            self.held.pop(spec).close()


def _result() -> ExecResult:
    return ExecResult(returncode=0, stdout=b"", stderr=b"")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["tcp", "unix"])
async def test_redial_over_a_surviving_master_restores_the_socket(monkeypatch, kind):
    master = FakeMaster()

    async def fake_run(argv, **kw):
        await master.run(argv)
        return _result()

    monkeypatch.setattr(ssh_exec, "run_process", fake_run)
    directory = tempfile.mkdtemp(prefix="rd")
    out = os.path.join(directory, "out.sock")
    dest = SshDestination("studio")

    async def dial() -> str:
        if kind == "tcp":
            return await ssh_forward.forward_local(dest, "/x/cp", out, "127.0.0.1", 8000)
        return await ssh_forward.forward_local_unix(dest, "/x/cp", out, "/far/pair.sock")

    try:
        assert await dial() == out
        assert await dial() == out
    finally:
        for server in master.held.values():
            server.close()
        if os.path.lexists(out):
            os.unlink(out)
        os.rmdir(directory)
