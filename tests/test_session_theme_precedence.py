from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.core.sessions import theme_global
from src.core.sessions.theme_store import ThemeStore
from src.core.session_theme_resolution import (
    THEME_SOURCE_GLOBAL_DEFAULT,
    THEME_SOURCE_NONE,
    THEME_SOURCE_PIN,
    THEME_SOURCE_PROJECT_DEFAULT,
    resolve_theme,
)


class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path):
        self._pin_path = pin_path
        self._log_dir = log_dir

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


def _manager(monkeypatch, tmp_path: Path) -> SessionManager:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    stub = _StubSettings(pin_path=state / "pinned_themes.json", log_dir=logs)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()




def test_ladder_prefers_the_pin():
    got = resolve_theme(pinned="dracula", project_default="snes")
    assert got.theme_id == "dracula"
    assert got.source == THEME_SOURCE_PIN


def test_ladder_falls_through_to_the_project_default():
    got = resolve_theme(pinned=None, project_default="snes")
    assert got.theme_id == "snes"
    assert got.source == THEME_SOURCE_PROJECT_DEFAULT


def test_ladder_answers_nothing_when_neither_store_holds_a_theme():
    got = resolve_theme(pinned=None, project_default=None)
    assert got.theme_id is None
    assert got.source == THEME_SOURCE_NONE


def test_ladder_treats_a_blank_value_as_absent():
    assert resolve_theme(pinned="", project_default="snes").theme_id == "snes"
    assert resolve_theme(pinned="", project_default="").theme_id is None




def test_ladder_reaches_the_global_default_when_nothing_else_speaks():
    got = resolve_theme(pinned=None, project_default=None, global_default="alien")
    assert got.theme_id == "alien"
    assert got.source == THEME_SOURCE_GLOBAL_DEFAULT


def test_a_pinned_session_ignores_the_global_default():
    got = resolve_theme(pinned="snes", project_default=None, global_default="alien")
    assert got.theme_id == "snes"
    assert got.source == THEME_SOURCE_PIN


def test_a_project_default_outranks_the_global_default():
    got = resolve_theme(
        pinned=None, project_default="metal", global_default="alien"
    )
    assert got.theme_id == "metal"
    assert got.source == THEME_SOURCE_PROJECT_DEFAULT


def test_a_blank_global_default_is_absent_not_a_theme_named_nothing():
    got = resolve_theme(pinned=None, project_default=None, global_default="")
    assert got.theme_id is None
    assert got.source == THEME_SOURCE_NONE


def test_no_global_reader_at_all_answers_exactly_as_before():
    assert theme_global.read_global_theme(None) is None


def test_an_unreadable_preference_block_does_not_defeat_the_ladder(tmp_path):
    def boom():
        raise OSError("config.json is a directory")

    store = ThemeStore(
        pin_path=lambda: tmp_path / "pinned_themes.json", global_theme=boom
    )
    assert theme_global.effective_theme(store, tmp_path, "cloude_x") is None


