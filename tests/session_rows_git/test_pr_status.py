from __future__ import annotations

import asyncio
import json
import subprocess
from typing import List

import pytest

from src.core.session_git import pr_status
from src.core.session_git.pr_status import PrWatch, Target


def _node(number, state, branch, owner="me", draft=False, ci="SUCCESS", review=None, mergeable="MERGEABLE", threads=()):
    return {"number": number, "url": f"https://github.com/me/app/pull/{number}", "state": state, "isDraft": draft,
            "headRefName": branch, "headRepositoryOwner": {"login": owner}, "mergeable": mergeable,
            "reviewDecision": review, "reviewThreads": {"nodes": [{"isResolved": r} for r in threads]},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci}}}]}}


def _raw(*nodes) -> str:
    return json.dumps({"data": {"repository": {"pullRequests": {"nodes": list(nodes)}}}})


def test_parser_reads_draft_merged_conflict_red_ci_and_unresolved_threads() -> None:
    prs = pr_status.parse(_raw(
        _node(1, "OPEN", "feat/a", draft=True), _node(2, "MERGED", "feat/b"),
        _node(3, "OPEN", "feat/c", ci="FAILURE", mergeable="CONFLICTING", review="CHANGES_REQUESTED",
              threads=(False, True, False)),
        _node(4, "OPEN", "feat/c", owner="fork"), _node(5, "CLOSED", "feat/d")))
    by = {p["number"]: p for p in prs}
    assert by[1]["state"] == "draft" and by[2]["state"] == "merged" and by[5]["state"] == "closed"
    assert (by[3]["ci"], by[3]["conflict"], by[3]["review"], by[3]["unresolved"]) == ("red", True, "changes", 2)
    assert pr_status.match(prs, "feat/c", "me")["number"] == 3, "a fork's same-named branch must not collide"
    assert pr_status.repo_of("git@github.com:me/app.git") == ("me", "app")


def test_watch_calls_only_when_asked_caches_single_flights_and_backs_off() -> None:
    calls: List[tuple] = []
    now = [1000.0]
    answers = [_raw(_node(7, "OPEN", "feat/x"))]

    def call(account, repo):
        calls.append((account, repo))
        answer = answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    targets = {"/code/app": Target("feat/x", ("me", "app"), "me"), "/code/app2": Target("feat/x", ("me", "app"), "me"),
               "/code/gapped": Target(None, None, None), "/code/nogh": Target("main", ("me", "o"), None, "connect_gh")}
    watch = PrWatch(resolve=targets.__getitem__, call=call, clock=lambda: now[0])
    woke: List[int] = []

    async def tick() -> None:
        watch.tick(lambda: woke.append(1))
        if watch._task is not None:
            await watch._task

    async def run() -> None:
        await tick()
        assert calls == [], "nothing asked, nothing read"
        for f in targets:
            assert watch.badge(f) is None
        await tick()
        assert len(calls) == 1, "two sessions on one repo share one call; air gap and no account make none"
        for f in targets:
            watch.badge(f)
        assert watch.badge("/code/app")["number"] == 7 and watch.badge("/code/nogh") == {"hint": "connect_gh"}
        assert watch.badge("/code/gapped") is None
        await tick()
        assert len(calls) == 1, "cached for 60 s while the PR is open"
        now[0] += 61
        answers[0] = pr_status.RateLimited("x")
        watch.badge("/code/app")
        await tick()
        assert len(calls) == 2 and watch.badge("/code/app")["stale"] is True, "an error keeps the last result, stale"
        now[0] += 30
        watch.badge("/code/app")
        await tick()
        assert len(calls) == 2, "a rate limit backs off"

    asyncio.run(run())


def test_the_token_rides_the_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}
    monkeypatch.setattr(pr_status.github_account, "gh_path", lambda: "/usr/bin/gh")
    monkeypatch.setattr(pr_status.github_account, "token_env", lambda account: {"GH_TOKEN": "tok-secret-value"})

    def run(argv, *, air_gap, env=None, timeout=None, **_kw):
        seen["argv"], seen["env"] = list(argv), dict(env or {})
        return subprocess.CompletedProcess(argv, 0, stdout=_raw().encode(), stderr=b"")

    monkeypatch.setattr(pr_status.ladder, "run", run)
    pr_status.fetch("me", ("me", "app"))
    assert seen["env"] == {"GH_TOKEN": "tok-secret-value"}
    assert not any("tok-secret-value" in a for a in seen["argv"])
