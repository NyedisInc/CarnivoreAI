
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time

import pytest
import websockets

from src.core.crosstalk.codex_supervisor import _bootstrap_thread, _prepare_existing_thread, _requested_cwd, _stop
from src.core.crosstalk.delivery.codex_appserver import _request


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is not installed")
def test_fresh_thread_persists_before_any_turn(tmp_path, monkeypatch):
    assert _requested_cwd(['--cd', '/tmp/target']) == '/tmp/target'
    assert _requested_cwd(['-C', '/tmp/target']) == '/tmp/target'
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(mode=0o700)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.chdir(work)
    with tempfile.TemporaryDirectory(prefix="cb-", dir="/tmp") as socket_dir:
        path = os.path.join(socket_dir, "app.sock")
        server = subprocess.Popen(["codex", "app-server", "--listen", "unix://" + path],
                                  env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  process_group=0)
        try:
            deadline = time.monotonic() + 8
            while not os.path.exists(path) and server.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert os.path.exists(path) and server.poll() is None
            thread_id = asyncio.run(_bootstrap_thread(path, None, "Carnivore bootstrap test"))

            async def resumed():
                async with websockets.unix_connect(str(path)) as ws:
                    await _request(ws, "initialize", {"clientInfo": {"name": "bootstrap-test", "version": "1.0.0"},
                                                      "capabilities": {}}, 1)
                    await ws.send(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
                    result = await _request(ws, "thread/resume", {"threadId": thread_id}, 2)
                    return result["thread"]

            thread = asyncio.run(resumed())
            assert thread["id"] == thread_id
            assert thread["turns"] == []
            policy = {"approvalPolicy": "never", "sandbox": "danger-full-access"}
            assert asyncio.run(_prepare_existing_thread(path, "resume", thread_id, None, policy)) == thread_id

            async def posture():
                async with websockets.unix_connect(str(path)) as ws:
                    await _request(ws, "initialize", {"clientInfo": {"name": "bootstrap-test", "version": "1.0.0"},
                                                      "capabilities": {}}, 1)
                    await ws.send(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
                    return await _request(ws, "thread/resume", {"threadId": thread_id}, 2)

            effective = asyncio.run(posture())
            assert effective["approvalPolicy"] == "never"
            assert effective["sandbox"]["type"] == "dangerFullAccess"
            with sqlite3.connect(codex_home / "state_5.sqlite") as db:
                assert db.execute("SELECT cwd, thread_source FROM threads WHERE id=?", (thread_id,)).fetchone() == (
                    str(work), "user")
        finally:
            _stop(server)
