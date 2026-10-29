
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.api import stats_maintenance_routes as routes
from src.core.stats import reset


def _request() -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(stats_scheduler=None)))


def test_an_unexpected_error_fails_the_job_instead_of_leaving_it_running(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(store: object, job: reset.ClearJob) -> None:
        raise KeyError("answers.purge broke")

    monkeypatch.setattr(routes.reset, "clear_stats", boom)
    job = reset.ClearJob(state="running")
    asyncio.run(routes._clear(_request(), object(), job))
    assert job.state == "failed"
    assert job.error == "KeyError"
    assert "answers.purge" not in job.error, "the public error is the type name only"


def test_the_known_failures_still_fail_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    def full(store: object, job: reset.ClearJob) -> None:
        raise OSError("disk")

    monkeypatch.setattr(routes.reset, "clear_stats", full)
    job = reset.ClearJob(state="running")
    asyncio.run(routes._clear(_request(), object(), job))
    assert (job.state, job.error) == ("failed", "OSError")
