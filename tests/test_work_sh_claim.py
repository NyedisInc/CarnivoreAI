
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORK_SH_CLAUDE = REPO / ".claude" / "skills" / "work" / "work.sh"
WORK_SH_AGENTS = REPO / ".agents" / "skills" / "work" / "work.sh"
TRUNK_REMOTE_SH = REPO / "scripts" / "lib" / "trunk-remote.sh"

FIXED_PR_CREATE = (
    '    | g pr create -R "$REPO" --draft -B "$BASE" -H "$branch" \\\n'
    '        -t "claim #$n: $slug" -F - >/dev/null || return 3\n'
)
UNFIXED_PR_CREATE = (
    '    | g pr create -R "$REPO" --draft -B "$BASE" -H "$branch" -F - >/dev/null || return 3\n'
)

GH_STUB = r"""#!/usr/bin/env bash
# Stub gh - see tests/test_work_sh_claim.py for the contract.
set -uo pipefail

: "${GH_STUB_LOG:?GH_STUB_LOG must be set}"
: "${GH_STUB_BARE:?GH_STUB_BARE must be set}"
: "${GH_STUB_STATE:?GH_STUB_STATE must be set}"
ENFORCE_TITLE="${GH_STUB_ENFORCE_TITLE:-1}"

{ printf '%s\0' "$@"; printf '\n'; } >> "$GH_STUB_LOG"

sub="${1:-}"; shift || true
action="${1:-}"; shift || true

case "$sub $action" in
  "issue develop")
    base="" branch=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -R) shift 2 ;;
        -b) base="$2"; shift 2 ;;
        -n) branch="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    git -C "$GH_STUB_BARE" branch "$branch" "$base" >/dev/null
    exit $?
    ;;

  "issue view")
    if [ -f "$GH_STUB_STATE/pr_number" ]; then
      cat "$GH_STUB_STATE/pr_number"
    fi
    exit 0
    ;;

  "pr create")
    title=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -t|--title) title="$2"; shift 2 ;;
        -R|-B|-H|-F|--body-file) shift 2 ;;
        --draft) shift ;;
        *) shift ;;
      esac
    done
    cat >/dev/null
    if [ "$ENFORCE_TITLE" = "1" ] && [ -z "$title" ]; then
      echo 'must provide `--title` and `--body` (or `--fill` or `fill-first` or `--fillverbose`) when not running interactively' >&2
      exit 1
    fi
    n=$(( $(cat "$GH_STUB_STATE/pr_counter" 2>/dev/null || echo 100) + 1 ))
    echo "$n" > "$GH_STUB_STATE/pr_counter"
    echo "$n" > "$GH_STUB_STATE/pr_number"
    printf '%s\n' "$title" > "$GH_STUB_STATE/pr_title"
    echo "https://github.com/stub/repo/pull/$n"
    exit 0
    ;;

  "pr list")
    if [ -f "$GH_STUB_STATE/pr_number" ]; then
      cat "$GH_STUB_STATE/pr_number"
    fi
    exit 0
    ;;

  "api user")
    # cmd_reserve builds its RESERVED body line with `g api user --jq .login`.
    echo "stub-user"
    exit 0
    ;;

  *)
    echo "gh-stub: unhandled invocation: $sub $action $*" >&2
    exit 1
    ;;
esac
"""


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    done = _run(["git", "-C", str(repo), *args])
    assert done.returncode == 0, f"git {args} failed: {done.stderr}"
    return done


def _make_fixture_repo(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "origin.git"
    _run(["git", "init", "--bare", "-q", str(bare)])

    work_repo = tmp_path / "work-repo"
    work_repo.mkdir()
    _git(work_repo, "init", "-q", "-b", "master")
    _git(work_repo, "config", "user.email", "test@example.com")
    _git(work_repo, "config", "user.name", "Test")
    (work_repo / "README.md").write_text("fixture\n")
    _git(work_repo, "add", "README.md")
    _git(work_repo, "commit", "-q", "-m", "init")
    _git(work_repo, "remote", "add", "origin", str(bare))
    _git(work_repo, "push", "-q", "-u", "origin", "master")

    lib_dir = work_repo / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "trunk-remote.sh").write_text(TRUNK_REMOTE_SH.read_text())
    return work_repo, bare


