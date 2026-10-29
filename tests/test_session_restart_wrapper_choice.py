
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_models import SESSION_ORIGIN_OBSERVED  # noqa: E402
from src.core.session_agent_choice import (  # noqa: E402
    CHOICE_ACCEPTED,
    CHOICE_CANNOT_DETERMINE,
    CHOICE_UNKNOWN,
    validate_agent_choice,
)
from src.core.session_identity import record_instance  # noqa: E402
from src.core.session_respawn import (  # noqa: E402
    RESPAWN_AGENT,
    RESPAWN_TRANSCRIPT_MISSING,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_NOT_DEAD,
    RESPAWN_SHELL,
    resolve_respawn_plan,
)
from src.core.session_restart_preview import (  # noqa: E402
    WRAPPERS_OK,
    WRAPPERS_UNAVAILABLE,
    WrapperOffer,
    build_restart_preview,
)
from tests.s7_helpers import migrated_connection  # noqa: E402
from tests.socket_guard import derive_test_socket  # noqa: E402




def test_a_picked_wrapper_beats_an_empty_start_command():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command="",
        agent_command=None,
        chosen_agent_command="run-claude-chrome",
        chosen_agent_type="claude-chrome",
    )
    assert plan.kind == RESPAWN_AGENT
    assert plan.command == "run-claude-chrome"
    assert plan.chosen is True
    assert "plain shell" in plan.detail
    assert "claude-chrome" in plan.detail


def test_a_picked_wrapper_beats_an_unreadable_start_command():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command=None,
        agent_command=None,
        chosen_agent_command="run-claude-chrome",
        chosen_agent_type="claude-chrome",
    )
    assert plan.kind == RESPAWN_AGENT
    assert plan.chosen is True
    assert "did not report a start command" in plan.detail


def test_a_picked_wrapper_replaces_the_stored_one():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="1",
        pane_start_command='"cld"',
        agent_command="cld",
        chosen_agent_command="run-claude-chrome",
        chosen_agent_type="claude-chrome",
    )
    assert plan.command == "run-claude-chrome"
    assert plan.chosen is True


def test_a_picked_wrapper_never_revives_a_live_pane():
    plan = resolve_respawn_plan(
        probe_ok=True,
        pane_dead="0",
        pane_start_command="",
        agent_command=None,
        chosen_agent_command="run-claude-chrome",
        chosen_agent_type="claude-chrome",
    )
    assert plan.kind == RESPAWN_NOT_DEAD
    assert plan.actionable is False
    assert plan.command is None
    assert plan.chosen is False


def test_a_picked_wrapper_never_overrides_a_probe_that_did_not_answer():
    plan = resolve_respawn_plan(
        probe_ok=False,
        pane_dead=None,
        pane_start_command=None,
        agent_command=None,
        chosen_agent_command="run-claude-chrome",
        chosen_agent_type="claude-chrome",
    )
    assert plan.kind == RESPAWN_CANNOT_DETERMINE
    assert plan.actionable is False
    assert plan.chosen is False


def test_no_choice_leaves_the_ladder_byte_for_byte_as_it_was():
    assert (
        resolve_respawn_plan(
            probe_ok=True,
            pane_dead="1",
            pane_start_command="",
            agent_command="cld",
        ).kind
        == RESPAWN_SHELL
    )
    assert (
        resolve_respawn_plan(
            probe_ok=True,
            pane_dead="1",
            pane_start_command='"cld"',
            agent_command=None,
        ).kind
        == "replay"
    )
    assert (
        resolve_respawn_plan(
            probe_ok=True,
            pane_dead="1",
            pane_start_command="",
            agent_command="cld",
            chosen_agent_command="   ",
        ).kind
        == RESPAWN_SHELL
    )




