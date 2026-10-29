
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.core import update_check
from src.core.update_check import (
    DEFAULT_UPGRADE_COMMAND,
    FALLBACK_REMOTE,
    STATUS_CURRENT,
    STATUS_UNKNOWN,
    STATUS_UPDATE_AVAILABLE,
    UpdateCheckError,
    UpdateChecker,
    parse_version,
    read_configured_remote,
)
from src.core.version import (
    VERSION_FILE_HEADER,
    describe_git_tag,
    is_git_root,
    normalize_tag,
    read_version_file,
    resolve_version,
    write_version_file,
)




def test_normalize_tag_strips_v_and_whitespace() -> None:
    assert normalize_tag(" v1.2.3 ") == "1.2.3"
    assert normalize_tag("1.2.3") == "1.2.3"
    assert normalize_tag("") == ""


def test_version_file_round_trip(tmp_path: Path) -> None:
    write_version_file("v2.3.4", root=tmp_path)
    text = (tmp_path / "VERSION").read_text(encoding="utf-8")
    assert text.startswith(VERSION_FILE_HEADER)
    assert read_version_file(tmp_path) == "2.3.4"


def test_version_file_missing_returns_empty(tmp_path: Path) -> None:
    assert read_version_file(tmp_path) == ""


def test_env_var_wins_over_version_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_version_file("1.0.0", root=tmp_path)
    monkeypatch.setenv("CLOUDE_APP_VERSION", "v9.9.9")
    assert resolve_version(tmp_path) == "9.9.9"


def test_version_file_used_when_env_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.0.0", root=tmp_path)
    assert resolve_version(tmp_path) == "1.0.0"




def test_new_carnivore_app_version_name_alone_wins_over_version_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    monkeypatch.delenv("CLOUDECODE_APP_VERSION", raising=False)
    monkeypatch.setenv("CARNIVORE_APP_VERSION", "v9.9.9")
    write_version_file("1.0.0", root=tmp_path)
    assert resolve_version(tmp_path) == "9.9.9"


def test_legacy_cloude_app_version_name_alone_still_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CARNIVORE_APP_VERSION", raising=False)
    monkeypatch.delenv("CLOUDECODE_APP_VERSION", raising=False)
    monkeypatch.setenv("CLOUDE_APP_VERSION", "v9.9.9")
    assert resolve_version(tmp_path) == "9.9.9"


def test_new_carnivore_app_version_name_wins_over_legacy_when_both_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CARNIVORE_APP_VERSION", "v1.1.1")
    monkeypatch.setenv("CLOUDE_APP_VERSION", "v2.2.2")
    assert resolve_version(tmp_path) == "1.1.1"


def test_version_file_outranks_legacy_package_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    (tmp_path / "macOS").mkdir()
    (tmp_path / "macOS" / "package.json").write_text(
        json.dumps({"version": "0.0.1"}), encoding="utf-8"
    )
    write_version_file("0.8.1", root=tmp_path)
    assert resolve_version(tmp_path) == "0.8.1"


def test_package_json_is_still_the_fallback_without_a_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    (tmp_path / "macOS").mkdir()
    (tmp_path / "macOS" / "package.json").write_text(
        json.dumps({"version": "0.0.1"}), encoding="utf-8"
    )
    assert resolve_version(tmp_path) == "0.0.1"


def test_resolve_returns_empty_when_nothing_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    assert resolve_version(tmp_path) == ""




def _production_layout(tmp_path: Path) -> Path:
    server_dir = tmp_path / "server"
    (server_dir / "src" / "core").mkdir(parents=True)
    (server_dir / "client").mkdir()
    (server_dir / "config.json").write_text("{}", encoding="utf-8")
    return server_dir


def test_production_layout_resolves_from_the_injected_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = _production_layout(tmp_path)
    monkeypatch.setenv("CLOUDE_APP_VERSION", "v0.8.1")
    assert resolve_version(server_dir) == "0.8.1"


def test_production_layout_resolves_from_the_stamped_version_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = _production_layout(tmp_path)
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    assert not (server_dir / ".git").exists()
    assert not (server_dir / "macOS" / "package.json").exists()
    write_version_file("0.8.1", root=server_dir)
    assert resolve_version(server_dir) == "0.8.1"


def test_a_source_root_inside_a_foreign_checkout_does_not_borrow_its_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)

    outer = tmp_path / "someone-elses-repo"
    outer.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-q", "--allow-empty", "-m", "x"],
        ["git", "tag", "v42.0.0"],
    ):
        subprocess.run(cmd, cwd=outer, check=True, capture_output=True)

    assert resolve_version(outer) == "42.0.0"

    nested = outer / "server"
    (nested / "src" / "core").mkdir(parents=True)
    assert not (nested / ".git").exists()
    assert resolve_version(nested) == ""
    assert not is_git_root(nested)
    assert update_check.discover_origin_remote(nested) == ""


