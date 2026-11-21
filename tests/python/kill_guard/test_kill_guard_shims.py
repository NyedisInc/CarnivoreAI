
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import List, Tuple

import pytest

from src.core.kill_guard import shims
from src.core.kill_guard.shims import render_shim

REAL_PATH = "/usr/bin:/bin"


def _fake(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class Rig:

    def __init__(self, root: Path, tool: str) -> None:
        self.root = root
        self.pgrep_out = root / "pgrep.out"
        self.ps_out = root / "ps.out"
        self.exec_log = root / "exec.log"
        self.pgrep_args = root / "pgrep.args"
        for f in (self.pgrep_out, self.ps_out):
            f.write_text("")
        real = _fake(root / f"real-{tool}", f'printf "%s\\n" "$*" >> "{self.exec_log}"\nexit 0\n')
        pgrep = _fake(root / "pgrep", f'printf "%s\\n" "$*" > "{self.pgrep_args}"\n'
                      f'[ -s "{self.pgrep_out}" ] || exit 1\ncat "{self.pgrep_out}"\n')
        ps = _fake(root / "ps", f'cat "{self.ps_out}"\n')
        self.shim = root / tool
        self.shim.write_text(render_shim(tool, real, pgrep, ps))
        self.shim.chmod(0o755)

    def matches(self, rows: List[Tuple[int, str]]) -> None:
        self.pgrep_out.write_text("".join(f"{p}\n" for p, _ in rows))
        self.ps_out.write_text("".join(f"{p} {c}\n" for p, c in rows))

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.shim), *args], capture_output=True, text=True, timeout=20,
                              env={"PATH": REAL_PATH})

    def execed(self) -> List[str]:
        return self.exec_log.read_text().splitlines() if self.exec_log.exists() else []


@pytest.fixture()
def pkill(tmp_path: Path) -> Rig:
    return Rig(tmp_path, "pkill")


@pytest.fixture()
def killall(tmp_path: Path) -> Rig:
    return Rig(tmp_path, "killall")


def _refused(rig: Rig, args: Tuple[str, ...], reason: str) -> None:
    done = rig.run(*args)
    assert done.returncode == 2, (args, done.stderr)
    assert reason in done.stderr, done.stderr
    assert "kill <pid>" in done.stderr
    assert len(done.stderr.strip().splitlines()) == 1
    assert rig.execed() == []


def test_incident_command_is_refused(pkill: Rig):
    pkill.matches([(901, "node vitest run")])
    _refused(pkill, ("-f", "vitest", "-u", "jsugamele", "--newer", "0"), "comes after the pattern")


@pytest.mark.parametrize("args,reason", [
    (("-f", "vitest", "other"), "2 patterns"),
    (("-f", "ab"), "shorter than 3"),
    (("-f", "12345"), "all digits"),
    (("claude",), "would match 'claude'"),
    (("-f", "laud"), "would match 'claude'"),
    (("tmu",), "would match 'tmux'"),
    (("-fi", "carnivore"), "would match 'Carnivore'"),
    (("-f", "main"), "would match 'src.main'"),
    (("node",), "too broad"),
    (("python",), "too broad"),
    (("bash",), "too broad"),
    (("-f", "bas"), "would match 'bash'"),
    (("zsh",), "too broad"),
    (("-f", "zs"), "shorter than 3"),
    (("-v", "vitest"), "invert match"),
    (("-u", "jsugamele"), "no pattern"),
    (("-u",), "missing its value"),
    (("-F", "/tmp/pidfile", "vitest"), "not supported"),
])
def test_pkill_refusals(pkill: Rig, args, reason):
    pkill.matches([(901, "node vitest run")])
    _refused(pkill, args, reason)


def test_protected_process_in_dry_run_is_refused(pkill: Rig):
    pkill.matches([(901, "node vitest"), (902, "/Users/x/.local/bin/claude --resume abc")])
    _refused(pkill, ("-f", "vitest"), "protected process")


@pytest.mark.parametrize("cmd", ["tmux -L cloude new-session", "/Applications/Carnivore.app/Contents/MacOS/Carnivore",
                                 "python3 -m src.main"])
def test_other_protected_processes_in_dry_run_are_refused(pkill: Rig, cmd):
    pkill.matches([(902, cmd)])
    _refused(pkill, ("-f", "vitest"), "protected process")


def test_more_than_ten_matches_is_refused(pkill: Rig):
    pkill.matches([(1000 + i, "node vitest") for i in range(11)])
    _refused(pkill, ("-f", "vitest"), "more than 10")


def test_failed_dry_run_is_refused(pkill: Rig):
    (pkill.root / "pgrep").write_text("#!/bin/sh\nexit 3\n")
    _refused(pkill, ("-f", "vitest"), "dry run could not list")


