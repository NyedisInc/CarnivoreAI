"""Stop orphaned agent scratch processes (SIGTERM only), for the 6-hourly maintenance run.

Why: on 2026-10-28 eight ``while True: pass`` scripts started from
``/private/tmp/claude-501/`` outlived their agent, were adopted by launchd and
held the Mac at 96% CPU for 20 hours. Joe ruled (Task Manager item 1468):
"stop them automatically and tell me after".

A process is stopped only when ALL hold: same uid as us, ppid 1, not a
launchd-managed job (``launchctl list``), older than ``--min-age-hours``, and
it is an interpreter (python, node, sh ...) whose FIRST non-option argument is
an existing script file under a claude scratch root (a relative path is
resolved against the process's own working folder; an unreadable folder means
skip). Hard excludes (tmux, Carnivore, Electron, uvicorn, ``src.main``, pid 1,
ourselves, our parent, claude, codex) win over everything. Just before
signaling, the pid's start time (microseconds, from the table read) and argv
are compared again; a change means the pid was reused and it is skipped. Only
SIGTERM is ever sent. Survivors are reported, never escalated.

The process table, real argv list, start times and cwd come from libproc
(``src/core/libproc_snapshot.py``). Without libproc the run refuses (exit 2)
rather than guess from ``ps`` text. An implausible table (no pid 1, no own pid)
also refuses.

Exit codes: 0 nothing found or all stopped; 1 something survived;
2 the process table could not be read (a refusal, never a pass).

Command line for the maintenance run (from the repo root; the venv python is
needed because this imports ``src.core``):
``venv/bin/python3 scripts/maintenance/reap_orphan_agent_processes.py --json``
Preview with ``--dry-run`` added.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.core import libproc_snapshot  # noqa: E402
from src.core.stream_redactor import redact_whole  # noqa: E402

SCRATCH_ROOT_TEMPLATES: list[str] = ["/private/tmp/claude-{uid}", "/tmp/claude-{uid}"]
EXCLUDED_WORDS: list[str] = ["tmux", "carnivore", "electron", "uvicorn", "src.main"]
INTERPRETER_RE = re.compile(r"^(python(\d+(\.\d+)*)?|Python|sh|bash|zsh|node|ruby|perl|osascript)$")
VALUE_OPTIONS: dict[str, frozenset] = {
    "python": frozenset({"-W", "-X"}), "node": frozenset({"-r", "--require", "--import"}),
    "perl": frozenset({"-I"}), "ruby": frozenset({"-I"}), "osascript": frozenset({"-l"}),
}
CODE_OPTIONS: dict[str, frozenset] = {
    "python": frozenset({"-c", "-m"}), "node": frozenset({"-c", "-m", "-e"}),
    "perl": frozenset({"-e"}), "ruby": frozenset({"-e"}), "osascript": frozenset({"-e"}),
}
AGENT_BINARIES: list[str] = ["claude", "codex"]
DEFAULT_MIN_AGE_HOURS: float = 2.0
DEFAULT_GRACE_SECONDS: float = 10.0
POLL_INTERVAL_SECONDS: float = 0.5
COMMAND_TRIM_CHARS: int = 120
LAUNCHCTL_ARGS: list[str] = ["launchctl", "list"]
LAUNCHCTL_TIMEOUT_SECONDS: float = 15.0
EXIT_OK, EXIT_SURVIVOR, EXIT_UNREADABLE = 0, 1, 2

SKIP_SELF = "self_or_parent"
SKIP_PID1 = "pid_1"
SKIP_EXCLUDED = "excluded_word"
SKIP_UID = "other_uid"
SKIP_HAS_PARENT = "has_parent"
SKIP_LAUNCHD = "launchd_job"
SKIP_YOUNG = "too_young"
SKIP_UNREADABLE = "argv_unreadable"
SKIP_AGENT = "agent_binary"
SKIP_INTERPRETER = "not_an_interpreter"
SKIP_NO_CWD = "relative_script_no_cwd"
SKIP_NOT_SCRIPT = "no_scratch_script"
SKIP_REUSED = "pid_reused"
SKIP_ERROR = "read_error"
RESULT_UNVERIFIED = "unverified"

Start = tuple[int, int]


class ReaperError(Exception):
    pass


class ProcessTableError(ReaperError):
    pass


@dataclass(frozen=True)
class ProcRow:

    pid: int
    ppid: int
    uid: int
    start: Start
    age_seconds: int
    command: str


@dataclass(frozen=True)
class Detail:

    start: Start
    argv: tuple[str, ...]
    cwd: Optional[str]


@dataclass
class Deps:

    read_table: Callable[[], list[ProcRow]]
    read_detail: Callable[[int], Optional[Detail]]
    read_launchd_pids: Callable[[], set[int]]
    send_signal: Callable[[int, int], None]
    is_file: Callable[[str], bool]
    realpath: Callable[[str], str]
    sleep: Callable[[float], None]
    uid: int
    pid: int
    ppid: int


@dataclass
class Outcome:

    pid: int
    command: str
    age_seconds: int
    result: str


@dataclass
class Report:

    dry_run: bool
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        bad = ("survived", RESULT_UNVERIFIED)
        return EXIT_SURVIVOR if any(o.result in bad for o in self.outcomes) else EXIT_OK


def read_table_libproc() -> list[ProcRow]:
    snap = libproc_snapshot.snapshot()
    if not snap:
        raise ProcessTableError("libproc cannot read the process table")
    now = time.time()
    return [ProcRow(s.pid, s.ppid, s.uid, s.start, max(0, int(now - s.start[0])), s.command) for s in snap]


def read_detail_libproc(pid: int) -> Optional[Detail]:
    found = libproc_snapshot.process_details([pid])
    if found is None:
        raise ProcessTableError("libproc cannot read process details")
    d = found.get(pid)
    return Detail(d.start, d.argv, d.cwd) if d else None


def read_launchd_pids_real() -> set[int]:
    env = {**os.environ, "LC_ALL": "C"}
    try:
        proc = subprocess.run(LAUNCHCTL_ARGS, capture_output=True, text=True, env=env,
                              timeout=LAUNCHCTL_TIMEOUT_SECONDS, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProcessTableError(f"launchctl list failed: {exc}") from exc
    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        first = line.split(None, 1)
        if first and first[0].isdigit():
            pids.add(int(first[0]))
    return pids


def send_sigterm_real(pid: int, sig: int) -> None:
    if sig != signal.SIGTERM:
        raise ReaperError(f"refusing signal {sig}: only SIGTERM is allowed")
    os.kill(pid, sig)


def default_deps() -> Deps:
    return Deps(read_table_libproc, read_detail_libproc, read_launchd_pids_real, send_sigterm_real,
                os.path.isfile, os.path.realpath, time.sleep, os.getuid(), os.getpid(), os.getppid())


def check_table(rows: list[ProcRow], deps: Deps) -> None:
    pids = {r.pid for r in rows}
    if 1 not in pids or deps.pid not in pids:
        raise ProcessTableError("process table lacks pid 1 or this process; refusing to trust it")


def scratch_roots(uid: int, realpath: Callable[[str], str]) -> list[str]:
    roots: list[str] = []
    for tmpl in SCRATCH_ROOT_TEMPLATES:
        raw = tmpl.format(uid=uid)
        for r in (raw, realpath(raw)):
            if r not in roots:
                roots.append(r)
    return roots


def _under(path: str, roots: Sequence[str]) -> bool:
    return any(path.startswith(r.rstrip("/") + "/") for r in roots)


def interpreter_family(base: str) -> str:
    return "python" if base.lower().startswith("python") else base


def first_script_arg(argv: Sequence[str]) -> Optional[str]:
    family = interpreter_family(os.path.basename(argv[0]))
    takes_value, runs_code = VALUE_OPTIONS.get(family, frozenset()), CODE_OPTIONS.get(family, frozenset())
    args, i = argv[1:], 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if not tok.startswith("-") or tok == "-":
            return tok
        if tok in runs_code or (not tok.startswith("--") and tok[:2] in runs_code):
            return None
        i += 2 if tok in takes_value else 1
    return None


def script_verdict(detail: Detail, deps: Deps) -> Optional[str]:
    if not detail.argv:
        return SKIP_UNREADABLE
    base = os.path.basename(detail.argv[0])
    if base in AGENT_BINARIES:
        return SKIP_AGENT
    if not INTERPRETER_RE.match(base):
        return SKIP_INTERPRETER
    arg = first_script_arg(detail.argv)
    if arg is None:
        return SKIP_NOT_SCRIPT
    if not arg.startswith("/"):
        if not detail.cwd:
            return SKIP_NO_CWD
        arg = os.path.join(detail.cwd, arg)
    if deps.is_file(arg) and _under(deps.realpath(arg), scratch_roots(deps.uid, deps.realpath)):
        return None
    return SKIP_NOT_SCRIPT


def judge(row: ProcRow, min_age_s: float, launchd: set[int], deps: Deps) -> tuple[Optional[str], Optional[Detail]]:
    if row.pid in (deps.pid, deps.ppid):
        return SKIP_SELF, None
    if row.pid == 1:
        return SKIP_PID1, None
    if row.uid != deps.uid:
        return SKIP_UID, None
    if row.ppid != 1:
        return SKIP_HAS_PARENT, None
    if row.pid in launchd:
        return SKIP_LAUNCHD, None
    if row.age_seconds <= min_age_s:
        return SKIP_YOUNG, None
    detail = deps.read_detail(row.pid)
    if detail is None or not detail.argv:
        return SKIP_UNREADABLE, None
    exe = detail.argv[0].lower()
    if any(w in exe for w in EXCLUDED_WORDS):
        return SKIP_EXCLUDED, None
    verdict = script_verdict(detail, deps)
    return (verdict, None) if verdict else (None, detail)


def skip_reason(row: ProcRow, min_age_s: float, launchd: set[int], deps: Deps) -> Optional[str]:
    return judge(row, min_age_s, launchd, deps)[0]


def _same_process(row: ProcRow, judged: Detail, deps: Deps) -> bool:
    now = deps.read_detail(row.pid)
    return now is not None and now.start == row.start == judged.start and now.argv == judged.argv


def _wait_gone(row: ProcRow, grace_s: float, deps: Deps) -> bool:
    waited = 0.0
    while True:
        now = deps.read_detail(row.pid)
        if now is None or now.start != row.start:
            return True
        if waited >= grace_s:
            return False
        deps.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS


def _stop_one(row: ProcRow, grace_s: float, deps: Deps) -> str:
    try:
        deps.send_signal(row.pid, signal.SIGTERM)
    except ProcessLookupError:
        return "stopped"
    except PermissionError:
        return "survived"
    try:
        return "stopped" if _wait_gone(row, grace_s, deps) else "survived"
    except (ReaperError, OSError):
        return RESULT_UNVERIFIED


def _show(row: ProcRow) -> str:
    return redact_whole(row.command)[:COMMAND_TRIM_CHARS]


def _handle(row: ProcRow, judged: Detail, grace_s: float, dry_run: bool, deps: Deps) -> str:
    if not _same_process(row, judged, deps):
        return SKIP_REUSED
    return "would_stop" if dry_run else _stop_one(row, grace_s, deps)


def reap(rows: list[ProcRow], min_age_s: float, grace_s: float, dry_run: bool, deps: Deps) -> Report:
    report = Report(dry_run=dry_run)
    launchd = deps.read_launchd_pids()
    for row in rows:
        try:
            reason, judged = judge(row, min_age_s, launchd, deps)
            if reason is not None or judged is None:
                continue
            result = _handle(row, judged, grace_s, dry_run, deps)
        except (ReaperError, OSError):
            result = SKIP_ERROR
        report.outcomes.append(Outcome(row.pid, _show(row), row.age_seconds, result))
    return report


def format_report(report: Report) -> str:
    if not report.outcomes:
        return "no orphaned agent processes found"
    return "\n".join(f"pid {o.pid} age {o.age_seconds // 3600}h{o.age_seconds % 3600 // 60:02d}m "
                     f"{o.result}: {o.command}" for o in report.outcomes)


def run(argv: Sequence[str], deps: Optional[Deps] = None) -> tuple[int, str]:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--min-age-hours", type=float, default=DEFAULT_MIN_AGE_HOURS)
    ap.add_argument("--grace-seconds", type=float, default=DEFAULT_GRACE_SECONDS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv))
    deps = deps or default_deps()
    try:
        rows = deps.read_table()
        check_table(rows, deps)
        report = reap(rows, args.min_age_hours * 3600, args.grace_seconds, args.dry_run, deps)
    except ProcessTableError as exc:
        msg = f"refused: {exc}"
        return EXIT_UNREADABLE, json.dumps({"error": msg, "exit_code": EXIT_UNREADABLE}) if args.json else msg
    if args.json:
        return report.exit_code, json.dumps({"dry_run": report.dry_run, "found": len(report.outcomes),
                                             "results": [vars(o) for o in report.outcomes],
                                             "exit_code": report.exit_code}, indent=2)
    return report.exit_code, format_report(report)


def main() -> int:
    code, text = run(sys.argv[1:])
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