def test_describe_never_degrades_to_a_bare_commit_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    repo = tmp_path / "untagged"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "-q", "--allow-empty", "-m", "x"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    assert is_git_root(repo)
    assert describe_git_tag(repo) == ""
    assert resolve_version(repo) == ""


def test_production_layout_with_nothing_is_blank_not_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = _production_layout(tmp_path)
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    assert resolve_version(server_dir) == ""


def test_production_layout_unresolved_version_is_unknown_not_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = _production_layout(tmp_path)
    (server_dir / ".git").mkdir()
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: ["9.9.9"])
    checker = UpdateChecker(
        config_path=server_dir / "config.json",
        root=server_dir,
        cache_path=server_dir / "cache.json",
    )
    status = checker.refresh()
    assert status.status == STATUS_UNKNOWN
    assert status.status != STATUS_CURRENT
    assert status.reason


def test_cache_defaults_inside_the_source_root_not_a_new_state_dir(
    tmp_path: Path,
) -> None:
    server_dir = _production_layout(tmp_path)
    (server_dir / ".git").mkdir()
    checker = UpdateChecker(
        config_path=server_dir / "config.json", root=server_dir
    )
    checker.refresh()
    assert (server_dir / update_check.CACHE_FILENAME).is_file()
    assert update_check.default_cache_path(server_dir).parent == server_dir
    assert ".cloude-code" not in Path(update_check.CACHE_FILENAME).parts




@pytest.mark.parametrize(
    "tag,expected",
    [
        ("v1.2.3", (1, 2, 3)),
        ("1.2.3", (1, 2, 3)),
        ("v0.10.0", (0, 10, 0)),
        ("v1.2.3-rc1", None),
        ("0.8.1-3-gabc1234", None),
        ("nightly", None),
        ("", None),
    ],
)
def test_parse_version(tag: str, expected: tuple[int, int, int] | None) -> None:
    assert parse_version(tag) == expected


def test_read_configured_remote(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"updates": {"remote": "https://example.test/x.git"}}))
    assert read_configured_remote(config) == "https://example.test/x.git"


def test_read_configured_remote_absent_or_malformed(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    assert read_configured_remote(missing) == ""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert read_configured_remote(bad) == ""
    no_block = tmp_path / "plain.json"
    no_block.write_text(json.dumps({"projects": []}))
    assert read_configured_remote(no_block) == ""




def _checker(tmp_path: Path) -> UpdateChecker:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"updates": {"remote": "https://example.test/x.git"}}))
    return UpdateChecker(
        config_path=config,
        root=tmp_path,
        cache_path=tmp_path / "cache.json",
    )


def test_outcome_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.2.3", root=tmp_path)
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: ["1.2.2", "1.2.3"])
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_CURRENT
    assert status.latest_version == "1.2.3"
    assert status.reason == ""


def test_outcome_update_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.2.3", root=tmp_path)
    monkeypatch.setattr(
        update_check, "fetch_remote_tags", lambda remote: ["1.2.3", "1.10.0", "1.9.0"]
    )
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_UPDATE_AVAILABLE
    assert status.latest_version == "1.10.0"
    assert status.upgrade_command


def test_outcome_unknown_when_remote_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.2.3", root=tmp_path)

    def boom(remote: str) -> list[str]:
        raise UpdateCheckError("could not reach the release remote: offline")

    monkeypatch.setattr(update_check, "fetch_remote_tags", boom)
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_UNKNOWN
    assert status.status != STATUS_CURRENT
    assert "offline" in status.reason
    assert status.latest_version == ""


def test_outcome_unknown_when_version_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: ["9.9.9"])
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_UNKNOWN
    assert status.reason


def test_outcome_unknown_when_not_on_a_release_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDE_APP_VERSION", "1.2.3-4-gdeadbee")
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: ["1.2.3"])
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_UNKNOWN
    assert "release tag" in status.reason


def test_outcome_unknown_when_remote_has_no_release_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.2.3", root=tmp_path)
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: [])
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_UNKNOWN


def test_status_is_cached_and_reloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.2.3", root=tmp_path)
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: ["2.0.0"])
    first = _checker(tmp_path)
    first.refresh()
    reloaded = _checker(tmp_path).status()
    assert reloaded.status == STATUS_UPDATE_AVAILABLE
    assert reloaded.checked_at > 0


def test_malformed_cache_is_not_a_passing_check(tmp_path: Path) -> None:
    (tmp_path / "cache.json").write_text("{ garbage")
    assert _checker(tmp_path).status().status == STATUS_UNKNOWN


def test_configured_remote_overrides_origin(tmp_path: Path) -> None:
    assert _checker(tmp_path).resolve_remote() == "https://example.test/x.git"




def test_fallback_remote_is_the_ruled_on_repo_not_the_other_one() -> None:
    assert FALLBACK_REMOTE == "https://github.com/NyedisInc/CarnivoreAI.git"
    assert "ccsliinc" not in FALLBACK_REMOTE
    assert FALLBACK_REMOTE != "https://github.com/example-owner/CloudeCode.git"


