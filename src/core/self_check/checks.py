
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from src.core.db_models import SESSION_LIFECYCLE_RUNNING
from src.core.product_identity import is_owned_session_name
from src.core.self_check import constants as K
from src.core.tmux_listing import REASON_PROBE_ERROR, TmuxListing, classify_listing_failure


@dataclass(frozen=True)
class CheckResult:

    name: str
    status: str
    summary: str
    findings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status, "summary": self.summary, "findings": list(self.findings)}


ListForSocket = Callable[[str], Tuple[str, TmuxListing]]
SocketResolver = Callable[[ListForSocket], Tuple[str, TmuxListing]]


@dataclass(frozen=True)
class Context:

    code_dir: Path
    claude_dir: Path
    state_dir: Path
    db_file: Path
    resolve_socket: SocketResolver
    tmux_path: Optional[str]
    claude_candidates: Tuple[str, ...]

    @property
    def critical(self) -> List[Tuple[Path, bool]]:
        return [(self.code_dir / "src" / "main.py", True), (self.claude_dir, True),
                (self.claude_dir / "projects", True), (self.claude_dir / "settings.json", False),
                (self.state_dir, True), (self.db_file, True)]

    @property
    def sample_dirs(self) -> List[Path]:
        return [self.code_dir / "src", self.claude_dir, self.claude_dir / "projects", self.state_dir]


class SystemIO:

    def stat(self, path: Path) -> Optional[os.stat_result]:
        try:
            return os.stat(path)
        except OSError:
            return None

    def entries(self, path: Path) -> Iterator[Tuple[str, Optional[os.stat_result]]]:
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        yield entry.name, entry.stat()
                    except OSError:
                        yield entry.name, None
        except OSError:
            return

    def list_dir(self, path: Path) -> None:
        os.listdir(path)

    def free_bytes(self, path: Path) -> Optional[int]:
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None

    def is_executable(self, path: str) -> bool:
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def tmux_list(self, argv: List[str]) -> Optional[Tuple[int, str, str]]:
        """Run the read-only ``list-sessions``. Output: (returncode, stdout, stderr) or None when it could not run."""
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=K.COMMAND_TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.returncode, done.stdout, done.stderr

    def live_session_count(self, db_file: Path) -> Optional[int]:
        try:
            with closing(sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True,
                                         timeout=K.COMMAND_TIMEOUT_SECONDS)) as conn:
                row = conn.execute("SELECT COUNT(*) FROM sessions WHERE lifecycle = ?",
                                   (SESSION_LIFECYCLE_RUNNING,)).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0])


def is_dataless(st: Optional[os.stat_result]) -> bool:
    return st is not None and bool(getattr(st, "st_flags", 0) & K.SF_DATALESS)


def check_files(io: SystemIO, ctx: Context) -> CheckResult:
    findings: List[str] = []
    checked = 0
    for path, required in ctx.critical:
        st = io.stat(path)
        checked += 1
        if st is None:
            if required:
                findings.append(f"missing or unreadable: {path}")
        elif is_dataless(st):
            findings.append(f"iCloud placeholder (not on disk): {path}")
    budget = K.MAX_SAMPLE_STATS
    for directory in ctx.sample_dirs:
        for name, st in io.entries(directory):
            if budget <= 0:
                break
            budget -= 1
            checked += 1
            if is_dataless(st):
                findings.append(f"iCloud placeholder (not on disk): {directory / name}")
    summary = f"{checked} paths stat'ed, {len(findings)} problems"
    return CheckResult(K.CHECK_FILES, K.FAIL if findings else K.PASS, summary, findings)


def check_space(io: SystemIO, ctx: Context) -> CheckResult:
    seen: Dict[int, Tuple[Path, int]] = {}
    for path in (ctx.code_dir, ctx.claude_dir, ctx.state_dir):
        st = io.stat(path)
        free = io.free_bytes(path)
        if st is not None and free is not None:
            seen.setdefault(st.st_dev, (path, free))
    findings = [f"{free / 1024 ** 3:.1f} GiB free on the volume holding {path} "
                f"(alert below {K.LOW_SPACE_FREE_BYTES // 1024 ** 3} GiB)"
                for path, free in seen.values() if free < K.LOW_SPACE_FREE_BYTES]
    if not seen:
        return CheckResult(K.CHECK_SPACE, K.FAIL, "free space could not be measured",
                           ["no Carnivore path could be stat'ed for free space"])
    least = min(free for _, free in seen.values())
    return CheckResult(K.CHECK_SPACE, K.FAIL if findings else K.PASS,
                       f"{len(seen)} volume(s), least free {least / 1024 ** 3:.1f} GiB", findings)


