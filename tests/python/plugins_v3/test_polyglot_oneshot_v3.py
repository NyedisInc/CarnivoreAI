
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import List

import pytest

from src.plugins.runtime import frames, sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.process import PluginProcess, PluginSpec, ProcessEnded


def _can_run_darwin_sandbox() -> bool:
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return False
    try:
        sandbox.find_interpreter()
        return True
    except sandbox.SandboxUnavailable:
        return False


DARWIN_SANDBOX = _can_run_darwin_sandbox()


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
async def test_oneshot_hardening_exit_flag_overflow_and_escape(tmp_path: Path) -> None:
    disp = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"o" * 32))
    rt_dir = sandbox.copy_runtime(tmp_path / "state", "9.9.9")
    interp = sandbox.find_interpreter()
    sroot = sandbox.stdlib_root(interp)

    def _make_proc(pid: str, code: Path, run_cmd: tuple[str, ...]) -> PluginProcess:
        data_dir = tmp_path / "data" / pid
        (data_dir / "files").mkdir(parents=True, exist_ok=True)
        ctx = PluginContext(plugin_id=pid, install_key=pid, data_dir=data_dir, granted=frozenset())
        spec = PluginSpec(ctx=ctx, code_dir=code, entry="main", run_cmd=run_cmd, run_mode="oneshot")
        layout = sandbox.Layout(
            interpreter=interp,
            stdlib_root=sroot,
            runtime_dir=rt_dir,
            code_dir=Path(os.path.realpath(code)),
            data_dir=Path(os.path.realpath(data_dir)),
            runtime_kind="python",
            run_mode="oneshot",
        )
        return PluginProcess(spec, layout, disp, "9.9.9", lambda _why: asyncio.sleep(0))

    c_err = tmp_path / "code" / "os_err"
    c_err.mkdir(parents=True)
    (c_err / "main.py").write_text("import sys\nprint('Traceback (most recent call last): boom')\nsys.exit(2)\n", encoding="utf-8")
    p_err = _make_proc("oserr", c_err, ("python3", "main.py"))
    await p_err.start()
    with pytest.raises(ProcessEnded) as exc_err:
        await p_err.request("route.handle", {"route": "x"})
    assert exc_err.value.reason == "plugin_error"
    assert exc_err.value.code == frames.INTERNAL_ERROR
    assert exc_err.value.message == "oneshot_exit_2"

    c_flag = tmp_path / "code" / "os_flag"
    c_flag.mkdir(parents=True)
    (c_flag / "main.py").write_text("import json, sys\nprint(json.dumps({'argv': sys.argv[1:]}))\n", encoding="utf-8")
    p_flag = _make_proc("osflag", c_flag, ("python3", "-u", "main.py", "--hello"))
    await p_flag.start()
    res_flag = await p_flag.request("tools/call", {"name": "echo", "arguments": {}})
    assert json.loads(res_flag["content"][0]["text"]) == {"argv": ["--hello"]}

    c_big = tmp_path / "code" / "os_big"
    c_big.mkdir(parents=True)
    (c_big / "main.py").write_text("import sys\nsys.stdout.write('A' * (1024 * 1024 + 256))\nsys.stdout.flush()\n", encoding="utf-8")
    p_big = _make_proc("osbig", c_big, ("python3", "main.py"))
    await p_big.start()
    with pytest.raises(ProcessEnded) as exc_big:
        await p_big.request("route.handle", {"route": "x"})
    assert exc_big.value.reason == "violation:frame_too_large"

    c_esc = tmp_path / "code" / "os_esc"
    c_esc.mkdir(parents=True)
    (tmp_path / "code" / "outside.py").write_text("print('escaped')\n", encoding="utf-8")
    p_esc = _make_proc("osesc", c_esc, ("python3", "../outside.py"))
    await p_esc.start()
    with pytest.raises(ProcessEnded) as exc_esc:
        await p_esc.request("route.handle", {"route": "x"})
    assert exc_esc.value.reason == "violation:script_outside_code_dir"


