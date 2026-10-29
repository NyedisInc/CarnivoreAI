
from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from src.cplugs.publicboard import CPLUG
from src.cplugs.publicboard.service import PublicBoardService
from src.cplugs.publicboard.settings import (DEFAULT_BIND, DEFAULT_PORT, KEY_BIND, KEY_HOSTS, KEY_PORT, KEY_PROXIES, MAX_PORT, MIN_PORT,
                                             parse_settings)
from tests.python.cplugs.publicboard.harness import HOST, LOOPBACK


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


def settings(**over: Any) -> Dict[str, Any]:
    return {"port": free_port(), "bindAddress": LOOPBACK, "hostnames": HOST, "trustedProxies": "203.0.113.11", **over}


def answers(port: int) -> bool:
    try:
        socket.create_connection((LOOPBACK, port), timeout=2).close()
    except OSError:
        return False
    return True


def test_the_plugin_is_off_by_default_and_needs_the_review_board() -> None:
    manifest = CPLUG.manifest
    assert manifest.default_enabled is False and manifest.tier == "builtin"
    raw = json.loads((Path(__file__).resolve().parents[4] / "src" / "cplugs" / "publicboard" / "cplug.json").read_text())
    assert raw["requires"] == ["reviewboard"]


def test_the_manifest_settings_schema_matches_what_the_parser_reads() -> None:
    raw = json.loads((Path(__file__).resolve().parents[4] / "src" / "cplugs" / "publicboard" / "cplug.json").read_text())
    fields = raw["settings_schema"]["fields"]
    assert set(fields) == {KEY_PORT, KEY_BIND, KEY_HOSTS, KEY_PROXIES}
    defaults = {key: spec["default"] for key, spec in fields.items()}
    assert defaults == {KEY_PORT: DEFAULT_PORT, KEY_BIND: DEFAULT_BIND, KEY_HOSTS: "", KEY_PROXIES: ""}
    assert parse_settings(defaults) == parse_settings({}) and parse_settings({}).configured is False
    assert (fields[KEY_PORT]["min"], fields[KEY_PORT]["max"]) == (MIN_PORT, MAX_PORT)
    assert fields[KEY_PORT]["kind"] == "number" and {fields[k]["kind"] for k in (KEY_BIND, KEY_HOSTS, KEY_PROXIES)} == {"string"}


def test_apply_starts_and_stop_closes_the_socket() -> None:
    async def scenario() -> None:
        service, config = PublicBoardService(), settings()
        assert await service.apply(config) is True and service.listener is not None
        port = int(config["port"])
        assert await asyncio.to_thread(answers, port)
        await service.stop()
        assert service.listener is None
        assert not await asyncio.to_thread(answers, port)
        await service.stop()

    asyncio.run(scenario())


def test_new_settings_restart_the_listener_on_the_new_port() -> None:
    async def scenario() -> None:
        service, first, second = PublicBoardService(), settings(), settings()
        await service.apply(first)
        await service.apply(second)
        assert await asyncio.to_thread(answers, int(second["port"]))
        assert not await asyncio.to_thread(answers, int(first["port"]))
        await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [{"hostnames": ""}, {"trustedProxies": ""}, {"port": 8000}, {"bindAddress": "0.0.0.0"}, {"trustedProxies": "10.0.0.0/8"}])
def test_incomplete_or_invalid_settings_leave_it_off_and_never_raise(bad: Dict[str, Any]) -> None:
    async def scenario() -> None:
        service = PublicBoardService()
        config = settings(**bad)
        assert await service.apply(config) is False and service.listener is None
        if config["port"] != 8000:
            assert not await asyncio.to_thread(answers, int(config["port"]))

    asyncio.run(scenario())


def test_a_taken_port_is_logged_and_leaves_it_off() -> None:
    async def scenario() -> None:
        with socket.socket() as taken:
            taken.bind((LOOPBACK, 0))
            taken.listen(1)
            assert await PublicBoardService().apply(settings(port=taken.getsockname()[1])) is False

    asyncio.run(scenario())


def test_the_plugin_hooks_start_and_stop_the_listener() -> None:
    from src.cplugs.publicboard.service import SERVICE

    async def scenario() -> None:
        config = settings()
        ctx = SimpleNamespace(settings=config, settings_now=lambda: config)
        await CPLUG.on_start(ctx)
        port = int(config["port"])
        assert SERVICE.listener is not None and await asyncio.to_thread(answers, port)
        moved = settings()
        ctx.settings_now = lambda: moved
        await CPLUG.on_settings(ctx)
        assert await asyncio.to_thread(answers, int(moved["port"])) and not await asyncio.to_thread(answers, port)
        await CPLUG.on_stop(ctx)
        assert SERVICE.listener is None and not await asyncio.to_thread(answers, int(moved["port"]))

    asyncio.run(scenario())
