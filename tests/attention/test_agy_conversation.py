
from __future__ import annotations

from pathlib import Path

from src.config.agent_command import agent_command
from src.config.agents import AgentsConfig
from src.config.launch_profiles import AgentDefinition, CustomCommand, LaunchProfile
from src.core.attention import agy_conversation as agy

CONV = "f2b22ab5-ea8f-437d-a676-8ab9fcddcc16"
OTHER = "1c4ab425-f370-40f0-99cf-c28c63685f7a"


def _home(tmp_path: Path, log_lines: list[str], store: bool = True) -> Path:
    (tmp_path / "log").mkdir()
    (tmp_path / "conversations").mkdir()
    if store:
        (tmp_path / "conversations" / f"{CONV}.db").write_bytes(b"x")
    log = tmp_path / "log" / "cli-1.log"
    log.write_text("\n".join(log_lines) + "\n")
    return log


def test_log_names_the_last_conversation_the_user_talked_in(tmp_path):
    log = _home(tmp_path, [
        f"I1 server.go: Streaming conversation {OTHER}",
        f"I2 conversation_manager.go: Forwarding user message to conversation {CONV} (items=1, media=0)",
    ])
    assert agy.conversation_in_log(str(log)) == CONV


def test_no_message_or_no_store_is_no_answer(tmp_path):
    assert agy.conversation_in_log(str(_home(tmp_path, [f"Streaming conversation {CONV}"]))) is None
    other = tmp_path / "b"
    other.mkdir()
    gone = _home(other, [f"Forwarding user message to conversation {CONV} (items=1)"], store=False)
    assert agy.conversation_in_log(str(gone)) is None


def test_agy_is_found_below_the_pane_shell_only():
    parents, commands = {11: 10, 12: 11, 99: 1}, {11: "zsh", 12: "/Users/x/.local/bin/agy --model m", 99: "agy"}
    assert agy.agy_pid_under(10, parents, commands) == 12
    assert agy.agy_pid_under(99, parents, commands) == 99
    assert agy.agy_pid_under(None, parents, commands) is None
    assert agy.agy_pid_under(50, parents, commands) is None


def _profile() -> LaunchProfile:
    return LaunchProfile(
        id="antigravity", label="antigravity", harness="custom", custom_command=CustomCommand(script="agy --model m"), custom_command_ack_no_args=True,
        agent=AgentDefinition(process="agy", resume="agy --model m --conversation {id}"))


def _command(extra, approved, monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.agent_command.wrapper_scripts_dir", lambda _: tmp_path)
    return agent_command("antigravity", agents=AgentsConfig(), resolve_state_dir=lambda: str(tmp_path),
                         disable_alternate_screen=lambda: False, profiles=[_profile()], extra_args=extra,
                         approved_resume_prefixes=approved)


def test_a_recorded_conversation_resumes_through_the_profile_template(monkeypatch, tmp_path):
    command = _command(["--resume", CONV], ["agy"], monkeypatch, tmp_path)
    assert f"--conversation {CONV}" in command and "--resume" not in command


def test_unapproved_prefix_or_no_id_launches_plain(monkeypatch, tmp_path):
    assert "--conversation" not in _command(["--resume", CONV], [], monkeypatch, tmp_path)
    assert "--conversation" not in _command(None, ["agy"], monkeypatch, tmp_path)


def test_custom_closed_row_is_listed_without_an_id_and_a_claude_one_is_not(monkeypatch):
    from src.core import session_sleep, session_store

    base = {"lifecycle": "stopped", "lifecycle_source": "tmux_missing", "tmux_created_epoch": 5, "archived_at": None,
            "claude_session_uuid": None}
    rows = [{**base, "id": 1, "agent_family": "custom"}, {**base, "id": 2, "agent_family": "claude"}]
    monkeypatch.setattr(session_store, "list_sessions", lambda *a, **k: rows)
    assert [r["id"] for r in session_sleep.closed_rows(None)] == [1]


def test_an_agy_resume_command_reads_as_resumed():
    from src.core.session_resume_target import CONVERSATION_RESUMED, continuity_from_command

    assert continuity_from_command(f"zsh -c 'agy --model m --conversation {CONV}'") == CONVERSATION_RESUMED
