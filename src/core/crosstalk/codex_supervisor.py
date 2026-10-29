
from __future__ import annotations

import asyncio
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import websockets


async def _bootstrap_thread(path: Path, model: str | None, name: str,
                            policy: dict | None = None) -> str:
    from src.core.crosstalk.delivery.codex_appserver import _request

    async with websockets.unix_connect(str(path), open_timeout=3) as ws:
        await _request(ws, "initialize", {"clientInfo": {"name": "carnivore-codex-launch", "version": "1.0.0"},
                                          "capabilities": {}}, 1)
        await ws.send(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        params = {"cwd": os.getcwd(), "threadSource": "user"}
        if model:
            params["model"] = model
        if policy:
            params.update(policy)
        started = await _request(ws, "thread/start", params, 2)
        thread_id = str((started.get("thread") or {}).get("id") or "")
        if str(uuid.UUID(thread_id)) != thread_id:
            raise ValueError("app-server returned an invalid thread id")
        await _request(ws, "thread/name/set", {"threadId": thread_id, "name": name}, 3)
        return thread_id


async def _prepare_existing_thread(path: Path, command: str, source_id: str,
                                   model: str | None, policy: dict, cwd: str | None = None) -> str:
    from src.core.crosstalk.delivery.codex_appserver import _request

    if str(uuid.UUID(source_id)) != source_id:
        raise ValueError("invalid source thread id")
    async with websockets.unix_connect(str(path), open_timeout=3) as ws:
        await _request(ws, "initialize", {"clientInfo": {"name": "carnivore-codex-launch", "version": "1.0.0"},
                                          "capabilities": {}}, 1)
        await ws.send(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        params = {"threadId": source_id, "excludeTurns": True, **policy}
        if model:
            params["model"] = model
        if cwd:
            params["cwd"] = cwd
        result = await _request(ws, "thread/resume" if command == "resume" else "thread/fork", params, 2)
        target_id = str((result.get("thread") or {}).get("id") or "")
        if str(uuid.UUID(target_id)) != target_id or (command == "resume" and target_id != source_id):
            raise ValueError("app-server returned an invalid thread id")
        return target_id


def _requested_cwd(args: list[str]) -> str | None:
    for index, arg in enumerate(args):
        if arg in ("--cd", "-C") and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--cd="):
            return arg.split("=", 1)[1]
    return None


def _stop(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=3)


def run(spec: dict) -> int:
    from src.core.crosstalk.delivery.codex_appserver import socket_path

    session_id = os.environ.get("CLOUDECODE_SESSION_ID", "")
    path = socket_path(session_id)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    directory = path.parent.stat()
    if directory.st_uid != os.getuid() or directory.st_mode & 0o077:
        return 1
    if path.exists():
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(path))
            except OSError:
                path.unlink(missing_ok=True)
            else:
                return 1
    url = "unix://" + str(path)
    server = None
    tui = None
    socket_inode = None
    stopped = False
    terminal_fd = sys.stdin.fileno()
    foreground_group = os.tcgetpgrp(terminal_fd)
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)

    def interrupt(signum: int, frame: object) -> None:
        nonlocal stopped
        del signum, frame
        stopped = True

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupt)
    try:
        server = subprocess.Popen(["codex", *spec["server"], "app-server", "--listen", url], process_group=0)
        deadline = time.monotonic() + 8
        while not path.exists() and server.poll() is None and time.monotonic() < deadline and not stopped:
            time.sleep(0.05)
        if not path.exists() or stopped:
            return server.poll() or 1
        socket_inode = path.stat().st_ino
        tui_args = list(spec["tui"])
        if spec.get("bootstrap") is not None:
            try:
                thread_id = asyncio.run(_bootstrap_thread(
                    path, spec["bootstrap"]["model"], f"Carnivore {session_id}", spec.get("policy")))
            except (OSError, TimeoutError, websockets.WebSocketException, ValueError, KeyError, RuntimeError) as exc:
                print(f"Codex thread startup failed: {type(exc).__name__}", file=sys.stderr)
                return 1
            tui_args = ["resume", thread_id, *tui_args]
        elif spec.get("policy") and len(tui_args) >= 2 and tui_args[0] in ("resume", "fork"):
            try:
                thread_id = asyncio.run(_prepare_existing_thread(
                    path, tui_args[0], tui_args[1], spec.get("model"), spec["policy"],
                    _requested_cwd(tui_args[2:]) or (os.getcwd() if tui_args[0] == "fork" else None)))
            except (OSError, TimeoutError, websockets.WebSocketException, ValueError, KeyError, RuntimeError) as exc:
                print(f"Codex thread posture failed: {type(exc).__name__}", file=sys.stderr)
                return 1
            tui_args = ["resume", thread_id, *tui_args[2:]]
        tui = subprocess.Popen(["codex", "--remote", url, *tui_args], process_group=0)
        os.tcsetpgrp(terminal_fd, tui.pid)
        watcher = select.poll()
        watcher.register(terminal_fd, select.POLLHUP | select.POLLERR)
        while not stopped and tui.poll() is None and server.poll() is None:
            if watcher.poll(250):
                stopped = True
        return tui.poll() if tui.poll() is not None else 1
    finally:
        try:
            os.tcsetpgrp(terminal_fd, foreground_group)
        except OSError:
            pass
        _stop(tui)
        _stop(server)
        if socket_inode is not None:
            try:
                if path.stat().st_ino == socket_inode:
                    path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    sys.exit(run(json.loads(sys.argv[1])))