def _write_gh_stub(bin_dir: Path) -> None:
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_claim(
    work_sh_text: str,
    tmp_path: Path,
    *,
    subcommand_args: list[str] | None = None,
    enforce_title: str = "1",
) -> tuple[subprocess.CompletedProcess, Path]:
    subcommand_args = subcommand_args or ["claim", "42", "my-slug"]
    work_repo, bare = _make_fixture_repo(tmp_path)

    script = tmp_path / "work.sh"
    script.write_text(work_sh_text)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_gh_stub(bin_dir)

    state = tmp_path / "gh-state"
    state.mkdir()
    log = tmp_path / "gh-calls.log"
    worktree_root = tmp_path / "worktrees"

    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GH_TOKEN": "fake-token-for-test",
            "WORK_REPO": "stub/repo",
            "WORK_BASE": "master",
            "CLOUDE_TRUNK_REMOTE": "origin",
            "CLOUDE_WORKTREE_ROOT": str(worktree_root),
            "GH_STUB_LOG": str(log),
            "GH_STUB_BARE": str(bare),
            "GH_STUB_STATE": str(state),
            "GH_STUB_ENFORCE_TITLE": enforce_title,
        }
    )
    done = _run(["bash", str(script), *subcommand_args], cwd=work_repo, env=env)
    return done, log


def _pr_create_calls(log_path: Path) -> list[list[str]]:
    if not log_path.exists():
        return []
    calls = []
    for line in log_path.read_bytes().split(b"\n"):
        if not line:
            continue
        argv = [p.decode() for p in line.split(b"\0") if p != b""]
        if argv[:2] == ["pr", "create"]:
            calls.append(argv)
    return calls


class TestGhClientSideBehavior:

    pytestmark = pytest.mark.skipif(
        shutil.which("gh") is None, reason="gh binary not on PATH"
    )

    def test_pr_create_with_no_title_refuses_non_interactively(self) -> None:
        done = _run(
            [
                "gh",
                "pr",
                "create",
                "-R",
                "Example-owner/CarnivoreAIDev",
                "--draft",
                "-B",
                "master",
                "-H",
                "this-branch-does-not-exist-zzz",
                "-F",
                "-",
            ],
            input="Closes #999999\n",
        )
        assert done.returncode != 0
        assert "--title" in done.stderr
        assert "not running interactively" in done.stderr

    def test_pr_create_with_title_gets_past_the_flag_check(self) -> None:
        done = _run(
            [
                "gh",
                "pr",
                "create",
                "-R",
                "Example-owner/CarnivoreAIDev",
                "--draft",
                "-B",
                "master",
                "-H",
                "this-branch-does-not-exist-zzz",
                "-t",
                "claim #999999: test",
                "-F",
                "-",
            ],
            input="Closes #999999\n",
        )
        assert done.returncode != 0
        assert "not running interactively" not in done.stderr


class TestClaimAgainstStubbedGh:

    def test_unfixed_pr_create_call_fails_non_interactively(
        self, tmp_path: Path
    ) -> None:
        current = WORK_SH_CLAUDE.read_text()
        assert current.count(FIXED_PR_CREATE) == 1, (
            "expected fix text not found verbatim in work.sh; "
            "update FIXED_PR_CREATE/UNFIXED_PR_CREATE if the pr create call changed"
        )
        unfixed = current.replace(FIXED_PR_CREATE, UNFIXED_PR_CREATE)

        done, log = _run_claim(unfixed, tmp_path)

        assert done.returncode == 3, (done.stdout, done.stderr)
        calls = _pr_create_calls(log)
        assert len(calls) == 1
        assert "-t" not in calls[0] and "--title" not in calls[0]

    def test_fixed_pr_create_call_carries_the_claim_title(
        self, tmp_path: Path
    ) -> None:
        done, log = _run_claim(WORK_SH_CLAUDE.read_text(), tmp_path)

        assert done.returncode == 0, (done.stdout, done.stderr)
        assert "claimed issue 42 as PR #101" in done.stdout
        calls = _pr_create_calls(log)
        assert len(calls) == 1
        assert "-t" in calls[0]
        assert calls[0][calls[0].index("-t") + 1] == "claim #42: my-slug"

    def test_reserve_uses_the_same_claim_title(self, tmp_path: Path) -> None:
        done, log = _run_claim(
            WORK_SH_CLAUDE.read_text(),
            tmp_path,
            subcommand_args=["reserve", "43", "later-slug", "2026-10-01"],
        )
        assert done.returncode == 0, (done.stdout, done.stderr)
        calls = _pr_create_calls(log)
        assert calls[0][calls[0].index("-t") + 1] == "claim #43: later-slug"


def test_agents_copy_is_byte_identical_to_claude_copy() -> None:
    assert WORK_SH_CLAUDE.read_bytes() == WORK_SH_AGENTS.read_bytes()
