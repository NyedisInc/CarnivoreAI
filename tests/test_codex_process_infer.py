
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.core import session_agent_infer_sweep as sweep_mod
from src.core.agent_family_display import (
    FAMILY_SOURCE_INFERRED_PROCESS,
    resolve_family_for_display,
)
from src.core.claude_resume_argv import ProcessRow
from src.core.codex_process_infer import is_codex_command
from src.core.db_models import (
    SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
    SESSION_FAMILY_SOURCE_LAUNCHED,
    SESSION_FAMILY_SOURCE_UNKNOWN,
)
from src.core.session_agent_evidence import choose_agent_evidence
from src.core.session_agent_infer import (
    INFER_FAMILY,
    INFER_NOT_CLAUDE,
    INFER_UNAVAILABLE,
    restart_agent_type,
)
from src.core.session_agent_infer_families import infer_pane_agent
from src.core.session_agent_infer_resweep import AgentResweep

NODE_LAUNCHER = "node /Users/x/.nvm/versions/node/v22.22.0/bin/codex --yolo"
NATIVE = (
    "/Users/x/.nvm/versions/node/v22.22.0/lib/node_modules/@openai/codex/"
    "node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex --yolo"
)
HELPER = NATIVE.replace("bin/codex --yolo", "bin/codex-code-mode-host")

CODEX_PANE = [
    ProcessRow(pid=4441, ppid=1, command=NODE_LAUNCHER),
    ProcessRow(pid=4237, ppid=4441, command=NATIVE),
    ProcessRow(pid=4337, ppid=4237, command=HELPER),
]
SHELL_PANE = [ProcessRow(pid=300, ppid=1, command="-zsh")]
CLAUDE_PANE = [
    ProcessRow(pid=100, ppid=1, command="/bin/zsh -l"),
    ProcessRow(pid=200, ppid=100, command="/Users/x/.local/bin/claude --chrome"),
]


def infer(pid, table, current=None):
    return infer_pane_agent(
        pane_pid=pid, table=table, pane_current_command=current, wrappers=[]
    )




@pytest.mark.parametrize(
    "command",
    [HELPER, "my-codex --yolo", "node server.js", "vim codex", "/bin/zsh -l", ""],
)
def test_a_process_that_is_not_codex_does_not_match(command):
    assert is_codex_command(command) is False


def test_a_plain_shell_pane_stays_unnamed():
    verdict = infer(300, SHELL_PANE, current="zsh")
    assert verdict.family is None
    assert verdict.named is False
    assert verdict.inference.outcome == INFER_NOT_CLAUDE


def test_a_node_pane_command_alone_creates_nothing():
    verdict = infer(300, SHELL_PANE, current="node")
    assert verdict.named is False


def test_an_unread_table_asks_no_reader_and_names_nothing():
    verdict = infer(4441, None)
    assert verdict.family is None
    assert verdict.inference.outcome == INFER_UNAVAILABLE


def test_a_claude_pane_still_answers_claude():
    verdict = infer(100, CLAUDE_PANE)
    assert verdict.family == "claude"
    assert verdict.inference.agent_type == "claude"




@pytest.mark.parametrize("command", [NODE_LAUNCHER, NATIVE, "codex --yolo"])
def test_both_measured_codex_shapes_match(command):
    assert is_codex_command(command) is True


def test_the_measured_codex_pane_is_named_codex_as_an_inference():
    verdict = infer(4441, CODEX_PANE, current="node")
    assert verdict.named is True
    assert verdict.family == "codex"
    assert verdict.inference.outcome == INFER_FAMILY
    assert verdict.inference.agent_type == "codex"
    assert verdict.inference.family_source == SESSION_FAMILY_SOURCE_INFERRED_PROCESS


def test_codex_under_a_zsh_c_parent_is_found():
    table = [ProcessRow(pid=10, ppid=1, command="zsh -c codex --yolo")] + [
        ProcessRow(pid=r.pid, ppid=10 if r.pid == 4441 else r.ppid, command=r.command)
        for r in CODEX_PANE
    ]
    assert infer(10, table).family == "codex"


def test_a_pane_whose_own_command_is_codex_corroborates():
    assert infer(300, SHELL_PANE, current="codex").family == "codex"


def test_the_inference_is_shown_dashed_and_never_reaches_the_restart_ladder():
    evidence = choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type="codex",
        row_family_source=SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
    )
    assert evidence.agent_type == "codex"
    assert evidence.from_process is True
    family, source = resolve_family_for_display(
        "codex", [], from_process=evidence.from_process
    )
    assert family.name == "codex"
    assert source == FAMILY_SOURCE_INFERRED_PROCESS
    assert restart_agent_type("codex", SESSION_FAMILY_SOURCE_INFERRED_PROCESS) is None




