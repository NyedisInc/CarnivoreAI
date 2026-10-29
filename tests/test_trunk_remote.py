
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.lib.trunk_remote import TrunkRemoteError, trunk_remote_name

REPO = Path(__file__).resolve().parent.parent
LIB_SH = REPO / "scripts" / "lib" / "trunk-remote.sh"

TRUNK_SLUG = "example-owner/example-trunk"
TRUNK_HTTPS = f"https://github.com/{TRUNK_SLUG}.git"
TRUNK_HTTPS_NO_GIT = f"https://github.com/{TRUNK_SLUG}"
TRUNK_SSH = f"git@github.com:{TRUNK_SLUG}.git"
OTHER_URL = "git@github.com:ccsliinc/CloudeCode.git"


def _init_repo(tmp_path: Path, remotes: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for name, url in remotes.items():
        subprocess.run(["git", "remote", "add", name, url], cwd=repo, check=True)
    return repo


def bash_trunk_remote(
    repo: Path, *, env_extra: dict[str, str] | None = None
) -> tuple[int, str, str]:
    env = dict(os.environ)
    env.pop("CLOUDE_TRUNK_REMOTE", None)
    env.pop("CLOUDE_TRUNK_REPO", None)
    env.update(env_extra or {})
    script = f'. "{LIB_SH}"; trunk_remote_name "{repo}"'
    done = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env
    )
    return done.returncode, done.stdout.strip(), done.stderr.strip()



TRUNK_NAMED_ORIGIN = {"origin": TRUNK_HTTPS}
TRUNK_NAMED_ADAMDEV = {"origin": OTHER_URL, "adamdev": TRUNK_SSH}
NO_MATCH = {"origin": OTHER_URL}
TRUNK_NO_GIT_SUFFIX = {"origin": OTHER_URL, "adamdev": TRUNK_HTTPS_NO_GIT}
TRUNK_MIXED_CASE = {"origin": OTHER_URL, "adamdev": TRUNK_HTTPS.upper()}
BOTH_MATCH_ORIGIN_WINS = {"origin": TRUNK_HTTPS, "zzz": TRUNK_SSH}
BOTH_MATCH_NO_ORIGIN = {"zzz-remote": TRUNK_SSH, "aaa-remote": TRUNK_HTTPS}


