from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sd_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import settings, StateDirUnavailableError
from src.config import state_paths


@pytest.fixture(autouse=True)
def _reset_state_dir_override(monkeypatch):
    monkeypatch.setattr(settings, "state_dir_override", None)
    monkeypatch.setattr(settings, "log_directory", None)



def test_get_state_dir_uses_override_when_set(tmp_path, monkeypatch):
    target = tmp_path / "cloude-state"
    monkeypatch.setattr(settings, "state_dir_override", str(target))

    resolved = settings.get_state_dir()

    assert resolved == target
    assert resolved.is_dir()


def test_get_state_dir_expands_tilde_in_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(settings, "state_dir_override", "~/cloude-state-tilde")

    resolved = settings.get_state_dir()

    assert resolved == tmp_path / "cloude-state-tilde"
    assert resolved.is_dir()


def test_get_state_dir_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert settings.state_dir_override is None

    resolved = settings.get_state_dir()

    expected = tmp_path / "Library" / "Application Support" / "Carnivore"
    assert resolved == expected
    assert resolved.is_dir()
    assert resolved.relative_to(tmp_path) == Path(
        "Library"
    ) / "Application Support" / "Carnivore"


def test_get_state_dir_falls_back_to_the_legacy_directory_when_present(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / "Library" / "Application Support" / "CloudeCode"
    legacy.mkdir(parents=True)
    (legacy / "session_metadata.json").write_text('{"real": "data"}')

    resolved = settings.get_state_dir()

    expected = tmp_path / "Library" / "Application Support" / "Carnivore"
    assert resolved == expected
    assert not legacy.exists(), "the legacy directory must be gone, not copied"
    assert (resolved / "session_metadata.json").read_text() == (
        '{"real": "data"}'
    ), "the rename must carry the file's content along, not just the name"
    assert state_paths.state_dir_legacy_note() is None, (
        "a successful rename must not leave a fallback note behind"
    )


def test_get_state_dir_keeps_the_legacy_directory_when_the_rename_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / "Library" / "Application Support" / "CloudeCode"
    legacy.mkdir(parents=True)
    (legacy / "session_metadata.json").write_text('{"real": "data"}')

    def _boom(self, target):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(Path, "rename", _boom)

    resolved = settings.get_state_dir()

    assert resolved == legacy
    assert legacy.exists()
    assert (legacy / "session_metadata.json").read_text() == '{"real": "data"}'
    carnivore = tmp_path / "Library" / "Application Support" / "Carnivore"
    assert not carnivore.exists(), (
        "a failed rename must never leave a partial destination behind"
    )
    note = state_paths.state_dir_legacy_note()
    assert note is not None
    assert str(legacy) in note


def test_get_state_dir_default_is_never_under_the_system_temp_dir(monkeypatch):
    temp_root = Path(tempfile.gettempdir()).resolve()
    base = ROOT.resolve()
    if base == temp_root or temp_root in base.parents:
        pytest.skip(
            f"CANNOT DETERMINE: this checkout ({base}) is itself under the "
            f"system temp root ({temp_root}), so no home rooted in it can "
            "distinguish 'resolved outside temp' from 'resolved inside temp'"
        )

    fake_home = base / "build" / f"state-dir-test-home-{uuid.uuid4().hex}"
    fake_home.mkdir(parents=True)
    try:
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        assert settings.state_dir_override is None

        resolved = settings.get_state_dir().resolve()

        assert resolved == (
            fake_home / "Library" / "Application Support" / "Carnivore"
        ).resolve()
        assert resolved.is_dir()
        assert resolved != temp_root
        assert temp_root not in resolved.parents
    finally:
        shutil.rmtree(fake_home, ignore_errors=True)


def test_get_state_dir_raises_named_error_when_uncreatable(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory")
    target = blocker / "state"
    monkeypatch.setattr(settings, "state_dir_override", str(target))

    with pytest.raises(StateDirUnavailableError) as exc_info:
        settings.get_state_dir()

    err = exc_info.value
    assert err.path == target
    assert isinstance(err.cause, OSError)
    assert str(target) in str(err)
    assert not target.exists()


def test_get_state_dir_uncreatable_does_not_touch_tmp(tmp_path, monkeypatch):
    private_tmp = tmp_path / "system-temp"
    private_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private_tmp))
    assert tempfile.gettempdir() == str(private_tmp), (
        "the redirect did not take, so this test would be measuring the "
        "shared system temp directory again"
    )

    before = set(os.listdir(tempfile.gettempdir()))
    blocker = tmp_path / "blocker2"
    blocker.write_text("x")
    monkeypatch.setattr(settings, "state_dir_override", str(blocker / "state"))

    with pytest.raises(StateDirUnavailableError):
        settings.get_state_dir()

    after = set(os.listdir(tempfile.gettempdir()))
    assert after == before