@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "s.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE sessions (session_uuid TEXT PRIMARY KEY, tmux_socket TEXT, "
        "tmux_name TEXT, tmux_created_epoch INTEGER, agent_type TEXT, "
        "agent_family TEXT, agent_family_source TEXT)"
    )
    c.executemany(
        "INSERT INTO sessions VALUES (?, 's', ?, 1, ?, ?, ?)",
        [
            ("u-codex", "cloude_AdBoard", None, None, SESSION_FAMILY_SOURCE_UNKNOWN),
            ("u-shell", "cloude_shell", None, None, SESSION_FAMILY_SOURCE_UNKNOWN),
            ("u-launched", "cloude_launched", "codex-yolo", "codex",
             SESSION_FAMILY_SOURCE_LAUNCHED),
        ],
    )
    c.commit()
    c.close()
    return path


def _manager(path):

    def connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    return SimpleNamespace(
        _tmux_socket_name=lambda: "s", _writable_datastore_connection=connect
    )


def _rows(path):
    c = sqlite3.connect(path)
    out = {
        r[0]: r[1:]
        for r in c.execute(
            "SELECT session_uuid, agent_type, agent_family, agent_family_source "
            "FROM sessions"
        )
    }
    c.close()
    return out


def test_the_sweep_names_the_codex_row_and_leaves_the_rest(db, monkeypatch):
    panes = [
        {"name": "cloude_AdBoard", "created_at_epoch": 1, "pid": 4441,
         "pane_current_command": "node"},
        {"name": "cloude_shell", "created_at_epoch": 1, "pid": 300,
         "pane_current_command": "zsh"},
        {"name": "cloude_launched", "created_at_epoch": 1, "pid": 100,
         "pane_current_command": "claude"},
    ]
    monkeypatch.setattr(sweep_mod, "_live_pane_rows", lambda _m: panes)
    examined, written = sweep_mod.sweep_live_sessions(
        _manager(db),
        table_reader=lambda: CODEX_PANE + SHELL_PANE + CLAUDE_PANE,
        wrappers_reader=lambda: [],
    )
    assert (examined, written) == (2, 1)
    rows = _rows(db)
    assert rows["u-codex"] == ("codex", "codex", SESSION_FAMILY_SOURCE_INFERRED_PROCESS)
    assert rows["u-shell"] == (None, None, SESSION_FAMILY_SOURCE_UNKNOWN)
    assert rows["u-launched"] == ("codex-yolo", "codex", SESSION_FAMILY_SOURCE_LAUNCHED)




def _infos(*families):
    return [SimpleNamespace(agent_family=f) for f in families]


def _booted(done=True):
    return SimpleNamespace(
        _boot_readopt_task=SimpleNamespace(done=lambda: done)
    )


def test_the_resweep_runs_only_when_a_row_is_unknown_and_is_rate_bounded():
    calls = []
    now = [1000.0]
    mgr = _booted()
    resweep = AgentResweep(
        interval=60.0, clock=lambda: now[0], sweep=lambda m: calls.append(m) or (1, 0)
    )

    async def run():
        assert resweep.maybe_schedule(mgr, _infos("claude", "codex")) is None
        task = resweep.maybe_schedule(mgr, _infos("claude", None))
        assert task is not None
        assert resweep.maybe_schedule(mgr, _infos(None)) is None
        await task
        now[0] += 30
        assert resweep.maybe_schedule(mgr, _infos(None)) is None
        now[0] += 31
        again = resweep.maybe_schedule(mgr, _infos(None))
        assert again is not None
        await again

    asyncio.run(run())
    assert calls == [mgr, mgr]


def test_nothing_is_resweeped_before_the_boot_pass_has_finished():
    calls = []
    resweep = AgentResweep(sweep=lambda m: calls.append(m) or (0, 0))

    async def run():
        assert resweep.maybe_schedule(SimpleNamespace(_boot_readopt_task=None), _infos(None)) is None
        assert resweep.maybe_schedule(_booted(done=False), _infos(None)) is None

    asyncio.run(run())
    assert calls == []


def test_a_failing_sweep_is_logged_not_raised():
    def boom(_m):
        raise RuntimeError("tmux gone")

    resweep = AgentResweep(sweep=boom)

    async def run():
        await resweep.maybe_schedule(_booted(), _infos(None))

    asyncio.run(run())
