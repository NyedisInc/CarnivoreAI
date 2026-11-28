
from __future__ import annotations

import asyncio

import pytest

from src.core.notify_caps import owner_reply_port
from src.plugins.taskmanager import owner_phone, reply
from src.plugins.taskmanager.rules import TaskManagerInvalid
from src.plugins.sdk import ports
from src.plugins.sdk.owner_reply import NAME, OwnerReplyDeclined, OwnerReplyRefused, OwnerReplyUnavailable


def _post(monkeypatch: pytest.MonkeyPatch, fn) -> None:
    monkeypatch.setattr(reply, "post_reply", fn)
    owner_phone.register(object())  # type: ignore[arg-type]


def test_no_port_means_unavailable() -> None:
    ports.unregister(NAME)
    with pytest.raises(OwnerReplyUnavailable):
        asyncio.run(owner_reply_port.owner_reply(object(), 1, "yes"))


def test_a_reply_goes_through_post_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    async def post(_ctx, item, text):
        return {"item": item, "message": text}

    _post(monkeypatch, post)
    try:
        assert asyncio.run(owner_reply_port.owner_reply(object(), 526, "ship it")) == {"item": 526, "message": "ship it"}
    finally:
        owner_phone.unregister()


def test_refusals_leave_as_the_sdk_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def card(*_a):
        raise reply.CardRefused("not waiting")

    async def invalid(*_a):
        raise TaskManagerInvalid("empty")

    try:
        _post(monkeypatch, card)
        with pytest.raises(OwnerReplyDeclined):
            asyncio.run(owner_reply_port.owner_reply(object(), 1, "x"))
        _post(monkeypatch, invalid)
        with pytest.raises(OwnerReplyRefused) as caught:
            asyncio.run(owner_reply_port.owner_reply(object(), 1, "x"))
        assert caught.value.code == TaskManagerInvalid.code
    finally:
        owner_phone.unregister()
