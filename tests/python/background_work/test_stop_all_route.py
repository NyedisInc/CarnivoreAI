
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import textwrap
import time
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bga_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bga_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.background_work.attribution import read_owners  # noqa: E402
from src.core.conversation_writers import read_process_table  # noqa: E402
from src.core.tmux_discovery import tmux_argv_prefix  # noqa: E402

TASKS = ("bstopaaa1", "bstopbbb2", "bkeepccc3")

AGENT = textwrap.dedent('''
    work="$1"
    mkdir -p "$work/tasks"
    for id in %s; do
      /bin/sh -c 'sleep 600 & wait' > "$work/tasks/$id.output" 2>&1 &
      echo "$id $!" >> "$work/pids.tmp"
    done
    sleep 0.3
    mv "$work/pids.tmp" "$work/pids.txt"
    wait
''' % " ".join(TASKS))


def _alive(pid: int) -> bool:
    done = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(pid)],
                          capture_output=True, text=True, check=False)
    state = done.stdout.strip()
    return bool(state) and not state.startswith("Z")


@pytest.fixture
def pane(tmp_path, tmux_test_socket):
    agent_sh = tmp_path / "agent.sh"
    agent_sh.write_text(AGENT)
    name = f"bga_{uuid.uuid4().hex[:8]}"
    prefix = tmux_argv_prefix(tmux_test_socket)
    subprocess.run(prefix + ["-f", "/dev/null", "new-session", "-d", "-s", name, "-x", "80",
                             "-y", "24",
                             f"bash -c 'exec -a claude /bin/bash \"$0\" \"$1\"' "
                             f"'{agent_sh}' '{tmp_path}'"],
                   check=True, capture_output=True, timeout=15)
    pids_path = tmp_path / "pids.txt"
    deadline = time.monotonic() + 15
    while not pids_path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert pids_path.exists(), "the stand-in agent never started"
    shells = {line.split()[0]: int(line.split()[1]) for line in pids_path.read_text().splitlines()}
    table = read_process_table()
    kids = {task: table.children[pid][0] for task, pid in shells.items()}
    stranger = subprocess.Popen(["/bin/sleep", "600"])
    yield name, tmux_test_socket, shells, kids, stranger.pid
    stranger.kill()
    stranger.wait(timeout=5)
    subprocess.run(prefix + ["kill-session", "-t", f"={name}"], capture_output=True, timeout=15)
    for pid in list(shells.values()) + list(kids.values()):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class _Manager:

    def __init__(self, name: str, socket: str) -> None:
        self._name = name
        self._socket = socket

    async def get_session_info(self, session_id=None):
        if session_id != "ses_bga":
            return None
        return SimpleNamespace(agent_family="claude", tmux_session=self._name, session=None)

    def tmux_socket_name(self) -> str:
        return self._socket

    def _claude_uuid_for_tmux_name(self, tmux_name: str):
        return None


def _client(manager):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = manager
    return TestClient(app)


def test_stop_all_stops_only_the_named_and_guarded(pane):
    name, socket, shells, kids, stranger = pane
    client = _client(_Manager(name, socket))
    listed = client.get("/api/v1/sessions/ses_bga/background-work").json()
    assert listed["state"] == "ok" and listed["owners"] == "absent"
    rows = {row["task_id"]: row for row in listed["processes"]}
    assert set(rows) == set(TASKS)
    assert all(row["agent_id"] is None for row in rows.values())
    table = read_process_table()
    agent = table.rows[shells[TASKS[0]]].ppid

    def start_of(pid: int) -> str:
        return " ".join(table.rows[pid].lstart.split())

    targets = [{"pid": rows[t]["pid"], "start": rows[t]["start"]} for t in TASKS[:2]]
    targets += [{"pid": agent, "start": start_of(agent)},
                {"pid": stranger, "start": start_of(stranger)}]
    assert client.post("/api/v1/sessions/ses_bga/background-work/terminate-all",
                       json={"targets": []}).status_code == 422
    answer = client.post("/api/v1/sessions/ses_bga/background-work/terminate-all",
                         json={"targets": targets})
    assert answer.status_code == 200, answer.text
    results = {r["pid"]: r for r in answer.json()["results"]}
    for task in TASKS[:2]:
        assert results[shells[task]]["outcome"] == "terminated", results
        assert not _alive(shells[task]) and not _alive(kids[task])
    assert results[agent]["outcome"] == "refused" and results[agent]["code"] == "pane_process"
    assert results[stranger]["outcome"] == "refused"
    assert results[stranger]["code"] == "not_descendant"
    assert _alive(agent) and _alive(stranger)
    assert _alive(shells[TASKS[2]]) and _alive(kids[TASKS[2]]), "an unnamed shell was stopped"


def _launch(task_id: str, n: int, agent: str | None) -> dict:
    record = {"parentUuid": f"p{n}", "isSidechain": agent is not None, "type": "user",
              "uuid": f"u{n}", "timestamp": "2026-09-28T16:00:0%dZ" % n,
              "sessionId": "7934883d-4a9e-46ca-8516-10788d83b345", "cwd": "/w",
              "message": {"role": "user", "content": [
                  {"tool_use_id": f"toolu_{task_id}", "type": "tool_result",
                   "content": f"Command running in background with ID: {task_id}. Output is "
                              f"being written to: /t/tasks/{task_id}.output"}]},
              "toolUseResult": {"stdout": "", "stderr": "", "interrupted": False,
                                "backgroundTaskId": task_id}}
    if agent is not None:
        record["agentId"] = agent
    return record


def test_a_sub_agent_owns_the_shells_its_file_recorded(tmp_path):
    conversation = "7934883d-4a9e-46ca-8516-10788d83b345"
    project = tmp_path / "projects" / "-w"
    (project / conversation / "subagents").mkdir(parents=True)
    (project / f"{conversation}.jsonl").write_text(json.dumps(_launch("bparent01", 1, None)) + "\n")
    (project / conversation / "subagents" / "agent-a1b2c3.jsonl").write_text(
        json.dumps(_launch("bsubagnt1", 2, "a1b2c3")) + "\n")
    owners = read_owners(conversation, working_dir="/w", projects_dir=tmp_path / "projects")
    assert owners.state == "ok"
    assert owners.owner_of("bsubagnt1") == "a1b2c3"
    assert owners.owner_of("bparent01") is None
    missing = read_owners("056cd146-57dd-4192-80f4-e5026cf33f9c", working_dir="/w",
                          projects_dir=tmp_path / "projects")
    assert missing.state == "absent" and missing.owner_of("bsubagnt1") is None
