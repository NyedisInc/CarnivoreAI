
from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, Dict

import pytest

from src.core.pack.jobs import engine_run, policy as policy_mod
from src.core.pack.jobs.types import CollectAnswer, JobError, JobRequest, JobState, LandResult
from tests.python.pack.jobs.test_pack_jobs_agent_engine import rig, seed  # noqa: F401

SETTINGS = ".claude/settings.json"


def _wire(rig: Any, monkeypatch: pytest.MonkeyPatch, peer: str, fetch_fails: bool = False) -> Dict[str, Any]:
    seen: Dict[str, Any] = {"consumed": 0}
    answer = CollectAnswer(blob_id="blob", result_commit="c" * 40, changed=1)

    async def collect(_job: str) -> CollectAnswer:
        return answer

    async def fetch_result(_job: str, _answer: CollectAnswer, _state: Any) -> str:
        if fetch_fails:
            raise JobError("far_transfer_failed", "the download ended early", 502)
        return "p"

    def fetch_bundle(*_a: Any, **kw: Any) -> str:
        seen["fsck"] = kw.get("fsck")
        return "c" * 40

    rig.target.collect, rig.target.fetch_result = collect, fetch_result
    monkeypatch.setattr(engine_run.bundle_io, "fetch_bundle", fetch_bundle)
    monkeypatch.setattr(engine_run.bundle_io, "consumed", lambda *_a, **_k: seen.update(consumed=seen["consumed"] + 1))
    monkeypatch.setattr(rig, "_is_child_of", lambda *_a: True)
    monkeypatch.setattr(engine_run.land, "land", lambda *_a, **kw: seen.update(skip=tuple(kw["skip"])) or LandResult(applied=["o"]))
    return seen


def _land(rig: Any, peer: str) -> None:
    rec = dataclasses.replace(seed(rig, JobState.RUNNING, body="command", snapshot_commit="a" * 40), peer_install_id=peer)
    ctx = {"snap": {"toplevel": "/x/p", "scope": ""}, "request": {}}
    req = JobRequest(command="true", folder="/x/p", kind="suite", caller_session="ses_t", time_cap_s=60)
    asyncio.run(rig._collect_and_land(rec, ctx, req, policy_mod.Policy(project_uid="uid-test-0001"), "side"))


def test_an_ssh_result_never_lands_harness_settings_and_is_fetched_with_fsck(rig, monkeypatch) -> None:
    seen = _wire(rig, monkeypatch, "ssh:abc")
    _land(rig, "ssh:abc")
    assert SETTINGS in seen["skip"] and ".mcp.json" in seen["skip"] and seen["fsck"] is True


def test_a_paired_result_keeps_the_old_landing_and_skips_fsck(rig, monkeypatch) -> None:
    seen = _wire(rig, monkeypatch, "iid-b")
    _land(rig, "iid-b")
    assert seen["skip"] == () and seen["fsck"] is False and seen["consumed"] == 1


def test_a_paired_blob_is_not_consumed_after_a_failed_fetch_but_a_download_is(rig, monkeypatch) -> None:
    seen = _wire(rig, monkeypatch, "iid-b", fetch_fails=True)
    with pytest.raises(JobError):
        _land(rig, "iid-b")
    assert seen["consumed"] == 0
