
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api import beast_mode_routes
from src.core.mcp import beast_store


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcp": {"enabled": True, "beast_mode": False}}))
    topics: list[str] = []
    monkeypatch.setattr(beast_mode_routes.settings, "auth_config_file", str(path))
    monkeypatch.setattr(beast_store.resource_push, "notify", topics.append)
    beast_mode_routes.settings.drop_auth_config_cache()
    return path, topics


def _mcp(path: Path) -> dict:
    return json.loads(path.read_text())["mcp"]


def _arm(**kw: object) -> None:
    asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True, **kw)))


def _patch(**kw: object) -> dict:
    return asyncio.run(beast_mode_routes.patch_beast_mode(beast_mode_routes.BeastAdjust(**kw)))


def test_prompts_change_live_and_since_and_auto_off_stay(config: tuple[Path, list[str]]) -> None:
    path, topics = config
    _arm(hours=4)
    before = _mcp(path)
    topics.clear()
    out = _patch(prompts=True)
    after = _mcp(path)
    assert after["beast_mode"] is True and after["beast_prompts"] is True and out["prompts"] is True
    assert after["beast_mode_since"] == before["beast_mode_since"], "not re-armed"
    assert after["beast_mode_until"] == before["beast_mode_until"], "hours omitted: auto-off untouched"
    assert topics == ["beast_mode"], "other windows are told"


def test_new_hours_restart_the_auto_off_from_now_and_null_clears_it(config: tuple[Path, list[str]]) -> None:
    path, _ = config
    _arm(prompts=True, hours=1)
    since = _mcp(path)["beast_mode_since"]
    _patch(hours=8)
    until = datetime.fromisoformat(_mcp(path)["beast_mode_until"])
    assert abs((until - datetime.now(timezone.utc)) - timedelta(hours=8)) < timedelta(minutes=1)
    assert _mcp(path)["beast_prompts"] is True and _mcp(path)["beast_mode_since"] == since
    _patch(hours=None)
    assert _mcp(path)["beast_mode_until"] is None and _mcp(path)["beast_mode_since"] == since


def test_a_change_while_disarmed_is_refused_with_409(config: tuple[Path, list[str]]) -> None:
    path, topics = config
    with pytest.raises(HTTPException) as err:
        _patch(prompts=True)
    assert err.value.status_code == 409
    assert _mcp(path)["beast_mode"] is False and not _mcp(path).get("beast_prompts") and topics == []


def test_a_change_after_the_auto_off_passed_is_refused(config: tuple[Path, list[str]]) -> None:
    path, _ = config
    _arm(hours=1)
    doc = json.loads(path.read_text())
    doc["mcp"]["beast_mode_until"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(doc))
    beast_mode_routes.settings.drop_auth_config_cache()
    with pytest.raises(HTTPException) as err:
        _patch(prompts=True)
    assert err.value.status_code == 409


def test_a_disarm_still_clears_prompts_and_the_auto_off(config: tuple[Path, list[str]]) -> None:
    path, _ = config
    _arm(prompts=True, hours=4)
    asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=False)))
    mcp = _mcp(path)
    assert mcp["beast_mode"] is False and mcp["beast_prompts"] is False and mcp["beast_mode_until"] is None


def test_an_empty_change_and_a_bad_hour_are_invalid(config: tuple[Path, list[str]]) -> None:
    _arm()
    with pytest.raises(ValueError):
        _patch()
    with pytest.raises(ValueError):
        _patch(hours=3)
