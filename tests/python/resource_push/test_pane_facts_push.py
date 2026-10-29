
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List

from src.core import resource_push
from src.core.resource_push import topics
from src.core.resource_push.pane_facts_watch import PaneFactsWatch
from src.core.session_pane_facts import find_git_head, git_branch, read_head_branch


def _row(cwd: str, command: str = "zsh", width: int = 80, height: int = 24) -> Dict[str, Any]:
    return {"pane_current_path": cwd, "pane_current_command": command,
            "pane_width": width, "pane_height": height}


def _repo(root: Path, branch: str = "master") -> Path:
    (root / ".git").mkdir(parents=True)
    head = root / ".git" / "HEAD"
    head.write_text(f"ref: refs/heads/{branch}\n")
    return head


def test_a_change_is_published_once_and_a_quiet_pass_publishes_nothing(tmp_path: Path) -> None:
    sent: List[str] = []
    watch = PaneFactsWatch(notify=sent.append)
    folder = tmp_path / "plain"
    folder.mkdir()
    assert watch.observe("ses_1", _row(str(folder))) is False
    for _ in range(5):
        assert watch.observe("ses_1", _row(str(folder))) is False
    assert sent == []
    assert watch.observe("ses_1", _row(str(folder), command="vim")) is True
    assert watch.observe("ses_1", _row(str(folder), command="vim", width=120)) is True
    assert watch.observe("ses_1", _row(str(folder), command="vim", width=120)) is False
    assert sent == [topics.keyed(topics.PANE_FACTS, "ses_1")] * 2


def test_the_branch_is_reread_only_when_head_moves(tmp_path: Path) -> None:
    sent: List[str] = []
    watch = PaneFactsWatch(notify=sent.append)
    head = _repo(tmp_path)
    watch.observe("ses_1", _row(str(tmp_path)))
    assert watch.observe("ses_1", _row(str(tmp_path))) is False
    head.write_text("ref: refs/heads/feature\n")
    os.utime(head, ns=(1, head.stat().st_mtime_ns + 10_000_000))
    assert watch.observe("ses_1", _row(str(tmp_path))) is True
    assert sent == ["pane_facts:ses_1"]
    reads: List[Path] = []
    real = read_head_branch
    import src.core.resource_push.pane_facts_watch as module
    module.read_head_branch = lambda path: (reads.append(path), real(path))[1]
    try:
        for _ in range(3):
            watch.observe("ses_1", _row(str(tmp_path)))
    finally:
        module.read_head_branch = real
    assert reads == []


def test_a_cwd_change_into_another_repo_changes_the_branch(tmp_path: Path) -> None:
    sent: List[str] = []
    watch = PaneFactsWatch(notify=sent.append)
    one, two = tmp_path / "one", tmp_path / "two"
    _repo(one, "a")
    _repo(two, "b")
    watch.observe("ses_1", _row(str(one)))
    assert watch.observe("ses_1", _row(str(two))) is True
    assert git_branch(str(two)) == "b"


def test_retain_forgets_a_departed_session(tmp_path: Path) -> None:
    watch = PaneFactsWatch(notify=lambda _t: None)
    watch.observe("ses_1", _row(str(tmp_path)))
    watch.retain(set())
    assert watch.observe("ses_1", _row(str(tmp_path), command="vim")) is False


def test_git_helpers_keep_their_old_answers(tmp_path: Path) -> None:
    head = _repo(tmp_path / "r")
    assert git_branch(str(tmp_path / "r")) == "master"
    head.write_text("0123456789abcdef\n")
    assert git_branch(str(tmp_path / "r")) == "0123456"
    wt = tmp_path / "wt"
    wt.mkdir()
    gitdir = tmp_path / "gd"
    gitdir.mkdir()
    (gitdir / "HEAD").write_text("ref: refs/heads/w\n")
    (wt / ".git").write_text(f"gitdir: {gitdir}\n")
    assert find_git_head(str(wt)) == gitdir / "HEAD"
    assert git_branch(str(wt)) == "w"


def test_a_keyed_topic_is_accepted_and_coalesced() -> None:
    loop = asyncio.new_event_loop()
    frames: List[Dict[str, Any]] = []
    resource_push.install(lambda f: frames.append(f) or 1, loop=loop, window_seconds=0.02)
    try:
        key = topics.keyed(topics.PANE_FACTS, "adopted:x")
        for _ in range(4):
            resource_push.notify(key)
        resource_push.notify("pane_facts_bogus:1")
        loop.run_until_complete(asyncio.sleep(0.1))
    finally:
        resource_push.uninstall()
        loop.close()
    assert [f["topics"] for f in frames] == [[key]]
    assert topics.family_of(key) == topics.PANE_FACTS


def test_the_listing_carries_cwd_and_size() -> None:
    from src.core.tmux_backend import TmuxBackend

    class Probe(TmuxBackend):
        socket_name = None

        def __init__(self) -> None:
            from src.core.tmux_transport.local import LocalTransport

            self._transport = LocalTransport()

        def _run_listing(self, *args: str):
            return None, "0|42|1755000000|%1|1755000001|177|60|1|1|1|3|s|zsh|/a|b/c\n"

    row = Probe().list_pane_status_all().sessions[0]
    assert (row["pane_width"], row["pane_height"], row["pane_current_path"]) == (177, 60, "/a|b/c")
