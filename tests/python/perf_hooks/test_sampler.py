
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_prof_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_prof_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.perf_hooks import call_counter, sampler  # noqa: E402
from src.core.perf_hooks.thread_cpu import read_thread_cpu  # noqa: E402

DARWIN = sys.platform == "darwin"


def _burn_marker(stop: threading.Event) -> None:
    while not stop.is_set():
        sum(i * i for i in range(2000))


def _parked_marker(stop: threading.Event) -> None:
    stop.wait()


def _spawn_marker(stop: threading.Event, folder: str) -> None:
    while not stop.is_set():
        subprocess.run(["true", "probe-verb"], check=False)
        os.listdir(folder)
        stop.wait(0.1)


@pytest.fixture
def workload():
    stop = threading.Event()
    folder = tempfile.mkdtemp(prefix="cc_prof_dir_")
    threads = [
        threading.Thread(target=_burn_marker, args=(stop,), name="burner-1"),
        threading.Thread(target=_parked_marker, args=(stop,), name="parked-1"),
        threading.Thread(target=_spawn_marker, args=(stop, folder), name="spawner-1"),
    ]
    for t in threads:
        t.start()
    yield stop
    stop.set()
    for t in threads:
        t.join(5)


@pytest.mark.skipif(not DARWIN, reason="per-thread CPU is read through Mach")
def test_thread_cpu_reads_this_thread():
    cpu = read_thread_cpu()
    assert cpu is not None and threading.get_native_id() in cpu
    before = cpu[threading.get_native_id()].seconds
    assert cpu[threading.get_native_id()].running
    t0 = time.process_time()
    while time.process_time() - t0 < 0.05:
        pass
    assert read_thread_cpu()[threading.get_native_id()].seconds > before


@pytest.mark.skipif(not DARWIN, reason="CPU weighting needs the Mach read")
def test_profile_charges_cpu_to_the_burning_stack_and_counts_calls(workload):
    result = sampler.run_profile(sampler.ProfileRequest(seconds=1.5, hz=100, top=10))
    workload.set()
    assert result["weight_unit"] == "cpu_seconds"
    threads = {row["thread"]: row for row in result["threads"]}
    assert threads["burner-*"]["cpu_seconds"] > 0.5
    assert threads.get("parked-*", {"cpu_seconds": 0})["cpu_seconds"] < 0.05
    top_stack = result["stacks"][0]
    assert top_stack["thread"] == "burner-*"
    assert any("_burn_marker" in f for f in top_stack["frames_leaf_first"]), top_stack
    assert all(row["thread"] != "parked-*" for row in result["stacks"])
    launches = result["calls"]["subprocess.Popen"]
    assert launches and launches[0]["detail"] == "true probe-verb"
    assert launches[0]["thread"] == "spawner-*"
    reads = result["calls"]["os.listdir"]
    assert reads and "_spawn_marker" in reads[0]["caller"]
    assert result["process_cpu_seconds"] >= threads["burner-*"]["cpu_seconds"] * 0.9


def test_counter_is_off_outside_a_window():
    call_counter.start()
    call_counter.stop(1.0)
    subprocess.run(["true"], check=False)
    os.listdir(".")
    call_counter.start()
    out = call_counter.stop(1.0)
    assert all(row["count"] == 0 for row in out["totals"])


def test_one_profile_at_a_time():
    async def both():
        first = asyncio.ensure_future(sampler.profile(sampler.ProfileRequest(seconds=1.0, hz=20)))
        await asyncio.sleep(0.2)
        with pytest.raises(sampler.ProfileBusyError):
            await sampler.profile(sampler.ProfileRequest(seconds=1.0, hz=20))
        return await first

    result = asyncio.run(both())
    assert result["ticks"] > 0 and 0.9 < result["seconds"] < 1.5


def test_launch_detail_masks_data_words():
    detail = call_counter._detail("subprocess.Popen", ("tmux", ["tmux", "-L", "/a/sock", "KEY=v", "capture-pane"], None, None))
    assert detail == "tmux -L * * capture-pane"


@pytest.mark.asyncio
async def test_mcp_tool_adapts_the_route(monkeypatch):
    from src.core.mcp import tools
    from src.core.mcp.caller import AgentCaller

    seen = {}

    async def fake_profile(request):
        seen["request"] = request
        return {"threads": [{"thread": "MainThread", "cpu_seconds": 0.1}], "access_token": "x"}

    monkeypatch.setattr(sampler, "profile", fake_profile)
    assert "perf_profile" in {t["name"] for t in tools.tool_definitions()}
    res = await tools.call_tool(None, AgentCaller(session_id="ses_test", tmux_name="carnivore_test", current_session_id="ses_test"), "perf_profile", {"seconds": 3})
    payload = json.loads(res["content"][0]["text"])
    assert seen["request"].seconds == 3 and payload["threads"][0]["thread"] == "MainThread"
    assert "access_token" not in payload
    bad = await tools.call_tool(None, AgentCaller(session_id="ses_test", tmux_name="carnivore_test", current_session_id="ses_test"), "perf_profile", {"seconds": 600})
    assert bad.get("isError")


def _frames(*leaf_first):
    from types import SimpleNamespace

    frame = None
    for filename, func in reversed(leaf_first):
        frame = SimpleNamespace(f_code=SimpleNamespace(co_filename=filename, co_name=func),
                                f_lineno=1, f_back=frame)
    return frame


class _Unwalkable:

    @property
    def f_code(self):
        raise AssertionError("an idle thread's stack was walked")


def test_charge_walks_no_stack_for_a_thread_that_burned_nothing():
    from src.core.perf_hooks.thread_cpu import ThreadCpu

    prev, now = {7: ThreadCpu(1.0, False)}, {7: ThreadCpu(1.0, False)}
    assert sampler._charge(now, prev, 7, _Unwalkable()) == (None, ())


def test_charge_sends_cpu_burned_between_ticks_to_its_own_row_not_the_idle_stack():
    from src.core.perf_hooks.thread_cpu import ThreadCpu

    idle = _frames((os.path.join("x", "concurrent", "futures", "thread.py"), "_worker"),
                   ("threading.py", "run"))
    weight, stack = sampler._charge({7: ThreadCpu(1.25, False)}, {7: ThreadCpu(1.0, False)}, 7, idle)
    assert weight == pytest.approx(0.25) and stack == sampler.BETWEEN_SAMPLES


def test_charge_puts_cpu_on_the_stack_a_running_thread_is_in():
    from src.core.perf_hooks.thread_cpu import ThreadCpu

    busy = _frames(("/repo/src/core/x.py", "hot"), ("threading.py", "run"))
    weight, stack = sampler._charge({7: ThreadCpu(2.0, True)}, {7: ThreadCpu(1.5, True)}, 7, busy)
    assert weight == pytest.approx(0.5) and stack[0][1] == "hot"


def test_charge_never_mixes_a_sample_into_cpu_seconds_for_a_thread_the_kernel_did_not_name():
    from src.core.perf_hooks.thread_cpu import ThreadCpu

    cpu = {7: ThreadCpu(1.0, True)}
    assert sampler._charge(cpu, cpu, None, _Unwalkable()) == (None, ())
