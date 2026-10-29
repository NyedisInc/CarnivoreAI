
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ts_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ts_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.session_manager import SessionManager
from src.core.sessions.theme_accents import ThemeAccents
from src.core.sessions.theme_store import ThemeStore
from src.core.sessions import theme_dotfile




class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path) -> None:
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


@pytest.fixture()
def store(tmp_path: Path) -> ThemeStore:
    return ThemeStore(pin_path=lambda: tmp_path / "pinned_themes.json")


@pytest.fixture()
def manager(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_manager.settings",
        _StubSettings(
            pin_path=tmp_path / "pinned_themes.json",
            log_dir=tmp_path / "logs",
        ),
    )
    return SessionManager()




def test_leg_a_the_facade_maps_are_the_store_maps(manager: SessionManager):
    assert manager._theme_store.pinned_themes is manager._theme_store.pinned_themes
    assert manager._theme_store.accent_cache is manager._theme_store.accent_cache
    assert (
        manager._theme_store.accent_cache
        is manager._theme_store.accents.cache
    )


def test_leg_b_the_facade_holds_no_field_of_its_own(manager: SessionManager):
    moved = ["pinned_themes", "_theme_accent_cache"]

    leftovers = [name for name in moved if hasattr(manager, name)]
    assert leftovers == [], (
        f"{leftovers} resolve on the facade again; the theme cluster is "
        "reached through the store and nothing else"
    )
    assert manager._theme_store.pinned_themes is not None


def test_leg_c_writes_cross_in_both_directions(manager: SessionManager):
    manager._theme_store.pinned_themes["via_facade"] = "matrix"
    assert manager._theme_store.pinned_themes["via_facade"] == "matrix"

    manager._theme_store.pinned_themes["via_store"] = "metal"
    assert manager._theme_store.pinned_themes["via_store"] == "metal"

    manager._theme_store.accent_cache["fake_theme"] = "#123456"
    assert manager._theme_store.accents.cache["fake_theme"] == "#123456"


def test_leg_c_a_whole_dict_rebind_lands_on_the_store(manager: SessionManager):
    replacement = {"cloude_Test": "matrix"}
    manager._theme_store.pinned_themes = replacement

    assert manager._theme_store.pinned_themes is replacement
    assert manager._theme_store.pinned_themes is replacement


def test_leg_d_a_real_public_method_persists_through_the_store(
    manager: SessionManager, tmp_path: Path
):
    manager.set_pinned_theme("cloude_live", "lovecraft")

    on_disk = json.loads((tmp_path / "pinned_themes.json").read_text())
    assert on_disk == {"cloude_live": "lovecraft"}

    second = ThemeStore(pin_path=lambda: tmp_path / "pinned_themes.json")
    second.load()
    assert second.get_pin("cloude_live") == "lovecraft"

    manager.set_pinned_theme("cloude_live", None)
    assert json.loads((tmp_path / "pinned_themes.json").read_text()) == {}




def test_the_pin_path_is_resolved_at_call_time_not_construction(
    monkeypatch, tmp_path: Path
):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    current = {"path": first}

    store = ThemeStore(pin_path=lambda: current["path"])
    store.set_pin("a", "matrix")
    assert first.exists() and not second.exists()

    current["path"] = second
    store.set_pin("b", "metal")
    assert second.exists()
    assert json.loads(second.read_text()) == {"a": "matrix", "b": "metal"}


def test_a_bare_manager_never_reads_the_real_pinned_themes_file(
    manager: SessionManager, tmp_path: Path
):
    manager.set_pinned_theme("cloude_scoped", "matrix")
    assert (tmp_path / "pinned_themes.json").exists()




def test_get_pin_answers_none_for_an_empty_name(store: ThemeStore):
    assert store.get_pin("") is None
    assert store.get_pin(None) is None


def test_set_pin_reports_whether_it_did_anything(store: ThemeStore):
    assert store.set_pin("cloude_x", "matrix") is True
    assert store.set_pin("", "matrix") is False
    assert store.pinned_themes == {"cloude_x": "matrix"}


def test_discard_pin_is_a_noop_when_absent(store: ThemeStore, tmp_path: Path):
    store.discard_pin("never_pinned")
    assert not (tmp_path / "pinned_themes.json").exists()


def test_rekey_pin_moves_a_pin_and_reports_it(store: ThemeStore):
    store.set_pin("old", "matrix")
    assert store.rekey_pin("old", "new") is True
    assert store.pinned_themes == {"new": "matrix"}
    assert store.rekey_pin("absent", "other") is False


def test_prune_to_live_drops_only_the_dead(store: ThemeStore):
    store.set_pin("alive", "matrix")
    store.set_pin("dead", "metal")

    pruned = store.prune_to_live({"alive"})

    assert pruned == ["dead"]
    assert store.pinned_themes == {"alive": "matrix"}


def test_prune_to_live_on_an_empty_map_writes_nothing(
    store: ThemeStore, tmp_path: Path
):
    store.prune_to_live(set())
    assert not (tmp_path / "pinned_themes.json").exists()


def test_load_drops_non_string_values(store: ThemeStore, tmp_path: Path):
    (tmp_path / "pinned_themes.json").write_text(
        json.dumps({"good": "matrix", "bad": 7, "empty": ""})
    )
    store.load()
    assert store.pinned_themes == {"good": "matrix"}