def test_default_upgrade_command_points_at_the_ruled_on_repo() -> None:
    assert DEFAULT_UPGRADE_COMMAND == (
        "open https://github.com/NyedisInc/CarnivoreAI/releases/latest"
    )
    assert "ccsliinc" not in DEFAULT_UPGRADE_COMMAND




def test_fallback_remote_is_sourced_from_the_release_repo_constant() -> None:
    from src.core.product_identity import RELEASE_REPO

    assert RELEASE_REPO == "NyedisInc/CarnivoreAI"
    assert FALLBACK_REMOTE == f"https://github.com/{RELEASE_REPO}.git"
    assert DEFAULT_UPGRADE_COMMAND == (
        f"open https://github.com/{RELEASE_REPO}/releases/latest"
    )
    assert "CloudeCodeDev" not in FALLBACK_REMOTE
    assert "CloudeCodeDev" not in DEFAULT_UPGRADE_COMMAND


def test_a_legacy_named_origin_is_still_recognized_as_this_apps_own_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "legacy-named-clone"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example-owner/CloudeCodeDev.git"],
        cwd=repo, check=True, capture_output=True,
    )

    assert update_check.discover_origin_remote(repo) == (
        "https://github.com/example-owner/CloudeCodeDev.git"
    )

    config = tmp_path / "config.json"
    config.write_text("{}")
    checker = UpdateChecker(
        config_path=config, root=repo, cache_path=tmp_path / "legacy-cache.json"
    )
    assert checker.resolve_remote() == "https://github.com/example-owner/CloudeCodeDev.git"


def test_a_future_named_origin_is_also_recognized_with_no_further_code_change(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "future-named-clone"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/NyedisInc/CarnivoreAI.git"],
        cwd=repo, check=True, capture_output=True,
    )

    config = tmp_path / "config.json"
    config.write_text("{}")
    checker = UpdateChecker(
        config_path=config, root=repo, cache_path=tmp_path / "future-cache.json"
    )
    assert checker.resolve_remote() == "https://github.com/NyedisInc/CarnivoreAI.git"


def test_real_repo_numbers_never_offer_a_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.4.3", root=tmp_path)
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: ["1.0.36"])
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_CURRENT
    assert status.status != STATUS_UPDATE_AVAILABLE


def test_an_unreachable_private_remote_is_unknown_not_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.4.3", root=tmp_path)

    def _refuse(remote: str) -> list[str]:
        raise update_check.UpdateCheckError(
            "could not reach the release remote: repository not found"
        )

    monkeypatch.setattr(update_check, "fetch_remote_tags", _refuse)
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_UNKNOWN
    assert status.reason



EXPECTED_UPSTREAM_REPO = "NyedisInc/CarnivoreAI"


def test_the_fallback_remote_is_the_upstream_product_repo() -> None:
    assert FALLBACK_REMOTE == f"https://github.com/{EXPECTED_UPSTREAM_REPO}.git"


def test_the_offered_upgrade_command_points_at_the_same_repo() -> None:
    assert EXPECTED_UPSTREAM_REPO in DEFAULT_UPGRADE_COMMAND
    assert DEFAULT_UPGRADE_COMMAND.endswith("/releases/latest")


def test_a_latest_older_than_the_install_reads_current_not_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    write_version_file("1.2.1", root=tmp_path)
    monkeypatch.setattr(
        update_check, "fetch_remote_tags", lambda remote: ["1.0.35", "1.0.36"]
    )
    status = _checker(tmp_path).refresh()
    assert status.status == STATUS_CURRENT
    assert status.status != STATUS_UPDATE_AVAILABLE
    assert parse_version(status.current_version) == (1, 2, 1)
    assert parse_version(status.latest_version) == (1, 0, 36)


def test_a_packaged_install_with_no_git_entry_asks_nobody_and_answers_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api import version_routes
    from src.core.app_update import store

    server_dir = _production_layout(tmp_path)
    write_version_file("1.2.3", root=server_dir)
    ran: list = []
    monkeypatch.setattr(update_check, "fetch_remote_tags", lambda remote: ran.append(remote) or ["9.9.9"])
    monkeypatch.setattr(update_check.subprocess, "run", lambda *a, **k: ran.append(a) or None)
    checker = UpdateChecker(config_path=server_dir / "config.json", root=server_dir, cache_path=server_dir / "cache.json")
    assert checker.applicable() is False
    assert checker.refresh() is None
    assert ran == [] and not (server_dir / "cache.json").exists()
    monkeypatch.setattr(store, "status", lambda: {"attached": False})
    monkeypatch.setattr(version_routes, "_checker", checker)
    import asyncio
    monkeypatch.setattr(version_routes, "_datastore_block", lambda: {})
    assert asyncio.run(version_routes.get_version())["update"] is None
    (server_dir / ".git").mkdir()
    assert checker.applicable() is True