def test_persisting_a_pick_heals_a_stale_not_launched_row(tmp_path, monkeypatch):
    import src.core.session_manager as sm
    from src.core.db_models import (
        SESSION_FAMILY_SOURCE_LAUNCHED,
        SESSION_FAMILY_SOURCE_NOT_LAUNCHED,
        SESSION_ORIGIN_ADOPTED,
    )
    from src.core.session_agent_choice import persist_agent_type

    db_dir = tmp_path / "state"
    db_dir.mkdir()
    with closing(migrated_connection(db_dir)):
        pass

    from src.config import wrapper_reader

    monkeypatch.setattr(wrapper_reader, "configured_wrappers", lambda: [_FakeFamilyWrapper(
        "claude-chrome", "claude"
    )])

    name = "carnivore_Fantasy Football 2026-2"
    with closing(connect(db_path_for(db_dir))) as conn:
        record_instance(
            conn,
            socket="cloude",
            name=name,
            epoch=1790346951,
            origin=SESSION_ORIGIN_ADOPTED,
            agent_type=None,
            agent_family=None,
            agent_family_source=SESSION_FAMILY_SOURCE_NOT_LAUNCHED,
        )
        conn.commit()
        before = conn.execute(
            "SELECT agent_type, agent_family, agent_family_source "
            "FROM sessions WHERE tmux_name = ?",
            (name,),
        ).fetchone()
    assert before["agent_type"] is None
    assert before["agent_family_source"] == SESSION_FAMILY_SOURCE_NOT_LAUNCHED

    with closing(connect(db_path_for(db_dir))) as conn:
        written = persist_agent_type(
            conn, socket="cloude", tmux_name=name, agent_type="claude-chrome"
        )
        conn.commit()
    assert written is True

    with closing(connect(db_path_for(db_dir))) as conn:
        after = conn.execute(
            "SELECT agent_type, agent_family, agent_family_source "
            "FROM sessions WHERE tmux_name = ?",
            (name,),
        ).fetchone()
    assert after["agent_type"] == "claude-chrome"
    assert after["agent_family"] == "claude"
    assert after["agent_family_source"] == SESSION_FAMILY_SOURCE_LAUNCHED


class _FakeFamilyWrapper:

    def __init__(self, wid, family):
        self.id = wid
        self.family = family




def test_preview_says_shell_for_the_baseline_and_agent_for_the_pick():
    preview = build_restart_preview(
        name="cloude_api",
        probe_ok=True,
        pane_dead="1",
        pane_start_command="",
        stored_agent_type=None,
        stored_agent_command=None,
        offers=[
            WrapperOffer(agent_type="claude-chrome", label="chrome", command="cc"),
            WrapperOffer(agent_type="cldl", label="lm studio", command="cl"),
        ],
    )
    assert preview.unchanged.kind == RESPAWN_SHELL
    assert preview.wrappers_status == WRAPPERS_OK
    assert [o.kind for o in preview.options] == [RESPAWN_AGENT, RESPAWN_AGENT]
    assert all(o.resolvable and o.actionable_now for o in preview.options)
    assert [o.agent_type for o in preview.options] == ["claude-chrome", "cldl"]


def test_preview_marks_the_current_wrapper_without_reordering():
    preview = build_restart_preview(
        name="cloude_api",
        probe_ok=True,
        pane_dead="1",
        pane_start_command='"cld"',
        stored_agent_type="cldl",
        stored_agent_command="cl",
        offers=[
            WrapperOffer(agent_type="claude-chrome", command="cc"),
            WrapperOffer(agent_type="cldl", command="cl"),
        ],
    )
    assert [o.is_current for o in preview.options] == [False, True]
    assert preview.current_agent_type == "cldl"
    assert preview.options[0].label == "claude-chrome"


def test_preview_keeps_an_unlaunchable_wrapper_in_the_list_with_a_reason():
    preview = build_restart_preview(
        name="cloude_api",
        probe_ok=True,
        pane_dead="1",
        pane_start_command="",
        stored_agent_type=None,
        stored_agent_command=None,
        offers=[
            WrapperOffer(
                agent_type="cldl",
                command=None,
                unavailable_reason="the 'cldl' agent needs a model",
            )
        ],
    )
    assert len(preview.options) == 1
    assert preview.options[0].resolvable is False
    assert preview.options[0].actionable_now is False
    assert preview.options[0].kind == RESPAWN_CANNOT_DETERMINE
    assert "needs a model" in preview.options[0].detail