async def _assert_pid_reaped(pid: int, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            pytest.fail(f"process {pid} still alive after {timeout:.2f}s")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
@pytest.mark.parametrize(
    ("stream", "byte_count", "expected_reason"),
    [
        ("stdout", 2 * 1024 * 1024, "violation:frame_too_large"),
        ("stderr", 6 * 1024 * 1024, "violation:call_output_exceeded"),
    ],
)
async def test_oneshot_flood_kills_process_group_without_deadlock_or_orphans(
    tmp_path: Path, stream: str, byte_count: int, expected_reason: str
) -> None:
    disp = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"f" * 32))
    rt_dir = sandbox.copy_runtime(tmp_path / "state", "9.9.9")
    interp = sandbox.find_interpreter()
    sroot = sandbox.stdlib_root(interp)

    pid = f"flood_{stream}"
    code = tmp_path / "code" / pid
    code.mkdir(parents=True)
    data_dir = tmp_path / "data" / pid
    files_dir = data_dir / "files"
    files_dir.mkdir(parents=True)

    (code / "main.py").write_text(
        f"""
import os
import sys
import time

child = os.fork()
if child == 0:
    time.sleep(30)
    os._exit(0)

pid_file = os.path.join(os.environ["CARNIVORE_DATA_DIR"], "grandchild.pid")
with open(pid_file, "w", encoding="utf-8") as fh:
    fh.write(str(child))
    fh.flush()

chunk = "X" * 65536
remaining = {byte_count}
target = sys.{stream}
while remaining > 0:
    n = min(len(chunk), remaining)
    target.write(chunk[:n])
    remaining -= n
target.flush()
time.sleep(5)
""",
        encoding="utf-8",
    )

    ctx = PluginContext(plugin_id=pid, install_key=pid, data_dir=data_dir, granted=frozenset())
    spec = PluginSpec(ctx=ctx, code_dir=code, entry="main", run_cmd=("python3", "main.py"), run_mode="oneshot")
    layout = sandbox.Layout(
        interpreter=interp,
        stdlib_root=sroot,
        runtime_dir=rt_dir,
        code_dir=Path(os.path.realpath(code)),
        data_dir=Path(os.path.realpath(data_dir)),
        runtime_kind="python",
        run_mode="oneshot",
        plugin_id=pid,
        allow_fork=True,
    )
    proc = PluginProcess(spec, layout, disp, "9.9.9", lambda _why: asyncio.sleep(0))
    await proc.start()

    t0 = time.monotonic()
    with pytest.raises(ProcessEnded) as exc:
        await proc.request("route.handle", {"route": "x"}, timeout=5.0)
    elapsed = time.monotonic() - t0

    assert exc.value.reason == expected_reason
    assert elapsed < 1.0, f"{stream} flood took {elapsed:.3f}s"

    grandchild_pid = int((files_dir / "grandchild.pid").read_text(encoding="utf-8").strip())
    await _assert_pid_reaped(grandchild_pid)


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
@pytest.mark.parametrize("parent_exits_early_mode", ["timeout_open_pipes", "normal_return_lingering_grandchild"])
async def test_oneshot_kills_grandchild_when_direct_child_exits_early(
    tmp_path: Path, parent_exits_early_mode: str
) -> None:
    disp = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"g" * 32))
    rt_dir = sandbox.copy_runtime(tmp_path / "state", "9.9.9")
    interp = sandbox.find_interpreter()
    sroot = sandbox.stdlib_root(interp)

    pid = f"orphan_{parent_exits_early_mode}"
    code = tmp_path / "code" / pid
    code.mkdir(parents=True)
    data_dir = tmp_path / "data" / pid
    files_dir = data_dir / "files"
    files_dir.mkdir(parents=True)

    if parent_exits_early_mode == "timeout_open_pipes":
        child_script = """
import os
import time

child = os.fork()
if child == 0:
    time.sleep(30)
    os._exit(0)

pid_file = os.path.join(os.environ["CARNIVORE_DATA_DIR"], "grandchild.pid")
with open(pid_file, "w", encoding="utf-8") as fh:
    fh.write(str(child))
    fh.flush()

os._exit(0)
"""
    else:
        child_script = """
import json
import os
import sys
import time

child = os.fork()
if child == 0:
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    if devnull > 2:
        os.close(devnull)
    time.sleep(30)
    os._exit(0)

pid_file = os.path.join(os.environ["CARNIVORE_DATA_DIR"], "grandchild.pid")
with open(pid_file, "w", encoding="utf-8") as fh:
    fh.write(str(child))
    fh.flush()

sys.stdout.write(json.dumps({"ok": True}) + "\\n")
sys.stdout.flush()
os._exit(0)
"""

    (code / "main.py").write_text(child_script, encoding="utf-8")
    ctx = PluginContext(plugin_id=pid, install_key=pid, data_dir=data_dir, granted=frozenset())
    spec = PluginSpec(ctx=ctx, code_dir=code, entry="main", run_cmd=("python3", "main.py"), run_mode="oneshot")
    layout = sandbox.Layout(
        interpreter=interp,
        stdlib_root=sroot,
        runtime_dir=rt_dir,
        code_dir=Path(os.path.realpath(code)),
        data_dir=Path(os.path.realpath(data_dir)),
        runtime_kind="python",
        run_mode="oneshot",
        plugin_id=pid,
        allow_fork=True,
    )
    proc = PluginProcess(spec, layout, disp, "9.9.9", lambda _why: asyncio.sleep(0))
    await proc.start()

    if parent_exits_early_mode == "timeout_open_pipes":
        with pytest.raises(asyncio.TimeoutError):
            await proc.request("route.handle", {"route": "x"}, timeout=0.4)
    else:
        res = await proc.request("route.handle", {"route": "x"}, timeout=2.0)
        assert res == {"status": 200, "body": {"ok": True}}

    grandchild_pid = int((files_dir / "grandchild.pid").read_text(encoding="utf-8").strip())
    await _assert_pid_reaped(grandchild_pid)


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
@pytest.mark.parametrize(("action", "expected_reason"), [("kill", "killed"), ("stop", "disabled")])
async def test_oneshot_kill_and_stop_abort_inflight_request_and_reap_group(
    tmp_path: Path, action: str, expected_reason: str
) -> None:
    disp = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"h" * 32))
    rt_dir = sandbox.copy_runtime(tmp_path / "state", "9.9.9")
    interp = sandbox.find_interpreter()
    sroot = sandbox.stdlib_root(interp)

    pid = f"inflight_{action}"
    code = tmp_path / "code" / pid
    code.mkdir(parents=True)
    data_dir = tmp_path / "data" / pid
    files_dir = data_dir / "files"
    files_dir.mkdir(parents=True)

    (code / "main.py").write_text(
        """
import os
import time

child = os.fork()
if child == 0:
    time.sleep(30)
    os._exit(0)

pid_file = os.path.join(os.environ["CARNIVORE_DATA_DIR"], "pids.txt")
with open(pid_file, "w", encoding="utf-8") as fh:
    fh.write(f"{os.getpid()},{child}")
    fh.flush()

time.sleep(30)
""",
        encoding="utf-8",
    )

    exits: List[str] = []

    async def _on_exit(reason: str) -> None:
        exits.append(reason)

    ctx = PluginContext(plugin_id=pid, install_key=pid, data_dir=data_dir, granted=frozenset())
    spec = PluginSpec(ctx=ctx, code_dir=code, entry="main", run_cmd=("python3", "main.py"), run_mode="oneshot")
    layout = sandbox.Layout(
        interpreter=interp,
        stdlib_root=sroot,
        runtime_dir=rt_dir,
        code_dir=Path(os.path.realpath(code)),
        data_dir=Path(os.path.realpath(data_dir)),
        runtime_kind="python",
        run_mode="oneshot",
        plugin_id=pid,
        allow_fork=True,
    )
    proc = PluginProcess(spec, layout, disp, "9.9.9", _on_exit)
    await proc.start()

    req_task = asyncio.create_task(proc.request("route.handle", {"route": "x"}, timeout=30.0))
    pids_file = files_dir / "pids.txt"
    deadline = time.monotonic() + 5.0
    while not pids_file.exists() or "," not in pids_file.read_text(encoding="utf-8"):
        if req_task.done():
            await req_task
            pytest.fail("oneshot request exited prematurely before writing pids.txt")
        if time.monotonic() >= deadline:
            req_task.cancel()
            await asyncio.gather(req_task, return_exceptions=True)
            pytest.fail("timed out waiting for inflight oneshot child to write pids.txt")
        await asyncio.sleep(0.01)

    child_pid_s, grandchild_pid_s = pids_file.read_text(encoding="utf-8").strip().split(",", 1)
    child_pid, grandchild_pid = int(child_pid_s), int(grandchild_pid_s)

    t0 = time.monotonic()
    if action == "kill":
        await proc.kill(expected_reason)
    else:
        await proc.stop(expected_reason)
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"{action} took {elapsed:.3f}s"
    assert proc.busy == 0
    assert exits == [expected_reason]
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)

    with pytest.raises(ProcessEnded) as exc:
        await req_task
    assert exc.value.reason == expected_reason
