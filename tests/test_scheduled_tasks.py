
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_st_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_st_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core import scheduled_tasks  # noqa: E402
from src.core.scheduled_tasks import ScheduledTaskReader, parse_frontmatter  # noqa: E402


def _task(root: Path, folder: str, body: str) -> None:
    (root / folder).mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(body, encoding="utf-8")


def _run(projects: Path, name: str, stamp: str, conv: str) -> None:
    folder = projects / "-tmp-sched"
    folder.mkdir(parents=True, exist_ok=True)
    enqueue = {"type": "queue-operation", "operation": "enqueue", "timestamp": stamp,
               "sessionId": conv,
               "content": f'<scheduled-task name="{name}" file="/x/.claude/scheduled-tasks/{name}/SKILL.md">\n'}
    user = {"type": "user", "timestamp": stamp, "sessionId": conv, "isSidechain": False,
            "entrypoint": "claude-desktop", "promptSource": "sdk",
            "message": {"role": "user", "content": "placeholder"}}
    (folder / f"{conv}.jsonl").write_text(
        json.dumps(enqueue, separators=(",", ":")) + "\n" + json.dumps(user) + "\n", encoding="utf-8")


@pytest.fixture
def roots(tmp_path):
    tasks = tmp_path / "scheduled-tasks"
    projects = tmp_path / "projects"
    tasks.mkdir()
    projects.mkdir()
    _task(tasks, "nightly-check", "---\nname: nightly-check\ndescription: Check the placeholder fleet\n---\n\nbody text that says every night at 9pm\n")
    _task(tasks, "quoted", "---\nname: \"quoted task\"\ndescription: >\n  folded placeholder\n  description\nschedule: 0 9 * * *\n---\nbody\n")
    _task(tasks, "no-front", "just a body\n")
    _run(projects, "nightly-check", "2026-09-20T21:00:03.000Z", "c1")
    _run(projects, "nightly-check", "2026-09-26T21:00:05.000Z", "c2")
    return tasks, projects


def _read(roots):
    tasks, projects = roots
    return ScheduledTaskReader(tasks_dir=tasks, projects_dir=projects).read()


def test_tasks_carry_what_is_recorded_and_nothing_guessed(roots):
    result = _read(roots)
    assert result.state == "ok" and result.total == 3
    by = {task.id: task for task in result.tasks}
    nightly = by["nightly-check"]
    assert nightly.description == "Check the placeholder fleet"
    assert nightly.schedule is None and nightly.schedule_source == "not_recorded"
    assert nightly.next_run_at is None
    assert nightly.runs_recorded == 2 and nightly.last_run_at == "2026-09-26T21:00:05Z"
    quoted = by["quoted"]
    assert quoted.name == "quoted task" and quoted.description == "folded placeholder description"
    assert quoted.schedule == "0 9 * * *" and quoted.schedule_source == "frontmatter"
    assert by["no-front"].file_state == "no_frontmatter" and by["no-front"].name == "no-front"


def test_a_missing_folder_is_absent_not_empty(tmp_path):
    result = ScheduledTaskReader(tasks_dir=tmp_path / "nope", projects_dir=tmp_path).read()
    assert result.state == "absent" and result.tasks == []


def test_symlinks_and_unsafe_names_are_skipped(roots, tmp_path):
    tasks, _ = roots
    outside = tmp_path / "outside"
    _task(outside, "secret", "---\nname: secret\n---\n")
    os.symlink(outside / "secret", tasks / "linked-dir")
    _task(tasks, "linked-file", "placeholder")
    (tasks / "linked-file" / "SKILL.md").unlink()
    os.symlink(outside / "secret" / "SKILL.md", tasks / "linked-file" / "SKILL.md")
    _task(tasks, ".hidden", "---\nname: h\n---\n")
    result = _read(roots)
    ids = {task.id for task in result.tasks}
    assert "linked-dir" not in ids and ".hidden" not in ids
    linked = next(task for task in result.tasks if task.id == "linked-file")
    assert linked.file_state == "unreadable" and linked.description is None


def test_the_listing_is_bounded(roots, monkeypatch):
    tasks, _ = roots
    monkeypatch.setattr(scheduled_tasks, "MAX_TASKS", 2)
    _task(tasks, "big", "---\nname: big\n---\n" + "x" * (scheduled_tasks.MAX_SKILL_BYTES + 10))
    result = _read(roots)
    assert len(result.tasks) == 2 and result.total == 4 and result.truncated


def test_an_oversized_skill_file_is_named(roots, monkeypatch):
    tasks, _ = roots
    _task(tasks, "big", "---\nname: big\n---\n" + "x" * (scheduled_tasks.MAX_SKILL_BYTES + 10))
    big = next(task for task in _read(roots).tasks if task.id == "big")
    assert big.file_state == "too_large"


def test_descriptions_are_redacted(roots):
    tasks, _ = roots
    key = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    _task(tasks, "leaky", f"---\nname: leaky\ndescription: uses {key}\n---\n")
    leaky = next(task for task in _read(roots).tasks if task.id == "leaky")
    assert key not in leaky.description and "[redacted]" in leaky.description


def test_the_answer_is_cached_for_its_ttl(roots):
    tasks, projects = roots
    clock = [0.0]
    reader = ScheduledTaskReader(tasks_dir=tasks, projects_dir=projects, clock=lambda: clock[0])
    first = reader.read()
    _task(tasks, "added", "---\nname: added\n---\n")
    assert reader.read() is first
    clock[0] = scheduled_tasks.TTL_SECONDS + 1
    assert reader.read().total == first.total + 1


def test_frontmatter_parser_refuses_an_unclosed_block():
    assert parse_frontmatter("---\nname: a\n") is None
    assert parse_frontmatter("name: a\n---\n") is None


def test_the_route_answers_the_reader(roots, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    tasks, projects = roots
    monkeypatch.setattr(scheduled_tasks, "READER",
                        ScheduledTaskReader(tasks_dir=tasks, projects_dir=projects))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    body = TestClient(app).get("/api/v1/scheduled-tasks").json()
    assert body["state"] == "ok" and len(body["tasks"]) == 3
    assert all("/" not in (task["description"] or "") for task in body["tasks"])
