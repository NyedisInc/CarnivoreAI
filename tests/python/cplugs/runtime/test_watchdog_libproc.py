
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from src.plugins.runtime import proc_usage, watchdog

DARWIN = sys.platform == "darwin"


def _ps_rss_bytes(pid: int) -> int:
    out = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True).stdout
    return int(out.split()[0]) * 1024


@pytest.fixture
def child():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    time.sleep(0.5)
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.skipif(not DARWIN, reason="libproc is macOS only")
def test_usage_of_forks_nothing_on_darwin(child, monkeypatch):
    calls = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or real(*a, **k))
    usage = watchdog.usage_of(child.pid)
    assert usage is not None and calls == []


@pytest.mark.skipif(not DARWIN, reason="libproc is macOS only")
def test_live_child_agrees_with_ps(child):
    usage = watchdog.usage_of(child.pid)
    assert usage is not None and usage.rss > 0 and usage.cpu >= 0.0
    ps_rss = _ps_rss_bytes(child.pid)
    assert abs(usage.rss - ps_rss) <= max(4 * 2**20, ps_rss // 10)


def test_gone_pid_is_none(child):
    child.kill()
    child.wait()
    assert watchdog.usage_of(child.pid) is None


@pytest.mark.skipif(not DARWIN, reason="libproc is macOS only")
def test_gone_pid_forks_no_ps(child, monkeypatch):
    child.kill()
    child.wait()
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert watchdog.usage_of(child.pid) is None
    assert calls == []


@pytest.mark.skipif(not DARWIN, reason="libproc is macOS only")
def test_cpu_agrees_with_ps():
    burn = "import time\nt=time.process_time()\nwhile time.process_time()-t<1.5: pass\ntime.sleep(5)"
    proc = subprocess.Popen([sys.executable, "-c", burn])
    try:
        time.sleep(2.5)
        usage = watchdog.usage_of(proc.pid)
        out = subprocess.run(["/bin/ps", "-o", "cputime=", "-p", str(proc.pid)], capture_output=True, text=True).stdout
        ps_cpu = watchdog._cpu_from_ps(out.strip())
        assert usage is not None and ps_cpu > 1.0
        assert usage.cpu == pytest.approx(ps_cpu, rel=0.15)
    finally:
        proc.kill()
        proc.wait()


def test_ps_fallback_when_libproc_unavailable(child, monkeypatch):
    monkeypatch.setattr(proc_usage, "_LIBPROC", None)
    assert proc_usage.read_usage(child.pid) is None
    usage = watchdog.usage_of(child.pid)
    assert usage is not None and usage.rss > 0 and usage.cpu >= 0.0


def test_mach_conversion_with_fake_timebase():
    assert proc_usage.mach_to_seconds(24_000_000, 125, 3) == pytest.approx(1.0)
    assert proc_usage.mach_to_seconds(5_000_000_000, 1, 1) == pytest.approx(5.0)


def test_read_usage_applies_the_timebase(monkeypatch):
    class FakeLib:
        def proc_pidinfo(self, pid, flavor, arg, buf, size):
            info = buf._obj
            info.pti_resident_size = 4096
            info.pti_total_user = 12_000_000
            info.pti_total_system = 12_000_000
            return size

    monkeypatch.setattr(proc_usage, "_LIBPROC", FakeLib())
    monkeypatch.setattr(proc_usage, "_TIMEBASE", (125, 3))
    assert proc_usage.read_usage(1) == proc_usage.RawUsage(4096, pytest.approx(1.0))


def test_other_errno_is_none_not_gone(monkeypatch):
    class FakeLib:
        def proc_pidinfo(self, *args):
            return 0

    monkeypatch.setattr(proc_usage, "_LIBPROC", FakeLib())
    monkeypatch.setattr(proc_usage, "_TIMEBASE", (1, 1))
    monkeypatch.setattr(proc_usage.ctypes, "get_errno", lambda: proc_usage.errno.EPERM)
    assert proc_usage.read_usage(1) is None
    monkeypatch.setattr(proc_usage.ctypes, "get_errno", lambda: proc_usage.errno.ESRCH)
    with pytest.raises(proc_usage.ProcessGone):
        proc_usage.read_usage(1)


def test_short_read_is_none(monkeypatch):
    class FakeLib:
        def proc_pidinfo(self, *args):
            return 8

    monkeypatch.setattr(proc_usage, "_LIBPROC", FakeLib())
    monkeypatch.setattr(proc_usage, "_TIMEBASE", (1, 1))
    assert proc_usage.read_usage(1) is None


def test_struct_layout_is_96_bytes():
    import ctypes
    assert ctypes.sizeof(proc_usage.ProcTaskInfo) == 96
