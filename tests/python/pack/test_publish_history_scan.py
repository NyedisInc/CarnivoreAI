
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from src.core.pack.transport import github_account, history_objects, ladder, publish, publish_git

_ALPHABET = "aB3dE5fG7hJ9kL1mN2pQ4rS6tU8vW0xY2zA4cD6e"
TOKEN = "gh" + "p_" + _ALPHABET[:36]
GITHUB_URL = "https://github.com/someone/demo.git"
_REAL_PUSH_URL = getattr(publish_git, "push_url", None)


@pytest.fixture(autouse=True)
def _sealed_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


GhCalls = List[Tuple[List[str], Dict[str, str]]]


@pytest.fixture
def gh_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GhCalls:
    calls: GhCalls = []
    real_run = ladder.run

    def fake_run(argv, **kwargs):
        if argv[0] == "/stub/gh":
            calls.append((list(argv), dict(kwargs.get("env") or {})))
            bare = _remote(tmp_path)
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
            subprocess.run(["git", "-C", kwargs["cwd"], "remote", "add", "origin", str(bare)], check=True)
            return subprocess.CompletedProcess(list(argv), 0, b"", b"")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(github_account, "gh_path", lambda: "/stub/gh")
    monkeypatch.setattr(github_account, "token_env", lambda account: {"GH_TOKEN": "stub"})
    monkeypatch.setattr(ladder, "run", fake_run)
    monkeypatch.setattr(publish_git, "push_url", lambda root: GITHUB_URL, raising=False)
    return calls


def _remote(root: Path) -> Path:
    return root.parent / f"{root.name}-origin.git"


def _remote_refs(root: Path) -> Dict[str, str]:
    out = subprocess.run(["git", "-C", str(_remote(root)), "for-each-ref", "--format=%(refname) %(objectname)"],
                         check=True, capture_output=True, text=True).stdout.split("\n")
    return dict(line.split(" ", 1) for line in out if line)


