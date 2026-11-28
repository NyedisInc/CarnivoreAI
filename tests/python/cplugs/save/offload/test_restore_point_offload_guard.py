
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.core.bookmarks import locate
from src.plugins.save import routes as save_routes
from src.plugins.save.offload import offload_routes
from src.plugins.save.port import RestorePoints
from src.plugins.save.vault import points as vault_points
from src.plugins.sdk import restore_points
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, ledger_of
from tests.python.cplugs.save.vault_helpers import World

CONV = conv_id(1)


@pytest.fixture
def offloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = build_fleet(tmp_path, monkeypatch, 1)
    assert {c.status for c in offload_routes._run("S1", False).conversations} == {"offloaded"}
    assert not world.transcript(CONV).exists()
    monkeypatch.setattr(save_routes.RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(save_routes.tf, "projects_dir", lambda: world.projects)
    return world


def newest_id(world: World) -> str:
    return vault_points.list_points(world.vault, CONV)[0]["id"]


def untouched(world: World) -> bool:
    return not world.transcript(CONV).exists() and ledger_of(world).get(CONV).state == "offloaded"  # type: ignore[union-attr]


def homes(world: World) -> dict:
    return {"claude": world.projects.parent, "claude/projects": world.projects}


def test_restore_point_refuses_an_offloaded_conversation(offloaded: World) -> None:
    with pytest.raises(vault_points.OffloadedError) as caught:
        vault_points.restore_point(offloaded.vault, CONV, newest_id(offloaded), homes(offloaded))
    assert "offload" in str(caught.value) and untouched(offloaded)


def test_restore_point_refuses_while_the_ledger_cannot_be_read(offloaded: World) -> None:
    ledger_of(offloaded).path.write_text("{ not json")
    with pytest.raises(vault_points.OffloadedError):
        vault_points.restore_point(offloaded.vault, CONV, newest_id(offloaded), homes(offloaded))
    assert not offloaded.transcript(CONV).exists()


def test_the_save_route_answers_409_offloaded(offloaded: World) -> None:
    with pytest.raises(HTTPException) as caught:
        asyncio.run(save_routes._restore(None, CONV, newest_id(offloaded), save_routes.RestoreBody()))  # type: ignore[arg-type]
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "offloaded"  # type: ignore[index]
    assert untouched(offloaded)


def test_the_port_and_bookmark_repair_refuse(offloaded: World, monkeypatch: pytest.MonkeyPatch) -> None:
    port = RestorePoints(lambda: offloaded.vault)
    with pytest.raises(restore_points.RestoreFailed) as caught:
        port.restore_newest(CONV, offloaded.projects)
    assert "offload" in str(caught.value) and untouched(offloaded)
    monkeypatch.setattr(restore_points, "get", lambda: port)
    monkeypatch.setattr(locate, "_roots", lambda: (offloaded.projects,))
    with pytest.raises(locate.TranscriptUnavailable) as repaired:
        locate.restore_from_points(CONV)
    assert "offload" in str(repaired.value) and untouched(offloaded)


def test_a_conversation_that_is_not_offloaded_still_restores(offloaded: World) -> None:
    ledger_of(offloaded).remove(CONV)
    done = vault_points.restore_point(offloaded.vault, CONV, newest_id(offloaded), homes(offloaded))
    assert done.status == "written" and offloaded.transcript(CONV).is_file()
