#!/usr/bin/env python3
import argparse
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

DEFAULT_CAP = 10
DEFAULT_TIMEOUT = 600
_PASS_LINE = re.compile(r"run-tests\.sh: FAIL \(parallel pass (\d+), serial pass (\d+)\)")


@dataclass
class Outcome:

    rc: int
    flakes: list[str] = field(default_factory=list)
    real: list[str] = field(default_factory=list)
    reran: bool = False


def parse_ids(text: str) -> list[str]:
    ids = [line.split(" ", 1)[1] for line in text.splitlines() if " " in line]
    return list(dict.fromkeys(i for i in ids if i))


def normal_failure(rc: int, log_text: str) -> bool:
    if rc != 1:
        return False
    m = _PASS_LINE.findall(log_text)
    return bool(m) and {int(m[-1][0]), int(m[-1][1])} <= {0, 1}


def rerun_ids(ids: list[str], cap: int, run_one: Callable[[str], bool]) -> Outcome:
    if not ids:
        return Outcome(rc=0)
    if cap <= 0 or len(ids) > cap:
        return Outcome(rc=1, real=list(ids))
    flakes, real = [], []
    for i in ids:
        (flakes if run_one(i) else real).append(i)
    return Outcome(rc=1 if real else 0, flakes=flakes, real=real, reran=True)


def decide(rc: int, log_text: str, ids: list[str], cap: int, run_one: Callable[[str], bool]) -> Outcome:
    if cap <= 0 or not ids or len(ids) > cap or not normal_failure(rc, log_text):
        return Outcome(rc=rc)
    return rerun_ids(ids, cap, run_one)


def make_runner(timeout: int, cwd: str) -> Callable[[str], bool]:
    env = {k: v for k, v in os.environ.items() if k not in ("CLOUDE_SUITE_FAILURES_FILE", "CLOUDE_SUITE_STATE_DIR")}

    def run_one(test_id: str) -> bool:
        cmd = [sys.executable, "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", test_id]
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            print(f"suite_rerun: TIMEOUT after {timeout} s: {test_id}", flush=True)
            return False
        print(f"suite_rerun: {'passed' if proc.returncode == 0 else 'FAILED'} alone: {test_id}", flush=True)
        if proc.returncode != 0:
            print("\n".join(out.splitlines()[-15:]), flush=True)
        return proc.returncode == 0

    return run_one


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rc", type=int, required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--failures", required=True)
    ap.add_argument("--flakes", required=True)
    ap.add_argument("--cap", type=int, default=int(os.environ.get("CLOUDE_SUITE_RERUN_MAX", DEFAULT_CAP)))
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("CLOUDE_SUITE_RERUN_TIMEOUT", DEFAULT_TIMEOUT)))
    a = ap.parse_args(argv)
    fails, log = Path(a.failures), Path(a.log)
    ids = parse_ids(fails.read_text(errors="replace")) if fails.exists() else []
    log_text = log.read_text(errors="replace") if log.exists() else ""
    if normal_failure(a.rc, log_text) and ids and len(ids) > a.cap > 0:
        print(f"suite_rerun: {len(ids)} failing ids is over the cap of {a.cap}; RED, no rerun", flush=True)
    out = decide(a.rc, log_text, ids, a.cap, make_runner(a.timeout, os.getcwd()))
    if out.reran:
        Path(a.flakes).write_text("".join(f"{i}\n" for i in out.flakes))
        fails.write_text("".join(f"FAILED {i}\n" for i in out.real))
        print(f"suite_rerun: {len(out.flakes)} flakes (failed in the parallel run, passed alone), "
              f"{len(out.real)} real failures", flush=True)
    return out.rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