def _git(root: Path, *args: str) -> str:
    who = ["-c", "user.name=t", "-c", "user.email=t@localhost", "-c", "commit.gpgsign=false"]
    return subprocess.run(["git", "-C", str(root), *who, *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "--short", "HEAD")


def _repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text("node_modules/\n")
    (root / "readme.md").write_text("hello\n")
    _commit_all(root, "start")


def _publish(root: Path) -> dict:
    return publish.publish(str(root), name="demo", owner="someone", account="someone", air_gap=False)


def test_a_token_only_in_an_older_commit_refuses_the_publish(tmp_path: Path, gh_calls: GhCalls) -> None:
    _repo(tmp_path)
    (tmp_path / "keys.txt").write_text(f"GH_TOKEN={TOKEN}\n")
    planted = _commit_all(tmp_path, "add keys")
    (tmp_path / "keys.txt").unlink()
    _commit_all(tmp_path, "remove keys")
    with pytest.raises(publish.PublishRefused) as refused:
        _publish(tmp_path)
    assert refused.value.code == "secrets_found"
    assert refused.value.files == [f"keys.txt (commit {planted})"]
    assert TOKEN not in str(refused.value) and all(TOKEN not in f for f in refused.value.files)
    assert gh_calls == []


def test_a_token_in_head_with_a_clean_working_tree_refuses_the_publish(tmp_path: Path, gh_calls: GhCalls) -> None:
    _repo(tmp_path)
    (tmp_path / "keys.txt").write_text(f"GH_TOKEN={TOKEN}\n")
    planted = _commit_all(tmp_path, "add keys")
    (tmp_path / "keys.txt").unlink()
    with pytest.raises(publish.PublishRefused) as refused:
        _publish(tmp_path)
    assert refused.value.code == "secrets_found"
    assert refused.value.files == [f"keys.txt (commit {planted})"]
    assert gh_calls == []


def test_a_clean_history_publishes(tmp_path: Path, gh_calls: GhCalls) -> None:
    _repo(tmp_path)
    (tmp_path / "main.py").write_text("print('hi')\n")
    _commit_all(tmp_path, "code")
    assert _publish(tmp_path)["private"] is True
    assert len(gh_calls) == 1 and "--private" in gh_calls[0][0]
    assert _remote_refs(tmp_path) == {"refs/heads/main": _git(tmp_path, "rev-parse", "HEAD")}


def test_a_token_in_a_binary_blob_in_history_refuses(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "data.bin").write_bytes(b"\0\x01row" + TOKEN.encode() + b"\0\x02")
    _commit_all(tmp_path, "data")
    _git(tmp_path, "rm", "-q", "data.bin")
    _commit_all(tmp_path, "drop data")
    assert [f.split(" ")[0] for f in publish.scan_history_for_secrets(str(tmp_path))] == ["data.bin"]


def test_a_repo_with_no_commit_has_no_history_to_scan(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    assert publish.scan_history_for_secrets(str(tmp_path)) == []


def test_history_git_cannot_read_refuses_as_scan_failed(tmp_path: Path) -> None:
    _repo(tmp_path)
    blob = _git(tmp_path, "rev-parse", "HEAD:readme.md")
    os.chmod(tmp_path / ".git" / "objects" / blob[:2], 0o700)
    (tmp_path / ".git" / "objects" / blob[:2] / blob[2:]).rename(tmp_path / "moved-away")
    with pytest.raises(publish.PublishRefused) as refused:
        publish.scan_history_for_secrets(str(tmp_path))
    assert refused.value.code == "scan_failed"


def test_history_over_the_budget_refuses_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path)
    (tmp_path / "big.txt").write_text("x" * 500)
    _commit_all(tmp_path, "big")
    monkeypatch.setattr(publish, "MAX_TOTAL_SCAN_BYTES", 100)
    monkeypatch.setattr(publish, "holds_secret", lambda opener, remaining: pytest.fail("a blob was read"))
    with pytest.raises(publish.PublishRefused) as refused:
        publish.scan_history_for_secrets(str(tmp_path))
    assert refused.value.code == "scan_budget_exceeded" and refused.value.files[0] == "big.txt"


def _lfs_pointer(oid: str, size: int) -> str:
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n"


def test_a_token_in_a_commit_message_refuses_and_names_the_commit(tmp_path: Path, gh_calls: GhCalls) -> None:
    _repo(tmp_path)
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", f"rotate GH_TOKEN={TOKEN}")
    with pytest.raises(publish.PublishRefused) as refused:
        _publish(tmp_path)
    assert refused.value.code == "secrets_found"
    assert refused.value.files == [f"commit {_git(tmp_path, 'rev-parse', '--short', 'HEAD')} message"]
    assert gh_calls == []


def test_a_token_shaped_commit_header_is_not_read_as_the_message(tmp_path: Path) -> None:
    _repo(tmp_path)
    tree, parent = _git(tmp_path, "rev-parse", "HEAD^{tree}"), _git(tmp_path, "rev-parse", "HEAD")
    raw = (f"tree {tree}\nparent {parent}\nauthor t <t@l> 1 +0000\ncommitter t <t@l> 1 +0000\n"
           f"gpgsig {TOKEN}\n\nclean message\n")
    made = subprocess.run(["git", "-C", str(tmp_path), "hash-object", "-t", "commit", "-w", "--stdin"], input=raw, text=True,
                          check=True, capture_output=True).stdout.strip()
    _git(tmp_path, "update-ref", "HEAD", made)
    assert publish.scan_history_for_secrets(str(tmp_path)) == []


def test_the_push_carries_no_tag_even_when_config_and_inherited_settings_ask_for_follow_tags(
        tmp_path: Path, gh_calls: GhCalls, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "push.followTags")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'push.followtags'='true'")
    _repo(tmp_path)
    _git(tmp_path, "config", "push.followTags", "true")
    _git(tmp_path, "tag", "-a", "v1", "-m", f"key {TOKEN}")
    _publish(tmp_path)
    assert _remote_refs(tmp_path) == {"refs/heads/main": _git(tmp_path, "rev-parse", "HEAD")}
    assert "--push" not in gh_calls[0][0]


def test_the_push_turns_off_submodule_recursion() -> None:
    argv = publish_git.push_argv("/r", "/opt/gh dir/gh", "1a2b", "main")
    assert ["-c", "push.recurseSubmodules=no"] == argv[argv.index("push.recurseSubmodules=no") - 1:argv.index("push.recurseSubmodules=no") + 1]
    assert "credential.helper=!'/opt/gh dir/gh' auth git-credential" in argv and argv[-1] == "1a2b:refs/heads/main"


def test_an_lfs_object_holding_a_token_refuses_by_its_pointer_path(tmp_path: Path) -> None:
    _repo(tmp_path)
    oid = "ab" * 32
    store = tmp_path / ".git" / "lfs" / "objects" / oid[:2] / oid[2:4]
    store.mkdir(parents=True)
    (store / oid).write_text(f"GH_TOKEN={TOKEN}\n")
    (tmp_path / "model.bin").write_text(_lfs_pointer(oid, 50))
    planted = _commit_all(tmp_path, "add model")
    _git(tmp_path, "rm", "-q", "model.bin")
    _commit_all(tmp_path, "drop model")
    assert publish.scan_history_for_secrets(str(tmp_path)) == [f"model.bin (lfs object, commit {planted})"]


def test_an_lfs_object_missing_locally_refuses_as_scan_failed(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "model.bin").write_text(_lfs_pointer("cd" * 32, 50))
    _commit_all(tmp_path, "add model")
    with pytest.raises(publish.PublishRefused) as refused:
        publish.scan_history_for_secrets(str(tmp_path))
    assert refused.value.code == "scan_failed" and refused.value.files == ["model.bin (lfs object missing)"]


@pytest.mark.parametrize("hide", ["assume-unchanged", "skip-worktree"])
def test_with_no_commit_a_staged_token_hidden_from_the_disk_refuses(
        tmp_path: Path, gh_calls: GhCalls, hide: str) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    (tmp_path / "k.txt").write_text(f"GH_TOKEN={TOKEN}\n")
    _git(tmp_path, "add", "k.txt")
    _git(tmp_path, "update-index", f"--{hide}", "k.txt")
    if hide == "assume-unchanged":
        (tmp_path / "k.txt").write_text("clean\n")
    else:
        (tmp_path / "k.txt").rename(tmp_path.parent / f"{tmp_path.name}-moved-k.txt")
    with pytest.raises(publish.PublishRefused) as refused:
        _publish(tmp_path)
    assert refused.value.code == "secrets_found" and refused.value.files == ["k.txt (staged)"]
    assert gh_calls == [] and subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "-q", "--verify", "HEAD"],
                                             capture_output=True).returncode != 0