def test_narrow_pkill_runs_the_real_tool_with_the_same_args(pkill: Rig):
    pkill.matches([(901, "node /w/feat-x/web/node_modules/.bin/vitest run"), (902, "node vitest worker")])
    done = pkill.run("-f", "feat-x/web.*vitest")
    assert done.returncode == 0, done.stderr
    assert pkill.execed() == ["-f feat-x/web.*vitest"]


def test_signal_and_options_before_the_pattern_pass_and_dry_run_drops_the_signal(pkill: Rig):
    pkill.matches([(901, "node vitest")])
    assert pkill.run("-9", "-u", "jsugamele", "-f", "vitest").returncode == 0
    assert pkill.execed() == ["-9 -u jsugamele -f vitest"]
    assert pkill.pgrep_args.read_text().strip() == "-u jsugamele -f vitest"
    assert pkill.run("-TERM", "-fx", "vitest").returncode == 0
    assert pkill.pgrep_args.read_text().strip() == "-fx vitest"


def test_zero_matches_still_reaches_the_real_tool(pkill: Rig):
    assert pkill.run("-f", "vitest").returncode == 0
    assert pkill.execed() == ["-f vitest"]


def test_the_shims_own_process_line_is_not_counted(pkill: Rig):
    rows = [(1000 + i, "node vitest") for i in range(10)] + [(2000, f"/bin/sh {pkill.shim} -f vitest")]
    pkill.matches(rows)
    assert pkill.run("-f", "vitest").returncode == 0


def test_killall_refusals(killall: Rig):
    killall.matches([(901, "vitest")])
    _refused(killall, ("vitest", "-9"), "comes after the pattern")
    _refused(killall, ("vitest", "other"), "2 patterns")
    _refused(killall, ("node",), "too broad")
    _refused(killall, ("Carnivore",), "would match 'Carnivore'")
    _refused(killall, ("-9",), "no pattern")


def test_killall_matches_names_exactly_and_passes(killall: Rig):
    killall.matches([(901, "vitest")])
    assert killall.run("-9", "vitest").returncode == 0
    assert killall.execed() == ["-9 vitest"]
    assert killall.pgrep_args.read_text().strip() == "-x vitest"
    assert killall.run("-v", "vitest").returncode == 0


def test_killall_protected_match_is_refused(killall: Rig):
    killall.matches([(901, "claude")])
    _refused(killall, ("vitest",), "protected process")


def test_rendered_scripts_parse():
    for tool, real in shims.GUARDED_TOOLS.items():
        text = render_shim(tool, real)
        done = subprocess.run(["/bin/sh", "-n"], input=text, capture_output=True, text=True, timeout=10)
        assert done.returncode == 0, done.stderr
        assert real in text and "/usr/bin/pgrep" in text


def test_no_unfilled_markers_and_no_override_env():
    text = render_shim("pkill", "/usr/bin/pkill")
    for marker in ("@TOOL@", "@REAL_TOOL@", "@REAL_PGREP@", "@REAL_PS@", "@MAX_MATCHES@", "@MIN_PATTERN_LEN@",
                   "@PROTECTED_NAMES@", "@PROTECTED_PROCESS_REGEX@"):
        assert marker not in text
    assert "${CARNIVORE" not in text and "${CLOUDE" not in text and "getenv" not in text


def test_ensure_guards_writes_executable_shims_once(tmp_path: Path):
    folder = shims.ensure_guards(tmp_path)
    assert folder == tmp_path / "bin" / "guard"
    for tool in ("pkill", "killall"):
        f = folder / tool
        assert os.access(f, os.X_OK)
        assert f.read_text() == render_shim(tool, shims.GUARDED_TOOLS[tool])
    before = (folder / "pkill").stat().st_mtime_ns
    shims.ensure_guards(tmp_path)
    assert (folder / "pkill").stat().st_mtime_ns == before


def test_ensure_guards_unwritable_returns_none(tmp_path: Path):
    blocker = tmp_path / "bin"
    blocker.write_text("a file where the folder should be")
    assert shims.ensure_guards(tmp_path) is None


def test_path_with_guard_puts_the_folder_first_and_dedupes(monkeypatch):
    monkeypatch.setattr(shims, "pane_guard_dir", lambda: "/g")
    assert shims.path_with_guard("/usr/bin:/g:/bin") == "/g:/usr/bin:/bin"
    monkeypatch.setattr(shims, "pane_guard_dir", lambda: None)
    assert shims.path_with_guard("/usr/bin") == "/usr/bin"


def test_rc_prefixed_puts_the_guard_first_after_the_rc(monkeypatch):
    from src.core.shell_init import rc_prefixed

    monkeypatch.setattr("src.core.kill_guard.shims.pane_guard_dir", lambda: "/s/bin/guard")
    built = rc_prefixed("agent")
    assert "path=(/s/bin/guard $path)" in built
    assert built.index("source ~/.zshrc") < built.index("path=(/s/bin/guard $path)") < built.index("agent")