def test_preview_distinguishes_no_wrappers_from_could_not_read_them():
    empty = build_restart_preview(
        name="a",
        probe_ok=True,
        pane_dead="1",
        pane_start_command="",
        stored_agent_type=None,
        stored_agent_command=None,
        offers=[],
    )
    unknown = build_restart_preview(
        name="a",
        probe_ok=True,
        pane_dead="1",
        pane_start_command="",
        stored_agent_type=None,
        stored_agent_command=None,
        offers=None,
    )
    assert empty.wrappers_status == WRAPPERS_OK
    assert unknown.wrappers_status == WRAPPERS_UNAVAILABLE
    assert empty.options == unknown.options == []
    assert empty.wrappers_status != unknown.wrappers_status


def test_preview_of_a_live_session_offers_nothing_actionable():
    preview = build_restart_preview(
        name="a",
        probe_ok=True,
        pane_dead="0",
        pane_start_command='"cld"',
        stored_agent_type="cld",
        stored_agent_command="cld",
        offers=[WrapperOffer(agent_type="claude-chrome", command="cc")],
    )
    assert preview.unchanged.kind == RESPAWN_NOT_DEAD
    assert preview.unchanged.actionable is False
    assert [o.kind for o in preview.options] == [RESPAWN_NOT_DEAD]
    assert not any(o.actionable_now for o in preview.options)
    assert all(o.resolvable for o in preview.options)


def test_the_preview_applies_the_same_transcript_guard_as_the_action():
    resuming = "zsh -c 'claude --resume 82aabe7b-c0be-4430-b127-bbf8aad17a57'"
    kw = dict(
        name="cloude_api",
        probe_ok=True,
        pane_dead="1",
        pane_start_command=resuming,
        stored_agent_type=None,
        stored_agent_command=None,
        offers=[WrapperOffer(agent_type="claude-chrome", command="cc")],
    )

    gone = build_restart_preview(presence_outcome="absent", **kw)
    assert gone.unchanged.kind == RESPAWN_TRANSCRIPT_MISSING
    assert gone.unchanged.actionable is False
    assert gone.projected.kind == RESPAWN_TRANSCRIPT_MISSING
    assert gone.unchanged.command is None

    assert gone.options[0].actionable_now is True
    assert gone.options[0].kind == RESPAWN_AGENT

    for outcome in ("present", "unchecked", None):
        fine = build_restart_preview(presence_outcome=outcome, **kw)
        assert fine.unchanged.kind == "replay", (
            f"presence {outcome!r} refused a preview; only 'absent' may"
        )




class _FakeWrapper:
    def __init__(self, wid):
        self.id = wid
        self.label = wid


class _FakeAgents:
    def __init__(self, wrappers):
        self.wrappers = wrappers


class _FakeAuth:
    def __init__(self, wrappers):
        self.agents = _FakeAgents(wrappers)


class _FakeSettings:

    def __init__(self, ids, *, raise_load=False, command="resolved"):
        self._ids = ids
        self._raise_load = raise_load
        self._command = command

    def load_auth_config(self):
        if self._raise_load:
            raise OSError("config.json is unreadable")
        return _FakeAuth([_FakeWrapper(i) for i in self._ids])

    def get_agent_command(self, agent_type, model=None, extra_args=None):
        return self._command

    def pane_launch_command(self, agent_type, model=None, extra_args=None):
        return self.get_agent_command(agent_type, model=model, extra_args=extra_args)


def test_an_unknown_wrapper_id_is_refused_and_never_substituted():
    choice = validate_agent_choice(
        _FakeSettings(["claude-skip-permissions", "claude-chrome"]), "nope"
    )
    assert choice.verdict == CHOICE_UNKNOWN
    assert choice.accepted is False
    assert choice.command is None
    assert "claude-chrome" in choice.detail


