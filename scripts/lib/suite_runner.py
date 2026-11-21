#!/usr/bin/env python3
import argparse
import glob
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

STALL_EXIT = 97
CAP_EXIT = 98
MARKERS = ("== pass 1", "== targeted")


def running_tests(state_dir: Path) -> list[str]:
    return [f"{p.stem}: {p.read_text().strip()}" for p in sorted(state_dir.glob("*.cur"))]


def descendants(root: int) -> set[int]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout
    kids: dict[int, list[int]] = {}
    for line in out.splitlines():
        a, b = line.split()
        kids.setdefault(int(b), []).append(int(a))
    seen, todo = {root}, [root]
    while todo:
        for k in kids.get(todo.pop(), []):
            if k not in seen:
                seen.add(k)
                todo.append(k)
    return seen


def tmux_socket_dir() -> Path:
    base = os.environ.get("TMUX_TMPDIR") or ("/private/tmp" if sys.platform == "darwin" else "/tmp")
    return Path(base) / f"tmux-{os.getuid()}"


def reap_tmux(pids: set[int], sock_dir: Path) -> list[str]:
    killed = []
    for path in glob.glob(str(sock_dir / "cloude_pytest_*")):
        name = os.path.basename(path)
        m = re.match(r"cloude_pytest_(\d+)_", name)
        if m and int(m.group(1)) in pids:
            subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True)
            killed.append(name)
    return killed


def state_pids(state_dir: Path) -> set[int]:
    return {int(p.read_text()) for p in state_dir.glob("*.pid") if p.read_text().strip().isdigit()}


def kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    except (ProcessLookupError, PermissionError):
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    stall = float(os.environ.get("CLOUDE_SUITE_STALL_MINUTES", "15")) * 60
    cap = float(os.environ.get("CLOUDE_SUITE_MAX_MINUTES", "90")) * 60
    poll = float(os.environ.get("CLOUDE_SUITE_POLL_SECONDS", "5"))
    state, log = Path(a.state_dir), Path(a.log)
    state.mkdir(parents=True, exist_ok=True)
    for old in state.glob("*"):
        old.unlink()
    pids: set[int] = set()
    with open(log, "ab") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    pgid = proc.pid
    signalled = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: signalled.append(1))
    started = last_size = last_growth = None
    rc = None
    try:
        while (code := proc.poll()) is None and not signalled:
            now = time.time()
            pids |= descendants(proc.pid) | state_pids(state)
            size = log.stat().st_size if log.exists() else 0
            if started is None and any(m.encode() in log.read_bytes() for m in MARKERS):
                started = last_growth = now
                last_size = size
            if started is not None:
                if size != last_size:
                    last_size, last_growth = size, now
                why = None
                if now - last_growth > stall:
                    why, rc = f"log silent for {int((now - last_growth) / 60)} min", STALL_EXIT
                elif now - started > cap:
                    why, rc = f"wall-clock cap of {int(cap / 60)} min reached", CAP_EXIT
                if why:
                    msg = [f"suite_runner: {why}; killing this run's process group {pgid}", "tests running now:"]
                    msg += [f"  {t}" for t in running_tests(state)] or ["  (none recorded)"]
                    text = "\n".join(msg) + "\n"
                    sys.stderr.write(text)
                    with open(log, "a") as fh:
                        fh.write(text)
                    break
            time.sleep(poll)
        if rc is None:
            rc = 143 if signalled else code
        if proc.poll() is None:
            kill_group(proc)
        proc.wait()
    finally:
        killed = reap_tmux(pids | state_pids(state), tmux_socket_dir())
        if killed:
            sys.stderr.write(f"suite_runner: killed {len(killed)} leftover test tmux server(s)\n")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
