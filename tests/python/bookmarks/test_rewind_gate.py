
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core import restart_live_gate
from src.core.bookmarks import actions, locate, rows
from src.core.bookmarks.errors import NotClaudeSession, RewindRefused
from src.core.session_respawn import resolve_respawn_plan
from tests.python.bookmarks import fixtures

PACKAGE = Path(__file__).resolve().parents[3] / "src" / "core" / "bookmarks"


class FakeManager:

    def __init__(self, db: Path, result: dict) -> None:
        self.db, self.result, self.calls = db, result, []

    def tmux_socket_name(self) -> str:
        return "test_sock"

    async def respawn_session(self, name: str, **kwargs) -> dict:
        conversation = fixtures.row_conversation(self.db)[0]
        self.calls.append((name, kwargs, conversation))
        result = dict(self.result)
        if result.get("command") == "RESUME":
            result["command"] = f"claude --resume {conversation}"
        return result


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    source = fixtures.write_transcript(root)
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    monkeypatch.setattr(rows, "db_path", lambda: db)
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "codex" if agent_type == "codex" else "claude")
    return {"db": db, "source": source, "folder": source.parent}


def _live(monkeypatch, value):
    monkeypatch.setattr(restart_live_gate, "bound_instance_running", lambda *a, **k: value)


def _rewind(manager, confirm=True, entry="u2"):
    return asyncio.run(actions.rewind(manager, session_uuid="row-uuid-1", entry_uuid=entry, confirm=confirm))


def test_refused_without_confirm_and_nothing_is_touched(env, monkeypatch):
    _live(monkeypatch, True)
    manager = FakeManager(env["db"], {"ok": True})
    with pytest.raises(RewindRefused) as err:
        _rewind(manager, confirm=False)
    assert (err.value.status, err.value.code) == (400, "confirm_required")
    assert manager.calls == [] and sorted(env["folder"].iterdir()) == [env["source"]]
    assert fixtures.row_conversation(env["db"])[0] == fixtures.SOURCE


@pytest.mark.parametrize("measured", [False, None])
def test_refused_unless_the_row_is_measured_live(env, monkeypatch, measured):
    _live(monkeypatch, measured)
    manager = FakeManager(env["db"], {"ok": True})
    with pytest.raises(RewindRefused) as err:
        _rewind(manager)
    assert err.value.code == "not_live"
    assert manager.calls == [] and sorted(env["folder"].iterdir()) == [env["source"]]


def test_a_codex_session_is_refused_by_name(env, monkeypatch, tmp_path):
    _live(monkeypatch, True)
    db = fixtures.make_datastore(tmp_path / "codex.db", agent_type="codex")
    monkeypatch.setattr(rows, "db_path", lambda: db)
    with pytest.raises(NotClaudeSession, match="codex"):
        _rewind(FakeManager(db, {"ok": True}))


def test_a_confirmed_live_rewind_moves_the_row_then_restarts_through_the_ladder(env, monkeypatch):
    _live(monkeypatch, True)
    manager = FakeManager(env["db"], {"ok": True, "killed_live_pane": True, "kind": "agent",
                                      "command": "RESUME", "identity_status": "verified"})
    done = _rewind(manager)
    [(name, kwargs, at_call)] = manager.calls
    assert name == "cloude_fixture" and kwargs == {"live_restart_confirmed": True}
    assert at_call == done["claude_session_uuid"] != fixtures.SOURCE
    assert fixtures.row_conversation(env["db"]) == (done["claude_session_uuid"], "bookmark_rewind")
    assert done["resumed_copy"] and done["killed_live_pane"] and done["previous_claude_session_uuid"] == fixtures.SOURCE
    assert (env["folder"] / f"{done['claude_session_uuid']}.jsonl").is_file() and env["source"].is_file()


def test_a_refused_respawn_puts_the_row_back_and_removes_the_copy(env, monkeypatch):
    _live(monkeypatch, True)
    manager = FakeManager(env["db"], {"ok": False, "killed_live_pane": False, "kind": "cannot_determine",
                                      "detail": "tmux did not answer"})
    with pytest.raises(RewindRefused, match="tmux did not answer"):
        _rewind(manager)
    assert fixtures.row_conversation(env["db"]) == (fixtures.SOURCE, "registry")
    assert sorted(env["folder"].iterdir()) == [env["source"]]


def test_minus_k_comes_only_from_the_plan():
    live = dict(probe_ok=True, pane_dead="0", pane_start_command='"cld"', agent_command="cld")
    assert resolve_respawn_plan(**live, live_restart_confirmed=True).kills_live_pane is True
    assert resolve_respawn_plan(**live).kills_live_pane is False
    assert resolve_respawn_plan(**{**live, "pane_dead": "1"}, live_restart_confirmed=True).kills_live_pane is False
    source = "\n".join(p.read_text() for p in PACKAGE.glob("*.py"))
    assert "respawn-pane" not in source and "_run_tmux" not in source and '"-k"' not in source