def _configure_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    new_dir = tmp_path / "Library" / "Application Support" / "Carnivore"
    old_dir = tmp_path / "old_log_directory"
    new_dir.mkdir(parents=True)
    old_dir.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(old_dir))
    return new_dir, old_dir


@pytest.mark.parametrize(
    "getter_name,filename",
    [
        ("get_session_metadata_path", "session_metadata.json"),
        ("get_pinned_themes_path", "pinned_themes.json"),
        ("get_unread_state_path", "unread_state.json"),
    ],
)
def test_state_file_old_location_only(tmp_path, monkeypatch, getter_name, filename):
    new_dir, old_dir = _configure_dirs(monkeypatch, tmp_path)
    (old_dir / filename).write_text('{"legacy": true}')

    resolved = getattr(settings, getter_name)()

    assert resolved == old_dir / filename


@pytest.mark.parametrize(
    "getter_name,filename",
    [
        ("get_session_metadata_path", "session_metadata.json"),
        ("get_pinned_themes_path", "pinned_themes.json"),
        ("get_unread_state_path", "unread_state.json"),
    ],
)
def test_state_file_new_location_only(tmp_path, monkeypatch, getter_name, filename):
    new_dir, old_dir = _configure_dirs(monkeypatch, tmp_path)
    (new_dir / filename).write_text('{"current": true}')

    resolved = getattr(settings, getter_name)()

    assert resolved == new_dir / filename


@pytest.mark.parametrize(
    "getter_name,filename",
    [
        ("get_session_metadata_path", "session_metadata.json"),
        ("get_pinned_themes_path", "pinned_themes.json"),
        ("get_unread_state_path", "unread_state.json"),
    ],
)
def test_state_file_both_present_prefers_new_reports_and_keeps_old(
    tmp_path, monkeypatch, getter_name, filename, capsys
):
    new_dir, old_dir = _configure_dirs(monkeypatch, tmp_path)
    (new_dir / filename).write_text('{"current": true}')
    (old_dir / filename).write_text('{"legacy": true}')

    resolved = getattr(settings, getter_name)()

    assert resolved == new_dir / filename
    assert (old_dir / filename).exists()
    assert (old_dir / filename).read_text() == '{"legacy": true}'
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "state_file_present_in_both_locations" in combined
    assert filename in combined


def test_state_file_neither_location_returns_new_path_for_creation(
    tmp_path, monkeypatch
):
    new_dir, old_dir = _configure_dirs(monkeypatch, tmp_path)

    resolved = settings.get_pinned_themes_path()

    assert resolved == new_dir / "pinned_themes.json"


def test_state_file_no_old_log_directory_configured(tmp_path, monkeypatch):
    new_dir = tmp_path / "new_state_only"
    new_dir.mkdir()
    monkeypatch.setattr(settings, "state_dir_override", str(new_dir))
    monkeypatch.setattr(settings, "log_directory", None)

    resolved = settings.get_unread_state_path()

    assert resolved == new_dir / "unread_state.json"



PINNED_STATE_FILES = [
    ("get_refresh_tokens_path", "refresh_tokens.db"),
    ("get_session_metadata_path", "session_metadata.json"),
    ("get_pinned_themes_path", "pinned_themes.json"),
    ("get_unread_state_path", "unread_state.json"),
]


def test_explicit_state_dir_suppresses_the_legacy_pin(tmp_path, monkeypatch):
    state_dir = tmp_path / "throwaway_state"
    legacy_dir = tmp_path / "legacy"
    state_dir.mkdir()
    legacy_dir.mkdir()
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    monkeypatch.setattr(settings, "log_directory", str(legacy_dir))

    for _getter, filename in PINNED_STATE_FILES:
        (legacy_dir / filename).write_text("live user data")

    for getter, filename in PINNED_STATE_FILES:
        resolved = getattr(settings, getter)()
        assert resolved == state_dir / filename, (
            f"{getter}() escaped the explicitly named state directory"
        )
        assert settings.get_state_file_location(filename) == "state_dir"

    for _getter, filename in PINNED_STATE_FILES:
        assert (legacy_dir / filename).read_text() == "live user data"