def test_load_survives_a_file_that_is_not_a_dict(
    store: ThemeStore, tmp_path: Path
):
    (tmp_path / "pinned_themes.json").write_text("[1, 2, 3]")
    store.load()
    assert store.pinned_themes == {}


def test_save_publishes_atomically_and_leaves_no_temp(
    store: ThemeStore, tmp_path: Path
):
    store.set_pin("cloude_x", "matrix")

    published = tmp_path / "pinned_themes.json"
    assert published.exists(), "the pin file was never published"
    assert not (tmp_path / "pinned_themes.json.tmp").exists(), (
        "a temp file survived the save, so the rename did not happen"
    )
    assert json.loads(published.read_text()) == {"cloude_x": "matrix"}




def test_the_pin_beats_the_project_default(store: ThemeStore, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    store.set_pin("cloude_both", "lovecraft")
    store.set_project_theme(project, "metal")

    assert store.resolve_project_theme(project, "cloude_both") == "lovecraft"


def test_the_legacy_pin_is_the_fallback_only(store: ThemeStore, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    store.set_pin("cloude_legacy", "lovecraft")

    assert store.resolve_project_theme(project, "cloude_legacy") == "lovecraft"
    assert store.resolve_project_theme(project) is None


def test_set_project_theme_writes_one_line_and_the_mode(
    store: ThemeStore, tmp_path: Path
):
    project = tmp_path / "proj"
    project.mkdir()
    store.set_project_theme(project, "metal")

    path = project / ".cc.theme"
    assert path.read_text() == "metal\n"
    assert oct(path.stat().st_mode)[-3:] == "644"


def test_set_project_theme_raises_on_a_missing_directory(store: ThemeStore, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        store.set_project_theme(tmp_path / "absent", "metal")
    with pytest.raises(ValueError):
        store.set_project_theme(None, "metal")


def test_clearing_the_dotfile_removes_it(store: ThemeStore, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    store.set_project_theme(project, "metal")
    store.set_project_theme(project, None)

    assert not (project / ".cc.theme").exists()
    assert store.get_project_theme(project) is None


def test_the_dotfile_module_and_the_store_agree_on_the_path(
    store: ThemeStore, tmp_path: Path
):
    assert store.project_theme_path(tmp_path) == theme_dotfile.project_theme_path(
        tmp_path
    )
    assert store.project_theme_path(tmp_path).name == theme_dotfile.DOTFILE_NAME




@pytest.mark.parametrize(
    ("tmux_session", "session_id", "expected"),
    [
        ("cloude_named", "ses_1", "cloude_named"),
        (None, "adopted:cloude_adopted", "cloude_adopted"),
        (None, "ses_plain", "ses_plain"),
        (None, "", None),
        (None, None, None),
    ],
)
def test_the_legacy_key_prefers_the_tmux_name(tmux_session, session_id, expected):
    assert ThemeStore.legacy_pin_key(tmux_session, session_id) == expected




def test_a_real_bundled_manifest_resolves(store: ThemeStore):
    assert store.accent_for_theme("matrix") == "#00ff41"


def test_a_none_answer_is_cached_as_an_answer(
    monkeypatch, store: ThemeStore, tmp_path: Path
):
    root = tmp_path / "themes"
    root.mkdir()
    monkeypatch.setattr(ThemeAccents, "themes_dir", staticmethod(lambda: root))

    (root / "late_theme").mkdir()
    (root / "late_theme" / "theme.json").write_text(json.dumps({"cssVars": {}}))
    assert store.accent_for_theme("late_theme") is None
    assert "late_theme" in store.accent_cache
    assert store.accent_cache["late_theme"] is None

    (root / "late_theme" / "theme.json").write_text(
        json.dumps({"cssVars": {"--color-accent": "#abcdef"}})
    )

    assert store.accent_for_theme("late_theme") is None, (
        "the cached None was treated as a miss, so the manifest was "
        "re-read; the memo is not memoizing"
    )


def test_the_accent_read_consults_theme_accents(monkeypatch, store: ThemeStore):
    monkeypatch.setattr(
        ThemeAccents, "themes_dir", staticmethod(lambda: Path("/nowhere"))
    )
    assert store.accent_for_theme("matrix") is None


def test_accent_for_goes_through_the_theme_resolution(
    store: ThemeStore, tmp_path: Path
):
    project = tmp_path / "proj"
    project.mkdir()
    store.set_project_theme(project, "matrix")

    assert store.accent_for(project, None) == "#00ff41"
    assert store.accent_for(tmp_path / "unthemed", None) is None


def test_accent_from_theme_installed_after_first_lookup(monkeypatch, tmp_path):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    monkeypatch.setattr(ThemeAccents, "themes_dir", staticmethod(lambda: bundled))
    monkeypatch.setattr("src.core.sessions.theme_accents.user_themes_dir", lambda: user)
    accents = ThemeAccents()
    assert accents.accent_for_theme("late") is None
    (user / "late").mkdir()
    (user / "late" / "theme.json").write_text('{"cssVars": {"--color-accent": "#123456"}}')
    assert accents.accent_for_theme("late") == "#123456"
    assert accents.accent_for_theme("../late") is None
