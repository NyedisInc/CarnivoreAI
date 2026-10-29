
from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from scripts.maintenance import reap_orphan_agent_processes as r
from src.core import libproc_snapshot

UID, ME, PARENT = 501, 4000, 3999
SCRATCH = "/private/tmp/claude-501"
SCRIPT = f"{SCRATCH}/burn.py"
NOW = 1_800_000_000
REAL_SENDER = r.send_sigterm_real


@dataclass
class P:

    pid: int = 100
    argv: tuple = ("python3", SCRIPT)
    ppid: int = 1
    uid: int = UID
    age_h: float = 5
    cwd: Optional[str] = "/"

    @property
    def start(self) -> tuple:
        return (NOW - int(self.age_h * 3600), 123456)


class World:

    def __init__(self, *procs: P, dies: bool = True, launchd=(), files=(SCRIPT,)):
        base = [P(1, ("launchd",), 0, 0, 999), P(ME, ("python3", "pytest"), PARENT, UID, 0.1, "/"),
                P(PARENT, ("zsh",), 1, UID, 9)]
        self.procs = {p.pid: p for p in base + list(procs)}
        self.dies, self.launchd, self.files, self.sent = dies, set(launchd), set(files), []
        self.table_error: Optional[str] = None
        self.hide_table: set = set()

    def rows(self) -> list:
        if self.table_error:
            raise r.ProcessTableError(self.table_error)
        return [r.ProcRow(p.pid, p.ppid, p.uid, p.start, int(p.age_h * 3600), " ".join(p.argv))
                for p in self.procs.values() if p.pid not in self.hide_table]

    def detail(self, pid: int) -> Optional[r.Detail]:
        p = self.procs.get(pid)
        return r.Detail(p.start, tuple(p.argv), p.cwd) if p else None

    def send(self, pid: int, sig: int) -> None:
        self.sent.append((pid, sig))
        if self.dies:
            self.procs.pop(pid, None)

    def deps(self) -> r.Deps:
        return r.Deps(self.rows, self.detail, lambda: set(self.launchd), self.send, lambda f: f in self.files,
                      lambda f: f.replace("/tmp/claude", "/private/tmp/claude") if f.startswith("/tmp/") else f,
                      lambda s: None, UID, ME, PARENT)


def go(world: World, *flags: str):
    code, text = r.run(["--json", *flags], world.deps())
    return code, json.loads(text)


