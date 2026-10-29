
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List, Set

import pytest

from src.cplugs.host import capabilities

PINNED_READ_ONLY = {"get", "list"}


async def _no_rows() -> List[Any]:
    return []


def _request() -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def _public(obj: Any) -> Set[str]:
    return {n for n in dir(obj) if not n.startswith("_")}


def test_read_only_surface_is_pinned() -> None:
    assert _public(capabilities.RestrictedSessions(_no_rows)) == PINNED_READ_ONLY


def test_not_a_sessions_subclass() -> None:
    assert not isinstance(capabilities.RestrictedSessions(_no_rows), capabilities.Sessions)


def test_method_added_to_sessions_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities.Sessions, "brand_new", lambda self: "leak", raising=False)
    restricted = capabilities.RestrictedSessions(_no_rows, _request(), True, may_control=True)
    assert not hasattr(restricted, "brand_new")


@pytest.mark.parametrize("name", ["durable_keys", "stored_rows", "asleep_read", "list_allowed", "get_allowed", "start",
                                  "start_in_folder", "resume", "_infos"])
def test_privileged_members_unreachable(name: str) -> None:
    restricted = capabilities.RestrictedSessions(_no_rows, _request(), True, may_control=True)
    assert not hasattr(restricted, name)


def test_granted_actions_attach_only_with_grants() -> None:
    msg = capabilities.RestrictedSessions(_no_rows, _request(), True, may_control=False)
    assert _public(msg) == PINNED_READ_ONLY | {"message", "deliver", "booted"}
    full = capabilities.RestrictedSessions(_no_rows, _request(), True, may_control=True)
    assert _public(full) == PINNED_READ_ONLY | {"message", "deliver", "booted", "asleep", "wake"}
    assert _public(capabilities.RestrictedSessions(_no_rows, None, True, may_control=True)) == PINNED_READ_ONLY


def test_list_and_get_are_allow_listed() -> None:
    restricted = capabilities.RestrictedSessions(_no_rows)
    assert asyncio.run(restricted.list()) == []
    with pytest.raises(PermissionError):
        asyncio.run(restricted.get("remote:peer-1:ses_x"))


def test_control_defaults_to_deny() -> None:
    restricted = capabilities.RestrictedSessions(_no_rows, _request(), True)
    assert _public(restricted) == PINNED_READ_ONLY | {"message", "deliver", "booted"}
