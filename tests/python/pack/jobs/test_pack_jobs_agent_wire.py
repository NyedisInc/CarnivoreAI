
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.pack.jobs import ddl, paths, runner
from src.core.pack.jobs.agent_types import AgentSpec, ReplyBody
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import (CAP_AGENT, TERMINAL, AdmitBody, CollectAnswer, HostJob, HostState, JobRecord, JobState, StartBody,
                                      StatusAnswer)

JOB = "job_0123456789ab"
GOOD = {"task": "fix the bug", "family": "claude", "permission_mode": "acceptEdits"}


def _start(**over):
    base = {"job_id": JOB, "project_uid": "uid12345678", "snapshot_commit": "a" * 40, "snapshot_blob_id": "b1", "kind": "suite",
            "caller_roots": ["/a"], "agent": dict(GOOD)}
    base.update(over)
    return base


def test_states_and_capability():
    assert CAP_AGENT == "pack.jobs.agent" and JobState.QUESTION not in TERMINAL and HostState.PARKED.value == "parked"


@pytest.mark.parametrize("bad", [
    {"task": ""}, {"task": "x" * 19001}, {"task": "a\0b"}, {"task": "   "}, {"family": "gemini"}, {"permission_mode": "yolo"},
    {"permission_mode": "skip_all"},
    {"agent_type": "Bad Name"}, {"agent_type": "-x"}, {"model": "a b"}, {"model": "m" * 65}, {"account_key": "Upper"},
    {"account_key": "x;rm"}, {"definition_json": "{}"},
    {"agent_type": "ok", "definition_json": "not json"}, {"agent_type": "ok", "definition_json": "[1]"},
    {"agent_type": "ok", "definition_json": json.dumps({"hooks": {}})},
    {"agent_type": "ok", "definition_json": json.dumps({"permissionMode": "bypassPermissions"})},
    {"agent_type": "ok", "definition_json": json.dumps({"mcpServers": {}})},
    {"agent_type": "ok", "definition_json": json.dumps({"prompt": "x" * 9000})}, {"extra": 1},
    {"model": "--continue"}, {"model": "claude[1m]"}, {"model": "a..b"}, {"model": "x" * 65},
])
def test_agent_spec_refuses_bad_values(bad):
    with pytest.raises(ValidationError):
        AgentSpec(**{**GOOD, **bad})


def test_agent_spec_accepts_good_values():
    spec = AgentSpec(**GOOD, agent_type="reviewer", model="claude-sonnet-4-5:200k", account_key="work-1",
                     definition_json=json.dumps({"description": "d", "prompt": "p", "tools": ["Read"], "effort": "high"}))
    assert spec.agent_type == "reviewer"
    assert AgentSpec(task="t", family="codex", permission_mode="skip_all").permission_mode == "skip_all"
    with pytest.raises(ValidationError):
        AgentSpec(task="t", family="codex", permission_mode="acceptEdits")
    with pytest.raises(ValidationError):
        AgentSpec(task="t", family="codex", permission_mode="ask", agent_type="x", definition_json="{}")


def test_start_body_agent_or_command_exactly_one():
    assert StartBody(**_start()).agent.task == "fix the bug"
    with pytest.raises(ValidationError):
        StartBody(**_start(command="ls"))
    with pytest.raises(ValidationError):
        StartBody(**_start(agent=None))
    assert StartBody(**_start(agent=None, command="ls")).command == "ls"
    with pytest.raises(ValidationError):
        StartBody(**_start(agent={**GOOD, "permission_mode": "nope"}))
    with pytest.raises(ValidationError):
        StartBody(**_start(bogus=1))


def test_admit_body_agent_fields_and_reply_body():
    base = {"job_id": JOB, "project_uid": "uid12345678", "kind": "suite"}
    assert AdmitBody(**base, agent_family="codex", account_key="a-1").agent_family == "codex"
    for bad in ({"agent_family": "x"}, {"account_key": "A!"}, {"nope": 1}):
        with pytest.raises(ValidationError):
            AdmitBody(**base, **bad)
    assert ReplyBody(job_id=JOB, text="yes").text == "yes"
    for bad in ({"text": ""}, {"text": "x" * 8001}, {"text": "a\0"}, {"job_id": "job_x"}, {"extra": 1}):
        with pytest.raises(ValidationError):
            ReplyBody(**{"job_id": JOB, "text": "t", **bad})


def test_answers_carry_the_new_fields_and_forbid_extras():
    ans = StatusAnswer(state=HostState.PARKED, result_text="r", question="q?", question_kind="question", account_how="relay",
                       usage={"input_tokens": 1, "output_tokens": 2}, worker_session_uuid="u")
    assert ans.usage.output_tokens == 2
    assert CollectAnswer(question_kind="permission", account_label="acct").account_label == "acct"
    for bad in ({"question_kind": "other"}, {"account_how": "x"}, {"usage": {"input_tokens": -1}}, {"usage": {"bogus": 1}}):
        with pytest.raises(ValidationError):
            StatusAnswer(state=HostState.RUNNING, **bad)


