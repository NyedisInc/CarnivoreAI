
from __future__ import annotations

from src.core import product_identity as pid


class TestIsOwnedSessionName:
    def test_current_prefix_is_owned(self) -> None:
        assert pid.is_owned_session_name("carnivore_abc123") is True

    def test_legacy_prefix_is_owned(self) -> None:
        assert pid.is_owned_session_name("cloude_abc123") is True

    def test_unrelated_name_is_not_owned(self) -> None:
        assert pid.is_owned_session_name("some-other-tmux-session") is False

    def test_bare_prefix_with_nothing_after_is_owned(self) -> None:
        assert pid.is_owned_session_name("carnivore_") is True

    def test_prefix_as_substring_not_at_start_is_not_owned(self) -> None:
        assert pid.is_owned_session_name("my-carnivore_session") is False

    def test_empty_string_is_not_owned(self) -> None:
        assert pid.is_owned_session_name("") is False


class TestStripSessionPrefix:
    def test_current_prefix_strips_to_slug(self) -> None:
        assert pid.strip_session_prefix("carnivore_abc123") == "abc123"

    def test_legacy_prefix_strips_to_slug(self) -> None:
        assert pid.strip_session_prefix("cloude_abc123") == "abc123"

    def test_current_prefix_checked_before_legacy(self) -> None:
        assert pid.strip_session_prefix("carnivore_x") == "x"

    def test_no_prefix_match_returns_none(self) -> None:
        assert pid.strip_session_prefix("unrelated-name") is None

    def test_empty_string_returns_none(self) -> None:
        assert pid.strip_session_prefix("") is None

    def test_bare_prefix_strips_to_empty_slug(self) -> None:
        assert pid.strip_session_prefix("cloude_") == ""


class TestSocketsToProbe:
    def test_explicit_config_wins_alone(self) -> None:
        assert pid.sockets_to_probe("my-custom-socket") == ("my-custom-socket",)

    def test_none_returns_current_then_legacy_in_order(self) -> None:
        assert pid.sockets_to_probe(None) == ("carnivore", "cloude")

    def test_empty_string_is_falsy_and_returns_probe_order(self) -> None:
        assert pid.sockets_to_probe("") == ("carnivore", "cloude")


class TestResolveNamed:
    def test_current_name_exists_is_chosen(self, tmp_path) -> None:
        (tmp_path / "carnivore.db").write_text("x")
        result = pid.resolve_named(tmp_path, "carnivore.db", ("cloude.db",))
        assert result.path == tmp_path / "carnivore.db"
        assert result.used_legacy is False
        assert result.both_present is False

    def test_only_legacy_exists_is_chosen(self, tmp_path) -> None:
        (tmp_path / "cloude.db").write_text("x")
        result = pid.resolve_named(tmp_path, "carnivore.db", ("cloude.db",))
        assert result.path == tmp_path / "cloude.db"
        assert result.used_legacy is True
        assert result.both_present is False

    def test_both_exist_current_wins_but_flags_both(self, tmp_path) -> None:
        (tmp_path / "carnivore.db").write_text("x")
        (tmp_path / "cloude.db").write_text("x")
        result = pid.resolve_named(tmp_path, "carnivore.db", ("cloude.db",))
        assert result.path == tmp_path / "carnivore.db"
        assert result.used_legacy is False
        assert result.both_present is True

    def test_neither_exists_returns_current_path_uncreated(self, tmp_path) -> None:
        result = pid.resolve_named(tmp_path, "carnivore.db", ("cloude.db",))
        assert result.path == tmp_path / "carnivore.db"
        assert result.used_legacy is False
        assert result.both_present is False
        assert not result.path.exists()

    def test_multiple_legacy_names_checked_in_order(self, tmp_path) -> None:
        (tmp_path / "second-legacy").write_text("x")
        result = pid.resolve_named(
            tmp_path, "current", ("first-legacy", "second-legacy")
        )
        assert result.path == tmp_path / "second-legacy"
        assert result.used_legacy is True

    def test_never_creates_moves_or_deletes(self, tmp_path) -> None:
        (tmp_path / "cloude.db").write_text("original")
        pid.resolve_named(tmp_path, "carnivore.db", ("cloude.db",))
        assert not (tmp_path / "carnivore.db").exists()
        assert (tmp_path / "cloude.db").read_text() == "original"

    def test_result_is_frozen(self, tmp_path) -> None:
        result = pid.resolve_named(tmp_path, "carnivore.db", ("cloude.db",))
        with __import__("pytest").raises(Exception):
            result.path = tmp_path / "other"  # type: ignore[misc]


