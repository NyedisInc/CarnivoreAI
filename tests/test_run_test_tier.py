
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import run_test_tier as tier


@pytest.mark.parametrize(
    "paths, expected",
    [
        (["client/js/app.js"], "client"),
        (["web/src/lib/mount.ts", "docs/ci.md"], "client"),
        (["src/core/tmux_backend.py"], "full"),
        (["client/js/app.js", "src/api/routes.py"], "full"),
        (["client/css/my theme.css", "docs/a doc.md"], "client"),
        (["client/js/app.js", "tests/test_x.py"], "full"),
        (["clientside/x.js"], "full"),
        ([], "full"),
        (["tests/x.node.mjs"], "client"),
        (["client/js/app.js", "scripts/verify_x.py"], "client"),
        (["scripts/verify_x.py", "src/foo.py"], "full"),
        (["tests/test_foo.py"], "full"),
        (["scripts/some_db_script.py"], "full"),
        (["scripts/archive/verify/verify_login_chrome.py"], "full"),
        (["web/src/lib/mount.ts", "features/changes/2026-01-01-1-x.json"], "client"),
        (["features/catalog/thing.json"], "client"),
        (["features/changes/x.json", "src/api/routes.py"], "full"),
        (["features/index.json"], "full"),
        (["features/capture/thing.json"], "client"),
        (["features/media/thing/main.png"], "client"),
        (["features/media/thing/sleep-wake.gif"], "client"),
        (["features/capture/thing.json", "src/api/routes.py"], "full"),
        (["features/media/thing/main.png", "src/api/routes.py"], "full"),
        (["features/media/thing/notes.txt"], "full"),
        (["features/schema.json"], "full"),
        (["FEATURES.md"], "full"),
        (["design/boards/20261013-bottom-bar/sidecar.json", "design/boards/README.md"], "client"),
        (["design/boards/20261013-bottom-bar/r002.html"], "client"),
        (["design/boards/20261013-bottom-bar/sub/x.html"], "full"),
        (["design/other/thing.md"], "full"),
        (["design/boards/x/sidecar.json", "src/api/routes.py"], "full"),
    ],
    ids=["client-only", "web-and-docs", "server", "mixed", "space-in-path",
         "client-plus-test", "prefix-lookalike", "empty-diff",
         "node-script-only", "client-plus-verify-script",
         "verify-script-plus-server", "plain-test-file", "db-script",
         "nested-verify-lookalike", "web-plus-features-change",
         "features-catalog-only", "features-plus-server",
         "features-generated-index-stays-full",
         "features-capture-only", "features-media-image-only",
         "features-media-gif-only", "features-capture-plus-server",
         "features-media-plus-server",
         "features-media-non-image-extension-stays-full",
         "features-generated-schema-stays-full",
         "features-generated-md-stays-full", "boards-data-only", "boards-page-only",
         "boards-nested-stays-full", "design-outside-boards-stays-full", "boards-plus-server"],
)
def test_route(paths: list[str], expected: str) -> None:
    assert tier.route(paths) == expected


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c",
         "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True,
    )


def test_changed_paths_reads_committed_uncommitted_and_untracked_with_spaces(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "web" / "src").mkdir(parents=True)
    (tmp_path / "web" / "src" / "a b.ts").write_text("1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "tag", "base")
    (tmp_path / "client" / "js").mkdir(parents=True)
    (tmp_path / "client" / "js" / "my file.js").write_text("1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "change")
    (tmp_path / "web" / "src" / "a b.ts").write_text("2\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "new doc.md").write_text("x\n")

    paths = tier.changed_paths(tmp_path, "base")

    assert paths == ["client/js/my file.js", "docs/new doc.md", "web/src/a b.ts"]
    assert tier.route(paths) == "client"


def test_an_unreadable_base_is_a_refusal_not_an_empty_diff(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "f").write_text("1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    with pytest.raises(tier.Refusal):
        tier.changed_paths(tmp_path, "no-such-ref")


def test_a_list_naming_a_missing_file_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tier, "REPO", tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_here.py").write_text("")
    listing = tmp_path / "tests" / "smoke_files.txt"
    listing.write_text("# a comment\ntests/test_here.py\n\ntests/test_gone.py\n")
    with pytest.raises(tier.Refusal, match="test_gone"):
        tier.read_list(listing)
    listing.write_text("# only a comment\n")
    with pytest.raises(tier.Refusal, match="lists nothing"):
        tier.read_list(listing)


def test_the_committed_lists_resolve() -> None:
    smoke = tier.read_list(tier.SMOKE_LIST)
    assert "tests/test_route_auth_inventory.py" in smoke
    assert len(smoke) >= 25
    full = tier.read_list(tier.FULL_TIER_LIST)
    assert "tests/test_restart_picker_renders.py" in full
    assert "tests/python/widgets/test_widget_fit_check.py" in full
    assert "tests/test_perf_harness_smoke.py" in tier.serial_only_files()


def test_client_selection_names_a_touched_file_and_the_folder_guards() -> None:
    picked = tier.client_python_selection(
        tier.REPO, ["client/js/navigation-generation.js"], set()
    )
    assert "tests/test_navigation_generation_renders.py" in picked
    assert "tests/test_no_remote_assets.py" in picked
    assert "tests/test_hook_tokens.py" not in picked


def test_route_reason_names_the_allowlist_and_a_blocking_path() -> None:
    allowlisted_only = ["scripts/verify_x.py"]
    assert "allowlist" in tier.route_reason(allowlisted_only, "client")

    mixed = ["client/js/app.js", "src/api/routes.py"]
    reason = tier.route_reason(mixed, tier.route(mixed))
    assert "src/api/routes.py" in reason

    assert "empty diff" in tier.route_reason([], "full")


def test_client_selection_forces_the_features_catalog_test_for_features_data(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(tier, "REPO", tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_features_catalog.py").write_text(
        "def test_it_validates():\n    assert True\n"
    )

    for changed in (["features/changes/2026-01-01-1-x.json"],
                    ["features/catalog/thing.json"],
                    ["features/capture/thing.json"],
                    ["features/media/thing/main.png"]):
        picked = tier.client_python_selection(tmp_path, changed, set())
        assert picked == ["tests/test_features_catalog.py"]

    non_media_ext = tier.client_python_selection(
        tmp_path, ["features/media/thing/notes.txt"], set()
    )
    assert non_media_ext == []

    already_run = tier.client_python_selection(
        tmp_path, ["features/changes/x.json"], {"tests/test_features_catalog.py"}
    )
    assert already_run == []

    unrelated = tier.client_python_selection(tmp_path, ["client/js/app.js"], set())
    assert unrelated == []


def test_client_selection_forces_the_repo_boards_test_for_board_data(tmp_path: Path) -> None:
    (tmp_path / "tests" / "python" / "cplugs" / "reviewboard").mkdir(parents=True)
    (tmp_path / tier.BOARDS_TEST).write_text("def test_it_scans():\n    assert True\n")
    for changed in (["design/boards/20261013-bottom-bar/sidecar.json"], ["design/boards/README.md"], ["design/boards/x/r002.html"]):
        assert tier.client_python_selection(tmp_path, changed, set()) == [tier.BOARDS_TEST]
    assert tier.client_python_selection(tmp_path, ["design/boards/x/sidecar.json"], {tier.BOARDS_TEST}) == []
    assert tier.client_python_selection(tmp_path, ["design/other/x.md"], set()) == []