class TestPythonHelper:

    def test_trunk_named_origin_resolves_to_origin(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_NAMED_ORIGIN)
        assert trunk_remote_name(repo) == "origin"

    def test_trunk_named_adamdev_with_unrelated_origin(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_NAMED_ADAMDEV)
        assert trunk_remote_name(repo, slug=TRUNK_SLUG) == "adamdev"

    def test_no_matching_remote_refuses(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, NO_MATCH)
        with pytest.raises(TrunkRemoteError, match="no configured remote"):
            trunk_remote_name(repo, slug=TRUNK_SLUG)

    def test_no_remotes_at_all_refuses(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, {})
        with pytest.raises(TrunkRemoteError, match="no remotes configured"):
            trunk_remote_name(repo)

    def test_not_a_git_checkout_refuses(self, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()
        with pytest.raises(TrunkRemoteError):
            trunk_remote_name(not_a_repo)

    def test_https_without_dot_git_suffix_matches(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_NO_GIT_SUFFIX)
        assert trunk_remote_name(repo, slug=TRUNK_SLUG) == "adamdev"

    def test_case_insensitive_host_and_slug(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_MIXED_CASE)
        assert trunk_remote_name(repo, slug=TRUNK_SLUG) == "adamdev"

    def test_multiple_matches_origin_wins(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, BOTH_MATCH_ORIGIN_WINS)
        assert trunk_remote_name(repo) == "origin"

    def test_multiple_matches_no_origin_first_in_git_remote_order(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path, BOTH_MATCH_NO_ORIGIN)
        listed = subprocess.run(
            ["git", "remote"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.split()
        assert listed == ["aaa-remote", "zzz-remote"]
        assert trunk_remote_name(repo, slug=TRUNK_SLUG) == "aaa-remote"

    def test_override_trusts_existing_remote_with_no_url_check(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path, NO_MATCH)
        assert trunk_remote_name(repo, override="origin") == "origin"

    def test_override_naming_missing_remote_refuses(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, NO_MATCH)
        with pytest.raises(TrunkRemoteError, match="CLOUDE_TRUNK_REMOTE"):
            trunk_remote_name(repo, override="nope")

    def test_slug_override_matches_a_different_repo(self, tmp_path: Path) -> None:
        repo = _init_repo(
            tmp_path, {"upstream": "git@github.com:someorg/somerepo.git"}
        )
        assert (
            trunk_remote_name(repo, slug="someorg/somerepo") == "upstream"
        )


class TestBashHelper:

    def test_trunk_named_origin_resolves_to_origin(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_NAMED_ORIGIN)
        rc, out, err = bash_trunk_remote(repo)
        assert (rc, out, err) == (0, "origin", "")

    def test_trunk_named_adamdev_with_unrelated_origin(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_NAMED_ADAMDEV)
        rc, out, err = bash_trunk_remote(repo, env_extra={"CLOUDE_TRUNK_REPO": TRUNK_SLUG})
        assert (rc, out, err) == (0, "adamdev", "")

    def test_no_matching_remote_refuses_with_no_stdout(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, NO_MATCH)
        rc, out, err = bash_trunk_remote(repo, env_extra={"CLOUDE_TRUNK_REPO": TRUNK_SLUG})
        assert rc == 1
        assert out == ""
        assert "no configured remote" in err

    def test_no_remotes_at_all_refuses(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, {})
        rc, out, err = bash_trunk_remote(repo)
        assert rc == 1
        assert out == ""
        assert "no remotes configured" in err

    def test_https_without_dot_git_suffix_matches(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_NO_GIT_SUFFIX)
        rc, out, _ = bash_trunk_remote(repo, env_extra={"CLOUDE_TRUNK_REPO": TRUNK_SLUG})
        assert (rc, out) == (0, "adamdev")

    def test_case_insensitive_host_and_slug(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, TRUNK_MIXED_CASE)
        rc, out, _ = bash_trunk_remote(repo, env_extra={"CLOUDE_TRUNK_REPO": TRUNK_SLUG})
        assert (rc, out) == (0, "adamdev")

    def test_multiple_matches_origin_wins(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, BOTH_MATCH_ORIGIN_WINS)
        rc, out, _ = bash_trunk_remote(repo)
        assert (rc, out) == (0, "origin")

    def test_multiple_matches_no_origin_first_in_git_remote_order(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path, BOTH_MATCH_NO_ORIGIN)
        rc, out, _ = bash_trunk_remote(repo, env_extra={"CLOUDE_TRUNK_REPO": TRUNK_SLUG})
        assert (rc, out) == (0, "aaa-remote")

    def test_override_trusts_existing_remote_with_no_url_check(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path, NO_MATCH)
        rc, out, _ = bash_trunk_remote(repo, env_extra={"CLOUDE_TRUNK_REMOTE": "origin"})
        assert (rc, out) == (0, "origin")

    def test_override_naming_missing_remote_refuses(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path, NO_MATCH)
        rc, out, err = bash_trunk_remote(repo, env_extra={"CLOUDE_TRUNK_REMOTE": "nope"})
        assert rc == 1
        assert out == ""
        assert "CLOUDE_TRUNK_REMOTE" in err

    def test_slug_override_matches_a_different_repo(self, tmp_path: Path) -> None:
        repo = _init_repo(
            tmp_path, {"upstream": "git@github.com:someorg/somerepo.git"}
        )
        rc, out, _ = bash_trunk_remote(
            repo, env_extra={"CLOUDE_TRUNK_REPO": "someorg/somerepo"}
        )
        assert (rc, out) == (0, "upstream")


def test_default_finds_trunk_by_repo_name_when_origin_is_another_repo(tmp_path: Path) -> None:
    trunk = "git@github.com:example-owner/CarnivoreAIDev.git"
    fork = _init_repo(tmp_path, {"origin": OTHER_URL, "adamdev": trunk})
    assert trunk_remote_name(fork) == "adamdev"
    assert bash_trunk_remote(fork)[:2] == (0, "adamdev")


def test_default_falls_back_to_origin_slug_and_refuses_without_a_github_origin(
    tmp_path: Path,
) -> None:
    clone = _init_repo(tmp_path, {"origin": OTHER_URL, "upstream": TRUNK_SSH})
    assert trunk_remote_name(clone) == "origin"
    assert bash_trunk_remote(clone)[:2] == (0, "origin")
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=other, check=True)
    subprocess.run(["git", "remote", "add", "upstream", TRUNK_SSH], cwd=other, check=True)
    with pytest.raises(TrunkRemoteError, match="CLOUDE_TRUNK_REPO"):
        trunk_remote_name(other)
    rc, out, err = bash_trunk_remote(other)
    assert (rc, out) == (1, "")
    assert "CLOUDE_TRUNK_REPO" in err


def test_python_and_bash_agree_on_this_repo_checkout() -> None:
    py_result = trunk_remote_name(REPO)
    rc, out, err = bash_trunk_remote(REPO)
    assert rc == 0, f"bash helper refused on the real checkout: {err}"
    assert out == py_result