class TestEnvNames:
    def test_current_prefix_first_then_legacy_in_order(self) -> None:
        assert pid.env_names("PORT") == ("CARNIVORE_PORT", "CLOUDE_PORT", "CLOUDECODE_PORT")

    def test_works_for_any_suffix(self) -> None:
        assert pid.env_names("DEBUG") == ("CARNIVORE_DEBUG", "CLOUDE_DEBUG", "CLOUDECODE_DEBUG")


class TestEnvValue:

    def test_current_name_alone_resolves(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDE_PORT", raising=False)
        monkeypatch.delenv("CLOUDECODE_PORT", raising=False)
        monkeypatch.setenv("CARNIVORE_PORT", "9001")
        assert pid.env_value("PORT") == "9001"

    def test_legacy_cloude_name_alone_still_resolves(self, monkeypatch) -> None:
        monkeypatch.delenv("CARNIVORE_PORT", raising=False)
        monkeypatch.delenv("CLOUDECODE_PORT", raising=False)
        monkeypatch.setenv("CLOUDE_PORT", "9002")
        assert pid.env_value("PORT") == "9002"

    def test_legacy_cloudecode_name_alone_still_resolves(self, monkeypatch) -> None:
        monkeypatch.delenv("CARNIVORE_PORT", raising=False)
        monkeypatch.delenv("CLOUDE_PORT", raising=False)
        monkeypatch.setenv("CLOUDECODE_PORT", "9003")
        assert pid.env_value("PORT") == "9003"

    def test_current_name_wins_over_both_legacy_names(self, monkeypatch) -> None:
        monkeypatch.setenv("CARNIVORE_PORT", "current")
        monkeypatch.setenv("CLOUDE_PORT", "legacy1")
        monkeypatch.setenv("CLOUDECODE_PORT", "legacy2")
        assert pid.env_value("PORT") == "current"

    def test_first_legacy_wins_over_second_legacy(self, monkeypatch) -> None:
        monkeypatch.delenv("CARNIVORE_PORT", raising=False)
        monkeypatch.setenv("CLOUDE_PORT", "legacy1")
        monkeypatch.setenv("CLOUDECODE_PORT", "legacy2")
        assert pid.env_value("PORT") == "legacy1"

    def test_none_set_returns_none(self, monkeypatch) -> None:
        monkeypatch.delenv("CARNIVORE_PORT", raising=False)
        monkeypatch.delenv("CLOUDE_PORT", raising=False)
        monkeypatch.delenv("CLOUDECODE_PORT", raising=False)
        assert pid.env_value("PORT") is None

    def test_present_but_empty_is_distinct_from_absent(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDE_DEBUG", raising=False)
        monkeypatch.delenv("CLOUDECODE_DEBUG", raising=False)
        monkeypatch.setenv("CARNIVORE_DEBUG", "")
        assert pid.env_value("DEBUG") == ""


class TestIdentityReportPlaceholder:

    def test_returns_a_dict_of_placeholder_strings(self) -> None:
        report = pid.identity_report()
        assert isinstance(report, dict)
        assert len(report) > 0
        assert all(value == "current" for value in report.values())

    def test_covers_every_named_category(self) -> None:
        report = pid.identity_report()
        expected_categories = {
            "tmux_socket",
            "session_prefix",
            "db_filename",
            "state_dir",
            "menubar_state_dir",
            "bundle_id",
            "env_prefix",
            "upload_dir",
            "browser_key_prefix",
            "release_repo",
        }
        assert expected_categories.issubset(report.keys())