@pytest.fixture(autouse=True)
def never_real(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a test reached a real process boundary")
    for obj, name in [(r, "send_sigterm_real"), (r, "default_deps"), (os, "kill"), (subprocess, "run"),
                      (libproc_snapshot, "snapshot"), (libproc_snapshot, "process_details")]:
        monkeypatch.setattr(obj, name, boom)


def test_match_is_stopped():
    w = World(P())
    code, out = go(w)
    assert w.sent == [(100, signal.SIGTERM)] and code == 0 and out["results"][0]["result"] == "stopped"


@pytest.mark.parametrize("proc,reason", [
    (P(uid=502), r.SKIP_UID),
    (P(ppid=77), r.SKIP_HAS_PARENT),
    (P(age_h=1.5), r.SKIP_YOUNG),
    (P(argv=("python3", "/Users/x/spin.py")), r.SKIP_NOT_SCRIPT),
    (P(argv=("python3", f"{SCRATCH}/missing.py")), r.SKIP_NOT_SCRIPT),
    (P(argv=("python3", "-c", f"print('{SCRIPT}')")), r.SKIP_NOT_SCRIPT),
    (P(argv=(SCRIPT,)), r.SKIP_INTERPRETER),
    (P(argv=("claude", "--append-system-prompt-file", f"{SCRATCH}/a.md")), r.SKIP_AGENT),
    (P(argv=("/usr/local/bin/codex", SCRIPT)), r.SKIP_AGENT),
    (P(argv=("python3", "/Users/x/serve.py", "5091", f"{SCRATCH}/page.html")), r.SKIP_NOT_SCRIPT),
    (P(argv=("/opt/homebrew/bin/tmux", SCRIPT)), r.SKIP_EXCLUDED),
    (P(argv=("/Applications/Carnivore.app/Contents/Resources/python3", SCRIPT)), r.SKIP_EXCLUDED),
    (P(argv=("Electron", SCRIPT)), r.SKIP_EXCLUDED),
    (P(argv=("/x/venv/bin/uvicorn", SCRIPT)), r.SKIP_EXCLUDED),
    (P(argv=("/x/src.main/python3", SCRIPT)), r.SKIP_EXCLUDED),
    (P(argv=("node", "-r", f"{SCRATCH}/hook.js", "/Users/x/server.js")), r.SKIP_NOT_SCRIPT),
    (P(argv=("python3", "-m", "mod")), r.SKIP_NOT_SCRIPT),
    (P(argv=("python3", "-c", "CODE")), r.SKIP_NOT_SCRIPT),
    (P(argv=("python3", "-cCODE")), r.SKIP_NOT_SCRIPT),
    (P(argv=("ruby", "-e", "puts 1")), r.SKIP_NOT_SCRIPT),
    (P(argv=("bash", "-c", "sleep 9")), r.SKIP_NOT_SCRIPT),
    (P(argv=("python3", "relative.py"), cwd=None), r.SKIP_NO_CWD),
    (P(argv=("python3", "relative.py"), cwd="/Users/x"), r.SKIP_NOT_SCRIPT),
    (P(pid=ME), r.SKIP_SELF),
    (P(pid=PARENT), r.SKIP_SELF),
])
def test_each_failing_condition_is_skipped(proc, reason):
    w = World(proc, files=(SCRIPT, f"{SCRATCH}/page.html", "/Users/x/server.js", f"{SCRATCH}/hook.js", "/Users/x/serve.py", "/Users/x/spin.py", "/Users/x/relative.py"))
    row = next(x for x in w.rows() if x.pid == proc.pid)
    assert r.skip_reason(row, 2 * 3600, set(), w.deps()) == reason
    w.procs.pop(ME, None) if proc.pid == ME else None
    if proc.pid not in (ME, PARENT):
        code, _ = go(w)
        assert w.sent == [] and code == 0


def test_pid1_guard_alone():
    w = World()
    w.procs[1] = P(1, ("python3", SCRIPT), 1, UID, 999)
    d = w.deps()
    row = next(x for x in w.rows() if x.pid == 1)
    assert r.skip_reason(row, 0, set(), d) == r.SKIP_PID1


def test_first_non_option_argument_must_be_the_script():
    w = World(P(argv=("python3", "-u", SCRIPT)))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_framework_python_and_node_are_interpreters():
    fw = "/opt/homebrew/Frameworks/Python.framework/Versions/3.15/Resources/Python.app/Contents/MacOS/Python"
    w = World(P(100, (fw, SCRIPT)), P(101, ("python3.14", SCRIPT)), P(102, ("node", SCRIPT)))
    go(w)
    assert sorted(p for p, _ in w.sent) == [100, 101, 102]


def test_relative_script_with_scratch_cwd_is_a_target():
    w = World(P(argv=("Python", "recv.py"), cwd=f"{SCRATCH}/x/scratchpad"), files=(f"{SCRATCH}/x/scratchpad/recv.py",))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_symlink_into_scratch_counts_via_realpath():
    link = "/tmp/claude-501/spin.py"
    w = World(P(argv=("python3", link)), files=(link,))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_launchd_job_is_skipped():
    w = World(P(), launchd={100})
    code, out = go(w)
    assert w.sent == [] and out["found"] == 0


def _changes_after_judging(world: World, **change):
    reads = {"n": 0}
    orig = world.detail

    def shifting(pid: int):
        d = orig(pid)
        if pid != 100 or d is None:
            return d
        reads["n"] += 1
        return d if reads["n"] == 1 else r.Detail(change.get("start", d.start), change.get("argv", d.argv), d.cwd)
    deps = world.deps()
    deps.read_detail = shifting
    return deps


def test_reused_pid_new_start_is_skipped():
    w = World(P())
    code, text = r.run(["--json"], _changes_after_judging(w, start=(NOW, 1)))
    assert w.sent == [] and r.SKIP_REUSED in text


def test_argv_changed_after_judging_is_not_signaled():
    w = World(P())
    _, text = r.run(["--json"], _changes_after_judging(w, argv=("python3", "other.py")))
    assert w.sent == [] and r.SKIP_REUSED in text


def test_start_must_match_the_table_value():
    w = World(P())
    rows = w.rows()
    rows[-1] = r.ProcRow(100, 1, UID, (5, 5), 18000, f"python3 {SCRIPT}")
    deps = w.deps()
    deps.read_table = lambda: rows
    r.run([], deps)
    assert w.sent == []


def test_survivor_gives_exit_1_and_no_second_signal():
    w = World(P(), dies=False)
    code, out = go(w)
    assert code == 1 and out["results"][0]["result"] == "survived" and w.sent == [(100, signal.SIGTERM)]


def test_unreadable_table_gives_exit_2():
    w = World()
    w.table_error = "no libproc"
    code, text = r.run([], w.deps())
    assert code == 2 and "refused" in text


@pytest.mark.parametrize("hide", [{1}, {ME}, {1, ME}])
def test_blank_or_implausible_table_gives_exit_2(hide):
    w = World(P())
    w.hide_table = hide
    code, _ = go(w)
    assert code == 2 and w.sent == []


def test_empty_table_gives_exit_2():
    deps = World().deps()
    deps.read_table = lambda: []
    assert r.run([], deps)[0] == 2


def test_launchctl_failure_gives_exit_2():
    w = World(P())
    deps = w.deps()

    def bad():
        raise r.ProcessTableError("launchctl broke")
    deps.read_launchd_pids = bad
    assert r.run([], deps)[0] == 2 and w.sent == []


def test_dry_run_sends_nothing():
    w = World(P())
    code, out = go(w, "--dry-run")
    assert w.sent == [] and code == 0 and out["results"][0]["result"] == "would_stop"


def test_nothing_found_is_exit_0():
    code, out = go(World(P(argv=("/bin/zsh",))))
    assert code == 0 and out["found"] == 0


def test_command_is_trimmed_to_120_and_secrets_starred():
    secret = "ghp_" + "a" * 36
    w = World(P(argv=("python3", SCRIPT, secret, "x" * 300)))
    _, out = go(w)
    shown = out["results"][0]["command"]
    assert len(shown) == 120 and secret not in shown


def test_min_age_flag():
    w = World(P(age_h=1.5))
    go(w, "--min-age-hours", "1")
    assert w.sent == [(100, signal.SIGTERM)]


def test_scratch_path_containing_carnivore_is_still_reaped():
    script = f"{SCRATCH}/-Users-x-carnivore-projects/burn.py"
    w = World(P(argv=("python3", script)), files=(script,))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_script_named_after_tmux_is_still_reaped():
    script = f"{SCRATCH}/tmux-burn.py"
    w = World(P(argv=("python3", script)), files=(script,))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_python_option_value_is_not_the_script():
    w = World(P(argv=("python3", "-W", "ignore", SCRIPT)))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_node_require_value_is_not_the_script():
    w = World(P(argv=("node", "-r", f"{SCRATCH}/hook.js", SCRIPT)), files=(SCRIPT, f"{SCRATCH}/hook.js"))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_osascript_language_value_is_not_the_script():
    w = World(P(argv=("osascript", "-l", "JavaScript", SCRIPT)))
    go(w)
    assert w.sent == [(100, signal.SIGTERM)]


def test_read_error_on_one_pid_keeps_the_kills_already_sent():
    w = World(P(100), P(101, ("python3", SCRIPT)))
    deps, orig = w.deps(), w.detail

    def flaky(pid: int):
        if pid == 101:
            raise r.ProcessTableError("libproc hiccup")
        return orig(pid)
    deps.read_detail = flaky
    code, text = r.run(["--json"], deps)
    out = json.loads(text)
    assert w.sent == [(100, signal.SIGTERM)] and code == 0
    assert [(o["pid"], o["result"]) for o in out["results"]] == [(100, "stopped"), (101, r.SKIP_ERROR)]


def test_error_after_the_signal_is_reported_unverified_with_exit_1():
    w = World(P(), dies=False)
    deps, orig = w.deps(), w.detail
    reads = {"n": 0}

    def flaky(pid: int):
        reads["n"] += 1
        if pid == 100 and w.sent:
            raise OSError("gone sideways")
        return orig(pid)
    deps.read_detail = flaky
    code, text = r.run(["--json"], deps)
    assert code == 1 and json.loads(text)["results"][0]["result"] == r.RESULT_UNVERIFIED


@pytest.mark.parametrize("argv", [("python3", "-c", SCRIPT), ("python3", "-m", SCRIPT), ("node", "-e", SCRIPT),
                                  ("perl", "-e", SCRIPT)])
def test_code_option_is_never_a_target_even_when_its_value_is_a_scratch_file(argv):
    w = World(P(argv=argv))
    go(w)
    assert w.sent == []


def test_judged_start_that_differs_from_the_table_is_not_signaled():
    w = World(P())
    orig, reads = w.detail, {"n": 0}

    def first_read_other_start(pid: int):
        d = orig(pid)
        if pid != 100 or d is None:
            return d
        reads["n"] += 1
        return r.Detail((NOW, 7), d.argv, d.cwd) if reads["n"] == 1 else d
    deps = w.deps()
    deps.read_detail = first_read_other_start
    r.run([], deps)
    assert w.sent == []


KILL_CALLS = {"kill", "killpg", "Signals", "send_signal", "pthread_kill"}


def sigkill_uses(source: str) -> list:
    hits = []
    for node in ast.walk(ast.parse(source)):
        names = [getattr(node, "attr", None), getattr(node, "id", None), getattr(node, "name", None)]
        if "SIGKILL" in names:
            hits.append(node.lineno)
        if isinstance(node, ast.Call):
            fn = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            args = list(node.args) + [k.value for k in node.keywords]
            if fn in KILL_CALLS and any(isinstance(a, ast.Constant) and (a.value == 9 or "KILL" in str(a.value))
                                        for a in args):
                hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("bad", ["os.kill(pid, 9)", "signal.Signals(9)", "from signal import SIGKILL",
                                 "os.kill(pid, signal.SIGKILL)", "send_signal(pid, 9)"])
def test_sigkill_guard_catches_every_spelling(bad):
    assert sigkill_uses(bad)


def test_module_never_uses_sigkill():
    assert sigkill_uses(Path(r.__file__).read_text()) == []


def test_default_sender_refuses_non_sigterm_without_killing():
    with pytest.raises(r.ReaperError):
        REAL_SENDER(1, signal.SIGKILL)


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="libproc is macOS only")
def test_libproc_details_return_argv_list_start_and_cwd(monkeypatch):
    monkeypatch.undo()
    me = libproc_snapshot.process_details([os.getpid()])[os.getpid()]
    assert me.argv[0] and isinstance(me.argv, tuple) and me.start[0] > 0
    assert me.cwd == os.path.realpath(os.getcwd())


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="libproc is macOS only")
def test_libproc_reads_spaced_and_empty_arguments_exactly(monkeypatch, tmp_path):
    monkeypatch.undo()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "a b  c", ""], cwd=tmp_path)
    try:
        got = None
        for _ in range(100):
            found = libproc_snapshot.process_details([child.pid]).get(child.pid)
            if found and found.argv[-2:] == ("a b  c", ""):
                got = found
                break
            time.sleep(0.05)
        assert got is not None and got.argv[1:3] == ("-c", "import time; time.sleep(60)")
        assert got.cwd == os.path.realpath(tmp_path)
    finally:
        child.terminate()
        child.wait(timeout=10)