def test_legacy_pin_still_fires_when_no_state_dir_was_named(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy_dir = tmp_path / "legacy_only"
    legacy_dir.mkdir()
    monkeypatch.setattr(settings, "state_dir_override", None)
    monkeypatch.setattr(settings, "log_directory", str(legacy_dir))
    assert not settings.state_dir_is_explicit()

    for _getter, filename in PINNED_STATE_FILES:
        (legacy_dir / filename).write_text("pre-existing install data")

    for getter, filename in PINNED_STATE_FILES:
        resolved = getattr(settings, getter)()
        assert resolved == legacy_dir / filename, (
            f"{getter}() abandoned an existing install's data - the legacy "
            "fallback stopped firing for an install that never named a "
            "state directory"
        )
        assert settings.get_state_file_location(filename) == "log_directory"


def test_explicit_state_dir_never_resolves_under_the_real_legacy_default(
    tmp_path, monkeypatch
):
    state_dir = tmp_path / "isolated"
    state_dir.mkdir()
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    monkeypatch.setattr(settings, "log_directory", "~/cloude-projects")

    real_legacy = Path("~/cloude-projects").expanduser()
    for getter, filename in PINNED_STATE_FILES:
        resolved = getattr(settings, getter)()
        assert resolved.parent == state_dir
        assert real_legacy not in resolved.parents, (
            f"{getter}() resolved inside the real legacy directory "
            f"{real_legacy} while an explicit state dir was set"
        )



def test_pin_cache_key_must_include_state_dir_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    state_dir = tmp_path / "state"
    legacy_dir = tmp_path / "legacy"
    state_dir.mkdir()
    legacy_dir.mkdir()
    filename = "pinned_themes.json"
    (legacy_dir / filename).write_text("legacy data")

    pins: dict = {}
    common = dict(
        pins=pins,
        resolved_state_dir=state_dir,
        state_dir_override=str(state_dir),
        log_directory=str(legacy_dir),
    )

    path_a, location_a = state_paths.state_file_pin(
        filename, state_dir_explicit=False, **common
    )
    assert location_a == "log_directory"
    assert path_a == legacy_dir / filename

    path_b, location_b = state_paths.state_file_pin(
        filename, state_dir_explicit=True, **common
    )
    assert location_b == "state_dir", (
        "the cached pin from the state_dir_explicit=False call leaked "
        "into the state_dir_explicit=True call - the cache key is "
        "missing the explicit flag"
    )
    assert path_b == state_dir / filename




def _bootstrap_fresh_settings_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("TOTP_SECRET", "testsecretnotreal")
    monkeypatch.setenv("JWT_SECRET", "testjwtnotreal")
    for name in ("CARNIVORE_STATE_DIR", "CLOUDE_STATE_DIR", "CLOUDECODE_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_state_dir_override_resolves_from_new_carnivore_name_alone(
    monkeypatch, tmp_path
):
    _bootstrap_fresh_settings_env(monkeypatch, tmp_path)
    target = str(tmp_path / "carnivore-state")
    monkeypatch.setenv("CARNIVORE_STATE_DIR", target)

    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.state_dir_override == target, (
        "state_dir_override did not resolve from CARNIVORE_STATE_DIR "
        "alone - the new-style env var name must work with zero legacy "
        "var present."
    )


def test_state_dir_override_resolves_from_legacy_cloude_name_alone(
    monkeypatch, tmp_path
):
    _bootstrap_fresh_settings_env(monkeypatch, tmp_path)
    target = str(tmp_path / "legacy-state")
    monkeypatch.setenv("CLOUDE_STATE_DIR", target)

    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.state_dir_override == target, (
        "state_dir_override stopped resolving from the legacy "
        "CLOUDE_STATE_DIR var - this must stay additive."
    )


def test_state_dir_override_new_name_wins_over_legacy_when_both_set(
    monkeypatch, tmp_path
):
    _bootstrap_fresh_settings_env(monkeypatch, tmp_path)
    current = str(tmp_path / "current-state")
    legacy = str(tmp_path / "legacy-state")
    monkeypatch.setenv("CARNIVORE_STATE_DIR", current)
    monkeypatch.setenv("CLOUDE_STATE_DIR", legacy)

    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.state_dir_override == current, (
        "CARNIVORE_STATE_DIR must take precedence over CLOUDE_STATE_DIR "
        "when both are set."
    )


def test_state_dir_override_unset_when_neither_name_present(monkeypatch, tmp_path):
    _bootstrap_fresh_settings_env(monkeypatch, tmp_path)

    from src.config import Settings

    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.state_dir_override is None




def _home_app_support(tmp_path: Path) -> Path:
    return tmp_path / "Library" / "Application Support"


def test_pin_third_rung_finds_a_file_only_the_legacy_directory_has(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app_support = _home_app_support(tmp_path)
    current_dir = app_support / "Carnivore"
    legacy_dir = app_support / "CloudeCode"
    current_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "pinned_themes.json").write_text('{"legacy": true}')

    path, location = state_paths.state_file_pin(
        "pinned_themes.json",
        pins={},
        resolved_state_dir=current_dir,
        state_dir_override=None,
        log_directory=None,
        state_dir_explicit=False,
    )

    assert path == legacy_dir / "pinned_themes.json"
    assert location == state_paths.LOCATION_LEGACY_STATE_DIR


def test_pin_third_rung_prefers_current_and_reports_ambiguity(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app_support = _home_app_support(tmp_path)
    current_dir = app_support / "Carnivore"
    legacy_dir = app_support / "CloudeCode"
    current_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    (current_dir / "pinned_themes.json").write_text('{"current": true}')
    (legacy_dir / "pinned_themes.json").write_text('{"legacy": true}')

    path, location = state_paths.state_file_pin(
        "pinned_themes.json",
        pins={},
        resolved_state_dir=current_dir,
        state_dir_override=None,
        log_directory=None,
        state_dir_explicit=False,
    )

    assert path == current_dir / "pinned_themes.json"
    assert location == state_paths.LOCATION_STATE_DIR
    assert (legacy_dir / "pinned_themes.json").read_text() == '{"legacy": true}'
    combined = "".join(capsys.readouterr())
    assert "state_file_present_in_both_locations" in combined
    assert "pinned_themes.json" in combined


def test_pin_third_rung_skipped_when_state_dir_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy_dir = _home_app_support(tmp_path) / "CloudeCode"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "pinned_themes.json").write_text('{"legacy-leak": true}')
    explicit_dir = tmp_path / "explicit_state"
    explicit_dir.mkdir()

    path, location = state_paths.state_file_pin(
        "pinned_themes.json",
        pins={},
        resolved_state_dir=explicit_dir,
        state_dir_override=str(explicit_dir),
        log_directory=None,
        state_dir_explicit=True,
    )

    assert path == explicit_dir / "pinned_themes.json"
    assert location == state_paths.LOCATION_STATE_DIR


def test_pin_third_rung_skipped_when_resolved_state_dir_is_already_legacy(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy_dir = _home_app_support(tmp_path) / "CloudeCode"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "pinned_themes.json").write_text('{"only copy": true}')

    path, location = state_paths.state_file_pin(
        "pinned_themes.json",
        pins={},
        resolved_state_dir=legacy_dir,
        state_dir_override=None,
        log_directory=None,
        state_dir_explicit=False,
    )

    assert path == legacy_dir / "pinned_themes.json"
    assert location == state_paths.LOCATION_STATE_DIR, (
        "resolved_state_dir already IS the legacy directory - this must "
        "read as the ordinary rung-1 answer, not a separate legacy find"
    )


def test_pin_precedence_is_current_then_legacy_named_then_log_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app_support = _home_app_support(tmp_path)
    current_dir = app_support / "Carnivore"
    legacy_named_dir = app_support / "CloudeCode"
    log_dir = tmp_path / "old_log_directory"
    current_dir.mkdir(parents=True)
    legacy_named_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    (log_dir / "pinned_themes.json").write_text('{"very old": true}')

    path, location = state_paths.state_file_pin(
        "pinned_themes.json",
        pins={},
        resolved_state_dir=current_dir,
        state_dir_override=None,
        log_directory=str(log_dir),
        state_dir_explicit=False,
    )

    assert path == log_dir / "pinned_themes.json"
    assert location == state_paths.LOCATION_LOG_DIRECTORY