def test_a_file_named_head_does_not_break_the_scan(tmp_path: Path, gh_calls: GhCalls) -> None:
    _repo(tmp_path)
    (tmp_path / "HEAD").write_text("x\n")
    _commit_all(tmp_path, "headfile")
    _publish(tmp_path)
    assert len(gh_calls) == 1


def test_a_listing_past_the_object_cap_refuses_with_its_own_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path)
    monkeypatch.setattr(history_objects, "MAX_HISTORY_OBJECTS", 2)
    with pytest.raises(publish.PublishRefused) as refused:
        publish.scan_history_for_secrets(str(tmp_path))
    assert refused.value.code == "history_too_big" and refused.value.params == {"limit": "2"}
    from src.api.error_response import sentence_for

    assert "{limit}" in sentence_for("history_too_big", 409) and "objects" in sentence_for("history_too_big", 409)


def test_a_naming_timeout_keeps_the_hit_a_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path)
    (tmp_path / "keys.txt").write_text(f"GH_TOKEN={TOKEN}\n")
    _commit_all(tmp_path, "keys")
    real_run, real_stream = ladder.run, ladder.stream

    def slow_log(argv, **kwargs):
        if "log" in argv:
            raise subprocess.TimeoutExpired(argv, 1)
        return real_run(argv, **kwargs)

    def dead_log(argv, **kwargs):
        if "log" in argv:
            raise OSError("no git log")
        return real_stream(argv, **kwargs)

    monkeypatch.setattr(ladder, "run", slow_log)
    monkeypatch.setattr(ladder, "stream", dead_log)
    assert publish.scan_history_for_secrets(str(tmp_path)) == ["keys.txt"]


def test_two_flagged_messages_are_both_named_by_their_short_ids(tmp_path: Path) -> None:
    _repo(tmp_path)
    shorts = []
    for index in range(2):
        (tmp_path / f"f{index}.txt").write_text(f"{index}\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", f"rotate GH_TOKEN={TOKEN}")
        shorts.append(_git(tmp_path, "rev-parse", "--short", "HEAD"))
    assert sorted(publish.scan_history_for_secrets(str(tmp_path))) == sorted(f"commit {short} message" for short in shorts)


def test_a_commit_landing_during_the_scan_is_not_pushed(tmp_path: Path, gh_calls: GhCalls, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path)
    scanned = _git(tmp_path, "rev-parse", "HEAD")
    real_read = history_objects.read_batch

    def racing(root, ids):
        if not (tmp_path / "late.txt").exists():
            (tmp_path / "late.txt").write_text(f"GH_TOKEN={TOKEN}\n")
            _commit_all(tmp_path, "late")
        return real_read(root, ids)

    monkeypatch.setattr(history_objects, "read_batch", racing)
    _publish(tmp_path)
    assert _remote_refs(tmp_path) == {"refs/heads/main": scanned}


def test_a_pre_commit_hook_cannot_add_to_the_first_commit(tmp_path: Path, gh_calls: GhCalls) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    (tmp_path / "main.py").write_text("print('hi')\n")
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho 'GH_TOKEN={TOKEN}' > added.txt\ngit add added.txt\n")
    hook.chmod(0o755)
    _publish(tmp_path)
    pushed = _remote_refs(tmp_path)["refs/heads/main"]
    files = subprocess.run(["git", "-C", str(_remote(tmp_path)), "ls-tree", "-r", "--name-only", pushed],
                           check=True, capture_output=True, text=True).stdout.split()
    assert files == [".gitignore", "main.py"] and not (tmp_path / "added.txt").exists()
    assert _git(tmp_path, "rev-parse", "HEAD") == pushed and _git(tmp_path, "status", "--porcelain") == ""


