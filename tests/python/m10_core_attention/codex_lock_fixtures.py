
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Iterator

THREAD = "019a0000-0000-7000-8000-00000000c0de"
CWD = "/projects/codex-lock-test"
CHILD_WAIT_SECONDS = 10

_HOLDER_SCRIPT = (
    "import sys\n"
    "handles = [open(p) for p in sys.argv[1:]]\n"
    "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
    "sys.stdin.read()\n"
)


def make_codex_home(root: Path) -> Path:
    home = root / "codex-home"
    (home / "thread-writer-locks").mkdir(parents=True)
    state = sqlite3.connect(str(home / "state_5.sqlite"))
    state.execute("CREATE TABLE threads (id TEXT, thread_source TEXT, cwd TEXT, name TEXT, "
                  "archived INTEGER, rollout_path TEXT)")
    state.execute("INSERT INTO threads VALUES (?, 'user', ?, '', 0, '')", (THREAD, CWD))
    state.commit()
    state.close()
    hist = sqlite3.connect(str(home / "thread_history_1.sqlite"))
    hist.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, "
                 "status TEXT, error_json TEXT)")
    hist.execute("INSERT INTO thread_turns VALUES (?, 't0', 0, 'completed', NULL)", (THREAD,))
    hist.commit()
    hist.close()
    lock_path(home).write_text("")
    return home


def lock_path(home: Path) -> Path:
    return home / "thread-writer-locks" / ("%s.lock" % THREAD)


def spawn_holder(*paths: Path) -> subprocess.Popen:
    child = subprocess.Popen([sys.executable, "-c", _HOLDER_SCRIPT, *map(str, paths)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "ready"
    return child


def release(child: subprocess.Popen) -> None:
    if child.poll() is None:
        child.stdin.close()
        try:
            child.wait(timeout=CHILD_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=CHILD_WAIT_SECONDS)


def holding(*paths: Path) -> Iterator[subprocess.Popen]:
    child = spawn_holder(*paths)
    try:
        yield child
    finally:
        release(child)