def test_an_unreadable_config_cannot_determine_rather_than_unknown():
    choice = validate_agent_choice(
        _FakeSettings([], raise_load=True), "claude-chrome"
    )
    assert choice.verdict == CHOICE_CANNOT_DETERMINE
    assert choice.accepted is False
    assert "cannot be determined" in choice.detail


def test_a_configured_wrapper_is_accepted_with_its_command():
    choice = validate_agent_choice(
        _FakeSettings(["claude-chrome"], command="run-cc"), " claude-chrome "
    )
    assert choice.verdict == CHOICE_ACCEPTED
    assert choice.agent_type == "claude-chrome"
    assert choice.command == "run-cc"


def test_a_wrapper_that_resolves_to_nothing_is_not_accepted():
    choice = validate_agent_choice(
        _FakeSettings(["claude-chrome"], command="   "), "claude-chrome"
    )
    assert choice.verdict == CHOICE_CANNOT_DETERMINE
    assert choice.accepted is False



pytestmark_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def _pane_dead(socket: str, name: str) -> str:
    proc = _tmux(socket, "list-panes", "-t", name, "-F", "#{pane_dead}")
    return proc.stdout.strip() if proc.returncode == 0 else "?"


def _wait_for(socket: str, name: str, want: str, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _pane_dead(socket, name) == want:
            return True
        time.sleep(0.1)
    return False


def _dead_bare_pane(socket: str, name: str, cwd: Path) -> None:
    shell = _tmux(socket, "set-option", "-g", "default-shell", "/bin/sh")
    assert shell.returncode == 0, shell.stderr
    ready = f"CC_BARE_READY_{name}"
    created = _tmux(
        socket, "new-session", "-d", "-s", name, "-c", str(cwd),
        "-x", "80", "-y", "24", "-e", f"CC_TEST_READY={ready}",
    )
    assert created.returncode == 0, created.stderr
    start = _tmux(socket, "list-panes", "-t", name, "-F", "#{pane_start_command}")
    assert start.returncode == 0 and start.stdout.strip() == "", (
        f"setup: expected a bare pane, got {start.stdout.strip()!r}: {start.stderr}"
    )

    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        sent = _tmux(socket, "send-keys", "-t", name,
                     'printf "%s\\n" "$CC_TEST_READY"', "Enter")
        assert sent.returncode == 0, sent.stderr
        pane = _tmux(socket, "capture-pane", "-p", "-t", name)
        assert pane.returncode == 0, pane.stderr
        if ready in pane.stdout:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("setup: the bare shell did not accept input")

    exited = _tmux(socket, "send-keys", "-t", name, "exit", "Enter")
    assert exited.returncode == 0, exited.stderr
    assert _wait_for(socket, name, "1"), "setup: the pane did not exit"


@pytest.fixture()
def socket(request):
    name = derive_test_socket(f"pick_{request.node.name[:20]}")
    _tmux(name, "new-session", "-d", "-s", "keeper", "-x", "80", "-y", "24")
    _tmux(name, "set-option", "-wg", "remain-on-exit", "on")
    yield name
    subprocess.run(
        ["tmux", "-L", name, "kill-server"], capture_output=True, check=False
    )


def _patch_settings(monkeypatch, sm, *, wrappers):
    monkeypatch.setattr(
        type(sm.settings),
        "load_auth_config",
        lambda self: _FakeAuth([_FakeWrapper(w) for w in wrappers]),
    )


def _patch_command(monkeypatch, sm, command):
    monkeypatch.setattr(
        type(sm.settings),
        "get_agent_command",
        lambda self, agent_type, model=None, extra_args=None,
               pane_launch=False, plan_sink=None, **_launch_flags: command,
    )


def _manager():
    from unittest.mock import patch

    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        return SessionManager()


@pytestmark_tmux
@pytest.mark.asyncio
async def test_the_picked_wrapper_is_what_ends_up_in_the_pane(
    socket, tmp_path, monkeypatch
):
    from src.core import session_manager as sm

    name = "picked"
    marker = tmp_path / "ran.txt"
    _dead_bare_pane(socket, name, tmp_path)

    baseline = _tmux(
        socket, "list-panes", "-t", name, "-F", "#{pane_start_command}"
    ).stdout.strip()
    assert baseline == "", (
        f"setup: this pane was supposed to have no start command, got {baseline!r}"
    )

    chosen_command = f"sh -c \"echo picked > {marker}; sleep 30\""
    _patch_settings(monkeypatch, sm, wrappers=["claude-chrome"])
    _patch_command(monkeypatch, sm, chosen_command)

    mgr = _manager()
    result = await mgr.respawn_session(
        name, socket_name=socket, agent_type="claude-chrome"
    )

    assert result["ok"] is True, result["detail"]
    assert result["kind"] == RESPAWN_AGENT
    assert result["chosen"] is True
    assert result["agent_type"] == "claude-chrome"
    assert _wait_for(socket, name, "0"), "the pane did not come back to life"

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.1)
    assert marker.exists(), (
        "the picked wrapper never ran; the pane came back as a plain shell, "
        "which is the exact defect this feature exists to remove"
    )


