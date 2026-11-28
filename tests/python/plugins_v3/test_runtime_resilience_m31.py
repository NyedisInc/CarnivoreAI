
from __future__ import annotations

import asyncio
import compileall
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvloop

from src.plugins.runtime import sandbox, socket_server
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.process import PluginProcess, PluginSpec, ProcessEnded


def _make_proc(tmp_path: Path, plugin_id: str = "resil") -> PluginProcess:
    code = tmp_path / "code"
    data = tmp_path / "data"
    code.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    ctx = PluginContext(plugin_id=plugin_id, install_key="k-" + plugin_id, data_dir=data, granted=frozenset())
    spec = PluginSpec(ctx=ctx, code_dir=code, entry="main")
    layout = sandbox.Layout(tmp_path / "py", tmp_path / "fw", tmp_path / "rt", code, data)
    disp = HostDispatcher(HostServices(activity=lambda _row: None), OwnerTokens(b"r" * 32))

    async def _on_exit(_reason: str) -> None:
        return None

    return PluginProcess(spec, layout, disp, "1.0.0", _on_exit)


def test_process_send_closing_and_request_cleans_waiter(tmp_path: Path) -> None:
    proc = _make_proc(tmp_path)

    class _ClosingStdin:
        def is_closing(self) -> bool:
            return True

        def write(self, _data: bytes) -> None:
            raise AssertionError("write must not run when stdin.is_closing() is True")

    proc._proc = SimpleNamespace(stdin=_ClosingStdin(), returncode=None, pid=None)  # type: ignore[assignment]

    async def _run() -> None:
        with pytest.raises(ProcessEnded) as exc:
            await proc.request("ping", {})
        assert exc.value.reason == "exited"
        assert proc._waiting == {}
        assert proc._guard._outstanding == set()

    asyncio.run(_run())


def test_process_send_and_stop_survive_closed_uvloop_transport(tmp_path: Path) -> None:
    proc = _make_proc(tmp_path, "uvtest")
    sub_holder: list[asyncio.subprocess.Process] = []
    uv_loop = uvloop.new_event_loop()

    async def _spawn_on_uvloop() -> None:
        sub = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys, time; sys.stdin.read(); time.sleep(5)",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        sub_holder.append(sub)

    try:
        uv_loop.run_until_complete(_spawn_on_uvloop())
        sub = sub_holder[0]
        proc._proc = sub
        uv_loop.close()

        async def _check_second_loop() -> None:
            with pytest.raises(ProcessEnded) as exc:
                await proc._send(b"{}\n")
            assert exc.value.reason == "exited"
            await proc.stop("shutdown")
            assert proc.ended == "shutdown"

        asyncio.run(_check_second_loop())
    finally:
        if not uv_loop.is_closed():
            uv_loop.close()
        if sub_holder and sub_holder[0].returncode is None:
            try:
                os.killpg(sub_holder[0].pid, 9)
            except OSError:
                pass


def test_runner_still_refuses_planted_orphan_pyc_under_sandbox_command(tmp_path: Path) -> None:
    real_tmp = Path(os.path.realpath(tmp_path))
    rt = real_tmp / "rt"
    code = real_tmp / "code"
    data = real_tmp / "data"
    rt.mkdir(parents=True)
    code.mkdir(parents=True)
    (data / "files").mkdir(parents=True)

    shutil.copy2(sandbox.RUNNER_SOURCE, rt / "runner.py")
    shutil.copytree(sandbox.SDK_SOURCE, rt / sandbox.SDK_PACKAGE)

    helper_py = code / "planted_mod.py"
    helper_py.write_text("SECRET_MARKER = 'planted'\n", encoding="utf-8")
    assert compileall.compile_file(str(helper_py), quiet=1)
    helper_py.unlink()
    assert list((code / "__pycache__").glob("planted_mod*.pyc"))

    (code / "main.py").write_text(
        "import planted_mod\nplugin = None\n",
        encoding="utf-8",
    )

    layout = sandbox.Layout(
        interpreter=Path(sys.executable),
        stdlib_root=Path(sys.prefix),
        runtime_dir=rt,
        code_dir=code,
        data_dir=data,
    )
    argv = sandbox.build_unrestricted_command(layout, "main", 1024 * 1024)
    assert f"pycache_prefix={rt / sandbox.NO_PYCACHE}" in argv

    res = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert res.returncode != 0
    assert "ModuleNotFoundError" in res.stderr
    assert "planted_mod" in res.stderr

    if sys.platform == "darwin":
        try:
            interp = sandbox.find_interpreter()
        except sandbox.SandboxUnavailable:
            return
        sb_layout = sandbox.Layout(
            interpreter=interp,
            stdlib_root=sandbox.stdlib_root(interp),
            runtime_dir=rt,
            code_dir=code,
            data_dir=data,
        )
        profile = sandbox.write_profile(sb_layout)
        sb_argv = sandbox.build_command(sb_layout, profile, "main", 1024 * 1024)
        sb_res = subprocess.run(sb_argv, capture_output=True, text=True, check=False, env=sandbox.allow_env(sb_layout))
        assert sb_res.returncode != 0
        assert "ModuleNotFoundError" in sb_res.stderr
        assert "planted_mod" in sb_res.stderr


def test_fallback_sockets_and_sweep_stale_are_isolated_by_state_dir(tmp_path: Path) -> None:
    deep_a = tmp_path / ("state_alpha_" * 10) / "a"
    deep_b = tmp_path / ("state_beta__" * 10) / "b"
    deep_a.mkdir(parents=True, exist_ok=True)
    deep_b.mkdir(parents=True, exist_ok=True)

    sock_a = socket_server.socket_path_for(deep_a, "inst-bash-rpc")
    sock_b = socket_server.socket_path_for(deep_b, "inst-bash-rpc")
    assert sock_a != sock_b
    assert len(os.fsencode(str(sock_a))) <= socket_server.SOCKET_PATH_MAX
    assert len(os.fsencode(str(sock_b))) <= socket_server.SOCKET_PATH_MAX

    bound_a = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound_b = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock_a.unlink(missing_ok=True)
        sock_b.unlink(missing_ok=True)
        bound_a.bind(str(sock_a))
        bound_b.bind(str(sock_b))

        removed = socket_server.PluginSocketManager.sweep_stale(deep_a)
        assert removed >= 1
        assert not sock_a.exists()
        assert sock_b.exists()
    finally:
        bound_a.close()
        bound_b.close()
        sock_a.unlink(missing_ok=True)
        sock_b.unlink(missing_ok=True)