def test_a_refused_first_publish_leaves_the_index_as_it_was(tmp_path: Path, gh_calls: GhCalls) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    (tmp_path / "k.txt").write_text(f"GH_TOKEN={TOKEN}\n")
    _git(tmp_path, "add", "k.txt")
    _git(tmp_path, "update-index", "--assume-unchanged", "k.txt")
    (tmp_path / "k.txt").write_text("clean\n")
    (tmp_path / "other.txt").write_text("untracked\n")
    index = tmp_path / ".git" / "index"
    before = index.read_bytes()
    with pytest.raises(publish.PublishRefused):
        _publish(tmp_path)
    assert index.read_bytes() == before
    assert [p.name for p in (tmp_path / ".git").iterdir() if p.name.startswith("index")] == ["index"]


def test_a_url_rewrite_that_redirects_the_push_refuses_and_pushes_nothing(
        tmp_path: Path, gh_calls: GhCalls, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish_git, "push_url", _REAL_PUSH_URL)
    _repo(tmp_path)
    real_run = ladder.run

    def github_origin(argv, **kwargs):
        done = real_run(argv, **kwargs)
        if argv[0] == "/stub/gh":
            _git(tmp_path, "remote", "set-url", "origin", GITHUB_URL)
            _git(tmp_path, "config", f"url.{_remote(tmp_path)}.insteadOf", "https://github.com/")
        return done

    monkeypatch.setattr(ladder, "run", github_origin)
    with pytest.raises(publish.PublishRefused) as refused:
        _publish(tmp_path)
    assert refused.value.code == "remote_mismatch" and _remote_refs(tmp_path) == {}


@pytest.mark.parametrize("url, ok", [
    ("https://github.com/someone/demo.git", True), ("git@github.com:Someone/Demo", True), ("ssh://git@github.com/someone/demo.git", True),
    ("https://github.com/someone/other.git", False), ("https://evil.example/someone/demo.git", False), ("/tmp/x/demo.git", False),
    ("https://github.com.evil.example/someone/demo.git", False),
])
def test_the_push_url_must_name_the_new_repo_on_github(url: str, ok: bool) -> None:
    assert publish_git.remote_matches(url, "someone", "demo") is ok


def test_a_detached_head_refuses_before_anything_is_created(tmp_path: Path, gh_calls: GhCalls) -> None:
    _repo(tmp_path)
    _git(tmp_path, "checkout", "-q", "--detach")
    with pytest.raises(publish.PublishRefused) as refused:
        _publish(tmp_path)
    assert refused.value.code == "detached_head" and gh_calls == []
    from src.api.error_response import sentence_for

    assert "branch" in sentence_for("detached_head", 409) and "insteadof" in sentence_for("remote_mismatch", 409)


def test_a_held_index_lock_refuses_before_the_first_commit_and_is_left_alone(tmp_path: Path, gh_calls: GhCalls) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "main.py").write_text("print('hi')\n")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("held by another git\n")
    with pytest.raises(publish.PublishRefused) as refused:
        _publish(tmp_path)
    assert refused.value.code == "git_failed" and gh_calls == []
    assert lock.read_text() == "held by another git\n"
    assert subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode != 0


def test_a_stale_private_index_does_not_seed_a_repo_with_no_index(tmp_path: Path, gh_calls: GhCalls) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "old.txt").write_text("left over\n")
    stale = tmp_path / ".git" / f"index{publish_git.PRIVATE_INDEX_SUFFIX}"
    stale_env = {**os.environ, "GIT_INDEX_FILE": str(stale)}
    subprocess.run(["git", "-C", str(tmp_path), "add", "old.txt"], env=stale_env, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "update-index", "--skip-worktree", "old.txt"], env=stale_env, check=True)
    (tmp_path / "old.txt").rename(tmp_path.parent / f"{tmp_path.name}-old.txt")
    (tmp_path / "main.py").write_text("print('hi')\n")
    _publish(tmp_path)
    pushed = _remote_refs(tmp_path)["refs/heads/main"]
    files = subprocess.run(["git", "-C", str(_remote(tmp_path)), "ls-tree", "-r", "--name-only", pushed],
                           check=True, capture_output=True, text=True).stdout.split()
    assert "old.txt" not in files and "main.py" in files


def test_the_push_child_gets_a_minimal_environment(tmp_path: Path, gh_calls: GhCalls, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANTED_SERVER_VARIABLE", "server-only")
    _repo(tmp_path)
    seen = tmp_path.parent / f"{tmp_path.name}-hook-env.txt"
    hook = tmp_path / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\nenv | cut -d= -f1 > '{seen}'\n")
    hook.chmod(0o755)
    _publish(tmp_path)
    names = set(seen.read_text().split())
    assert "GH_TOKEN" in names and "PLANTED_SERVER_VARIABLE" not in names