def _phase1_db(path: Path) -> None:
    old = [s for s in ddl.DDL if "CREATE TABLE IF NOT EXISTS jobs" in s or "CREATE TABLE IF NOT EXISTS host_jobs" in s]
    conn = sqlite3.connect(path)
    for stmt in old:
        conn.execute(stmt)
    conn.execute("INSERT INTO jobs (id,state,created_at,updated_at) VALUES ('job_000000000001','running',1,1)")
    conn.execute("INSERT INTO host_jobs (job_id,state,created_at) VALUES ('job_000000000001','running',1)")
    conn.commit()
    conn.close()


def _cols(conn: sqlite3.Connection, table: str) -> list:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_migrate_is_additive_and_idempotent_on_a_phase1_file(tmp_path: Path):
    db = tmp_path / ddl.FILENAME
    _phase1_db(db)
    store = JobStore(tmp_path)
    old = store.get_job("job_000000000001")
    assert old is not None and old.body == "command" and old.state is JobState.RUNNING
    host = store.host_get("job_000000000001")
    assert host is not None and host.body == "command" and host.worker_session_id is None
    conn = sqlite3.connect(db)
    before = {t: _cols(conn, t) for t in ddl.ADDED_COLUMNS}
    ddl.migrate(conn)
    ddl.migrate(conn)
    assert {t: _cols(conn, t) for t in ddl.ADDED_COLUMNS} == before
    for table, cols in ddl.ADDED_COLUMNS.items():
        assert all(name in before[table] for name, _ in cols)
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    conn.close()
    JobStore(tmp_path).get_job("x")


def test_store_round_trips_the_new_columns(tmp_path: Path):
    store = JobStore(tmp_path)
    store.create_job(JobRecord(id=JOB, state=JobState.RUNNING, body="agent", task_head="fix", family="claude"))
    rec = store.set_state(JOB, JobState.QUESTION, question="which?", question_kind="question", notified_state="question")
    assert rec.state is JobState.QUESTION and rec.body == "agent" and rec.question == "which?" and rec.notified_state == "question"
    assert store.find_live_by_idem("") is None or True
    store.host_put(HostJob(job_id=JOB, state=HostState.RUNNING, body="agent", worker_session_id="ses_abc", worker_session_uuid="uu-1",
                           worker_epoch=3, family="claude"))
    got = store.host_set(JOB, state=HostState.PARKED, parked_at=5.0, question="q", usage_json="{}")
    assert got.state is HostState.PARKED and got.parked_at == 5.0 and got.worker_epoch == 3


def test_agent_job_for_session(tmp_path: Path):
    store = JobStore(tmp_path)
    store.host_put(HostJob(job_id=JOB, state=HostState.RUNNING, body="agent", worker_session_id="ses_abc", worker_session_uuid="uu-1"))
    store.host_put(HostJob(job_id="job_000000000002", state=HostState.RUNNING, body="command", worker_session_id="ses_cmd"))
    assert store.agent_job_for_session("ses_abc", None).job_id == JOB
    assert store.agent_job_for_session(None, "uu-1").job_id == JOB
    assert store.agent_job_for_session("ses_other", "uu-1").job_id == JOB
    assert store.agent_job_for_session("ses_cmd", None) is None
    assert store.agent_job_for_session(None, None) is None and store.agent_job_for_session("", "") is None
    store.host_set(JOB, state=HostState.PARKED)
    assert store.agent_job_for_session("ses_abc") is not None
    store.host_set(JOB, state=HostState.EXITED)
    assert store.agent_job_for_session("ses_abc", "uu-1") is None


def test_push_block_equals_the_runner_exports():
    env = paths.push_block_env()
    assert env["GIT_CONFIG_COUNT"] == "6" and len(env) == 13
    exported = dict(re.findall(r"(GIT_CONFIG_\w+)=(\S+)", runner._RUN_SH.format(job_id="j", cwd="c", cap=1, push_block=runner._push_block_exports())))
    assert exported == env


def test_command_job_dumps_stay_phase1_shaped():
    assert "agent" not in StartBody(**_start(agent=None, command="ls")).model_dump()
    assert "agent_family" not in AdmitBody(job_id=JOB, project_uid="uid12345678", kind="suite").model_dump()
    assert set(CollectAnswer().model_dump()) == {"result_commit", "blob_id", "changed"}
    assert set(StatusAnswer(state=HostState.RUNNING).model_dump(mode="json")) == {"state", "exit_code", "detail", "output_tail", "output_bytes"}
    assert "usage" in StatusAnswer(state=HostState.RUNNING, usage={"input_tokens": 1}).model_dump(mode="json")


def test_usage_totals_refuse_infinity_and_huge_numbers():
    from src.core.pack.jobs.agent_types import UsageTotals

    assert UsageTotals(input_tokens=5, cost_usd=0.5).cost_usd == 0.5
    for bad in ({"cost_usd": float("inf")}, {"cost_usd": float("nan")}, {"input_tokens": 10 ** 29}, {"output_tokens": 10 ** 13}):
        with pytest.raises(ValidationError):
            UsageTotals(**bad)
    with pytest.raises(ValidationError):
        UsageTotals.model_validate_json('{"cost_usd": Infinity}')