@pytestmark_tmux
@pytest.mark.asyncio
async def test_an_unknown_wrapper_id_refuses_and_spawns_nothing(socket, tmp_path):
    from src.core import session_manager as sm

    name = "refused"
    _tmux(
        socket, "new-session", "-d", "-s", name, "-c", str(tmp_path),
        "-x", "80", "-y", "24", 'sh -c "sleep 0.2; exit 0"',
    )
    assert _wait_for(socket, name, "1")

    mgr = _manager()
    with pytest.raises(ValueError) as excinfo:
        await mgr.respawn_session(
            name, socket_name=socket, agent_type="not-a-real-wrapper"
        )
    assert "not-a-real-wrapper" in str(excinfo.value)
    assert _pane_dead(socket, name) == "1", "a refused restart spawned something"
    assert sm is not None


@pytestmark_tmux
@pytest.mark.asyncio
async def test_the_choice_is_remembered_and_identity_is_unchanged(
    socket, tmp_path, monkeypatch
):
    from src.core import session_manager as sm

    db_dir = tmp_path / "state"
    db_dir.mkdir()
    with closing(migrated_connection(db_dir)):
        pass

    name = "remember"
    _tmux(
        socket, "new-session", "-d", "-s", name, "-c", str(tmp_path),
        "-x", "80", "-y", "24", 'sh -c "sleep 0.2; exit 0"',
    )
    epoch = int(
        _tmux(
            socket, "display-message", "-p", "-t", name, "#{session_created}"
        ).stdout.strip()
    )
    with closing(connect(db_path_for(db_dir))) as conn:
        record_instance(
            conn,
            socket=socket,
            name=name,
            epoch=epoch,
            origin=SESSION_ORIGIN_OBSERVED,
        )
        conn.commit()
        before = conn.execute(
            "SELECT session_uuid, agent_type FROM sessions"
        ).fetchall()
    assert len(before) == 1, "setup: expected exactly one row"
    uuid_before = before[0]["session_uuid"]

    assert _wait_for(socket, name, "1")

    monkeypatch.setattr(
        type(sm.settings), "get_state_dir", lambda self: db_dir
    )
    _patch_settings(monkeypatch, sm, wrappers=["claude-chrome"])
    _patch_command(monkeypatch, sm, 'sh -c "sleep 30"')

    mgr = _manager()
    result = await mgr.respawn_session(
        name, socket_name=socket, agent_type="claude-chrome"
    )
    assert result["ok"] is True, result["detail"]
    assert result["agent_type_persisted"] is True
    assert result["session_uuid"] == uuid_before, (
        "the restart reported a different session; identity moved"
    )

    with closing(connect(db_path_for(db_dir))) as conn:
        after = conn.execute(
            "SELECT session_uuid, agent_type, parent_session_id, fork_kind "
            "FROM sessions"
        ).fetchall()
    assert len(after) == 1, "the restart minted a second row; that is a fork"
    assert after[0]["session_uuid"] == uuid_before
    assert after[0]["agent_type"] == "claude-chrome"
    assert after[0]["parent_session_id"] is None
    assert after[0]["fork_kind"] is None