def _listing_from(answer: Optional[Tuple[int, str, str]]) -> TmuxListing:
    if answer is None:
        return TmuxListing.unavailable(REASON_PROBE_ERROR, detail="tmux could not run or timed out")
    code, out, err = answer
    if code != 0:
        return classify_listing_failure(code, err)
    names = [n for n in out.splitlines() if n and is_owned_session_name(n)]
    return TmuxListing.answered(names)


def check_tmux(io: SystemIO, ctx: Context) -> CheckResult:
    if not ctx.tmux_path:
        return CheckResult(K.CHECK_TMUX, K.FAIL, "tmux not found", ["tmux is not installed; no session can start"])

    def list_for_socket(socket: str) -> Tuple[str, TmuxListing]:
        return socket, _listing_from(io.tmux_list([ctx.tmux_path, "-L", socket, "list-sessions", "-F", "#{session_name}"]))

    socket, listing = ctx.resolve_socket(list_for_socket)
    if not listing.ok:
        return CheckResult(K.CHECK_TMUX, K.FAIL, "tmux did not answer",
                           [f"socket {socket}: {listing.reason}: {(listing.detail or '')[:200]}"])
    if listing.sessions:
        return CheckResult(K.CHECK_TMUX, K.PASS, f"tmux answers on socket {socket}, {len(listing.sessions)} session(s)")
    live = io.live_session_count(ctx.db_file)
    if live is None:
        return CheckResult(K.CHECK_TMUX, K.FAIL, "live sessions could not be counted",
                           [f"socket {socket} has no server and the database could not be read to tell if one is expected"])
    if live > 0:
        return CheckResult(K.CHECK_TMUX, K.FAIL, "sessions recorded live but no tmux server",
                           [f"the database records {live} running session(s) but socket {socket} has no session"])
    return CheckResult(K.CHECK_TMUX, K.PASS, f"no tmux server on socket {socket}, no session recorded live")


def check_claude_cli(io: SystemIO, ctx: Context) -> CheckResult:
    found = shutil.which("claude")
    candidates = ([found] if found else []) + [os.path.expanduser(c) for c in ctx.claude_candidates]
    for candidate in candidates:
        if io.is_executable(candidate):
            return CheckResult(K.CHECK_CLAUDE_CLI, K.PASS, f"claude at {candidate}")
    return CheckResult(K.CHECK_CLAUDE_CLI, K.FAIL, "claude not found",
                       ["no executable claude on PATH or the known install paths"])


def check_access(io: SystemIO, ctx: Context) -> CheckResult:
    target = ctx.claude_dir / "projects"
    try:
        io.list_dir(target)
    except OSError as exc:
        return CheckResult(K.CHECK_ACCESS, K.FAIL, "cannot list the claude projects folder",
                           [f"{target}: {exc.strerror or type(exc).__name__}"])
    return CheckResult(K.CHECK_ACCESS, K.PASS, "claude projects folder is listable")


_CHECKS = {K.CHECK_FILES: check_files, K.CHECK_SPACE: check_space, K.CHECK_TMUX: check_tmux,
           K.CHECK_CLAUDE_CLI: check_claude_cli, K.CHECK_ACCESS: check_access}


def run_checks(ctx: Context, io: Optional[SystemIO] = None) -> List[CheckResult]:
    host = io or SystemIO()
    return [_CHECKS[name](host, ctx) for name in K.ALL_CHECKS]


def report_dict(results: List[CheckResult]) -> Dict[str, Any]:
    failed = any(r.status == K.FAIL for r in results)
    return {"status": K.FAIL if failed else K.PASS, "checks": [r.to_dict() for r in results]}