def test_the_store_resolves_the_global_when_a_session_has_no_pin(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    store = ThemeStore(
        pin_path=lambda: tmp_path / "pinned_themes.json",
        global_theme=lambda: "alien",
    )

    assert theme_global.effective_theme(store, project, "cloude_proj") == "alien"

    store.set_project_theme(project, "metal")
    assert theme_global.effective_theme(store, project, "cloude_proj") == "metal"

    store.set_pin("cloude_proj", "snes")
    assert theme_global.effective_theme(store, project, "cloude_proj") == "snes"
    store.global_theme_reader = lambda: "matrix"
    assert theme_global.effective_theme(store, project, "cloude_proj") == "snes"

    store.set_pin("cloude_proj", None)
    assert theme_global.effective_theme(store, project, "cloude_proj") == "metal"

    store.set_project_theme(project, None)
    assert theme_global.effective_theme(store, project, "cloude_proj") == "matrix"


def test_the_persisted_answer_stops_short_of_the_global(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    store = ThemeStore(
        pin_path=lambda: tmp_path / "pinned_themes.json",
        global_theme=lambda: "alien",
    )
    assert store.resolve_project_theme(project, "cloude_proj") is None


def test_the_reader_projects_the_theme_out_of_a_preference_block():
    read = theme_global.theme_reader_over_block(
        lambda: {"revision": 3, "values": {"theme": "alien", "sidebar_density": "compact"}}
    )
    assert read() == "alien"
    assert theme_global.theme_reader_over_block(lambda: {})() is None
    assert theme_global.theme_reader_over_block(lambda: {"values": {}})() is None
    assert theme_global.theme_reader_over_block(
        lambda: {"values": {"theme": 7}}
    )() is None




def test_pin_wins_over_a_conflicting_dotfile(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "snes")
    mgr.set_pinned_theme("cloude_proj", "dracula")

    assert mgr._theme_store.resolve_project_theme(project, "cloude_proj") == "dracula"


def test_an_unpinned_session_still_inherits_the_project_default(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "snes")

    assert mgr._theme_store.resolve_project_theme(project, "cloude_never_pinned") == "snes"
    assert mgr._theme_store.resolve_project_theme(project, None) == "snes"


def test_clearing_a_pin_drops_back_to_the_project_default(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "snes")
    mgr.set_pinned_theme("cloude_proj", "dracula")
    mgr.set_pinned_theme("cloude_proj", None)

    assert mgr._theme_store.resolve_project_theme(project, "cloude_proj") == "snes"




def test_two_sessions_in_one_folder_hold_two_different_themes(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    project = tmp_path / "shared"
    project.mkdir()

    mgr.set_pinned_theme("cloude_a", "snes")
    mgr.set_pinned_theme("cloude_b", "dracula")

    assert mgr._theme_store.resolve_project_theme(project, "cloude_a") == "snes"
    assert mgr._theme_store.resolve_project_theme(project, "cloude_b") == "dracula"


def test_a_third_unpinned_session_in_that_folder_takes_the_default(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    project = tmp_path / "shared"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "blade_runner")
    mgr.set_pinned_theme("cloude_a", "snes")
    mgr.set_pinned_theme("cloude_b", "dracula")

    assert mgr._theme_store.resolve_project_theme(project, "cloude_c") == "blade_runner"
    assert mgr._theme_store.get_project_theme(project) == "blade_runner"




def test_a_pin_survives_the_manager_being_rebuilt_from_disk(
    monkeypatch, tmp_path
):
    project = tmp_path / "proj"
    project.mkdir()

    first = _manager(monkeypatch, tmp_path)
    first._theme_store.set_project_theme(project, "snes")
    first.set_pinned_theme("cloude_proj", "dracula")

    reborn = _manager(monkeypatch, tmp_path)

    assert reborn._theme_store.pinned_themes.get("cloude_proj") == "dracula"
    assert reborn._theme_store.resolve_project_theme(project, "cloude_proj") == "dracula"


def test_two_sessions_in_one_folder_keep_their_themes_across_a_restart(
    monkeypatch, tmp_path
):
    project = tmp_path / "proj"
    project.mkdir()

    first = _manager(monkeypatch, tmp_path)
    first.set_pinned_theme("cloude_a", "snes")
    first.set_pinned_theme("cloude_b", "dracula")

    reborn = _manager(monkeypatch, tmp_path)

    assert reborn._theme_store.resolve_project_theme(project, "cloude_a") == "snes"
    assert reborn._theme_store.resolve_project_theme(project, "cloude_b") == "dracula"




def test_a_symlinked_working_dir_resolves_to_the_same_theme(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    real = tmp_path / "real_project"
    real.mkdir()
    link = tmp_path / "linked_project"
    link.symlink_to(real, target_is_directory=True)

    mgr._theme_store.set_project_theme(link, "snes")

    assert (real / ".cc.theme").is_file()
    assert not (link / ".cc.theme").is_symlink()
    assert mgr._theme_store.get_project_theme(real) == "snes"
    assert mgr._theme_store.get_project_theme(link) == "snes"
    assert mgr._theme_store.resolve_project_theme(real, "cloude_x") == "snes"
    assert mgr._theme_store.resolve_project_theme(link, "cloude_x") == "snes"




def test_a_pin_is_not_dropped_because_its_session_is_not_running(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    mgr.set_pinned_theme("cloude_gone", "dracula")

    source = Path(SessionManager.__module__.replace(".", "/") + ".py")
    text = (ROOT / source).read_text(encoding="utf-8")
    assert "pinned_themes_pruning_dead" not in text, (
        "the liveness prune is back; a pin for a session that is not "
        "running right now is not a dead pin"
    )

    mgr._theme_store.discard_pin("cloude_gone")
    assert "cloude_gone" not in mgr._theme_store.pinned_themes


def test_the_pin_map_is_backed_up_before_it_is_replaced(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    path = tmp_path / "state" / "pinned_themes.json"

    mgr.set_pinned_theme("cloude_a", "snes")
    assert json.loads(path.read_text()) == {"cloude_a": "snes"}
    assert not path.with_suffix(path.suffix + ".bak").exists()

    mgr.set_pinned_theme("cloude_b", "dracula")

    backup = path.with_suffix(path.suffix + ".bak")
    assert backup.is_file()
    assert json.loads(backup.read_text()) == {"cloude_a": "snes"}
    assert json.loads(path.read_text()) == {
        "cloude_a": "snes",
        "cloude_b": "dracula",
    }
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_an_unparseable_pin_map_does_not_take_the_process_down(
    monkeypatch, tmp_path
):
    state = tmp_path / "state"
    state.mkdir()
    (state / "pinned_themes.json").write_text("{ this is not json",
                                              encoding="utf-8")

    mgr = _manager(monkeypatch, tmp_path)

    assert mgr._theme_store.pinned_themes == {}
    assert (state / "pinned_themes.json").read_text(encoding="utf-8") == (
        "{ this is not json"
    )


def test_an_unreadable_dotfile_does_not_defeat_a_pin(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    mgr._theme_store.set_project_theme(project, "snes")
    mgr.set_pinned_theme("cloude_proj", "dracula")

    dotfile = project / ".cc.theme"
    dotfile.chmod(0o000)
    try:
        if os.access(dotfile, os.R_OK):
            pytest.skip("running as a user that ignores file modes")
        assert mgr._theme_store.resolve_project_theme(project, "cloude_proj") == "dracula"
    finally:
        dotfile.chmod(0o644)