@pytestmark_tmux
@pytest.mark.asyncio
async def test_a_failed_restart_does_not_record_the_choice(
    socket, tmp_path, monkeypatch
):
    from src.core import session_manager as sm

    db_dir = tmp_path / "state"
    db_dir.mkdir()
    with closing(migrated_connection(db_dir)):
        pass

    name = "diedonarrival"
    _tmux(
        socket, "new-session", "-d", "-s", name, "-c", str(tmp_path),
        "-x", "80", "-y", "24", 'sh -c "sleep 0.2; exit 0"',
    )
    epoch = int(
        _tmux(
            socket, "display-message", "-p", "-t", name, "#{session_created}"
        ).stdout.strip()
    )
    with closing(connect(db_path_for(db_dir))) as conn:
        record_instance(
            conn,
            socket=socket,
            name=name,
            epoch=epoch,
            origin=SESSION_ORIGIN_OBSERVED,
        )
        conn.commit()
    assert _wait_for(socket, name, "1")

    monkeypatch.setattr(
        type(sm.settings), "get_state_dir", lambda self: db_dir
    )
    _patch_settings(monkeypatch, sm, wrappers=["claude-chrome"])
    _patch_command(monkeypatch, sm, 'sh -c "echo nope 1>&2; exit 3"')

    mgr = _manager()
    result = await mgr.respawn_session(
        name, socket_name=socket, agent_type="claude-chrome"
    )
    assert result["ok"] is False
    assert result["agent_type_persisted"] is False
    with closing(connect(db_path_for(db_dir))) as conn:
        row = conn.execute("SELECT agent_type FROM sessions").fetchone()
    assert row["agent_type"] is None, "a restart that failed recorded the choice"


@pytestmark_tmux
@pytest.mark.asyncio
async def test_restart_preview_reads_the_pane_and_spawns_nothing(
    socket, tmp_path, monkeypatch
):
    from src.core import session_manager as sm

    name = "previewed"
    _dead_bare_pane(socket, name, tmp_path)

    _patch_settings(monkeypatch, sm, wrappers=["claude-chrome"])
    _patch_command(monkeypatch, sm, "run-cc")

    mgr = _manager()
    preview = await mgr.restart_preview(name, socket_name=socket)

    assert preview.name == name
    assert preview.unchanged.kind == RESPAWN_SHELL
    assert preview.wrappers_status == WRAPPERS_OK
    assert [o.kind for o in preview.options] == [RESPAWN_AGENT]
    assert _pane_dead(socket, name) == "1", "the preview spawned something"


def _preview_for_current(offer_command: str, stored_command: str):
    return build_restart_preview(
        name="cloude_api",
        probe_ok=True,
        pane_dead="0",
        pane_start_command='"cld"',
        stored_agent_type="cldl",
        stored_agent_command=stored_command,
        offers=[
            WrapperOffer(agent_type="claude-chrome", command="cc"),
            WrapperOffer(agent_type="cldl", command=offer_command),
        ],
    )


def test_current_wrapper_with_the_identical_launch_is_marked_the_same_as_baseline():
    preview = _preview_for_current("cl --model x", "cl --model x ")
    assert [o.same_as_unchanged for o in preview.options] == [False, True]


def test_current_wrapper_with_a_different_launch_stays_a_separate_row():
    preview = _preview_for_current("cl --model y", "cl --model x")
    assert [o.same_as_unchanged for o in preview.options] == [False, False]


def test_a_baseline_with_no_command_never_merges():
    preview = _preview_for_current("cl", "")
    assert not any(o.same_as_unchanged for o in preview.options)
