
from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.deepsearch.fallback_hook import FallbackPoint, IncomingFile
from src.plugins.save.engine import layout
from src.plugins.save.offload import constants as C
from src.plugins.save.offload import offload_routes, restore_routes
from src.plugins.save.offload.move import holding_root
from src.plugins.save.vault import adopt, retention
from src.plugins.save.vault import constants as K
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, ledger_of
from tests.python.cplugs.save.vault_helpers import World, jsonl

CONV = conv_id(1)


@pytest.fixture
def offloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = build_fleet(tmp_path, monkeypatch, 1)
    world.original = world.transcript(CONV).read_bytes()  # type: ignore[attr-defined]
    out = offload_routes._run("S1", False)
    assert {c.status for c in out.conversations} == {"offloaded"}
    return world


def incoming(rel: str, body: bytes, source_path: str) -> IncomingFile:
    return IncomingFile(role=K.ROLE_TRANSCRIPT, home="claude", rel=rel, source_path=source_path, length=len(body),
                        sha256=hashlib.sha256(body).hexdigest(), read=lambda: iter([body]))


def file_newer_point(world: World, body: bytes, source_path: Path) -> str:
    point = world.vault.manifests.newest(CONV)
    assert point is not None
    main = point.main()
    entry = adopt._entry_of(world.vault, incoming(main.rel, body, str(source_path)), set())
    point_id = layout.new_point_id(K.REASON_IMPORT, datetime.now(timezone.utc) + timedelta(days=1), set(world.vault.manifests.point_ids(CONV)))
    files = [entry if (f.home, f.rel) == (main.home, main.rel) else f for f in point.files]
    world.vault.manifests.write(replace(point, point_id=point_id, reason=K.REASON_IMPORT, created_epoch=point.created_epoch + 86400, files=files))
    assert world.vault.manifests.newest(CONV).point_id == point_id  # type: ignore[union-attr]
    return point_id


def held(world: World) -> list:
    folder = holding_root(world.state) / CONV
    return sorted(p for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


def test_a_restore_comes_from_the_verified_point_when_a_newer_differing_point_exists(offloaded: World) -> None:
    verified = ledger_of(offloaded).get(CONV).point_id  # type: ignore[union-attr]
    file_newer_point(offloaded, jsonl(4, seed=99), offloaded.transcript(CONV))
    out = restore_routes.run_restore("S1", None, False)
    assert [(c.status, c.point_id) for c in out.conversations] == [("written", verified)]
    assert offloaded.transcript(CONV).read_bytes() == offloaded.original  # type: ignore[attr-defined]
    assert ledger_of(offloaded).read() == {} and held(offloaded) == []


def test_a_dry_run_reports_the_verified_point_too(offloaded: World) -> None:
    verified = ledger_of(offloaded).get(CONV).point_id  # type: ignore[union-attr]
    file_newer_point(offloaded, jsonl(4, seed=98), offloaded.transcript(CONV))
    out = restore_routes.run_restore("S1", None, True)
    assert [(c.status, c.point_id) for c in out.conversations] == [("would_write", verified)]
    assert not offloaded.transcript(CONV).exists() and ledger_of(offloaded).get(CONV).state == C.STATE_OFFLOADED  # type: ignore[union-attr]


def test_a_held_file_is_kept_unless_the_destination_starts_with_its_own_bytes(offloaded: World) -> None:
    side = next(p for p in held(offloaded) if p.suffix == ".txt")
    side.write_bytes(b"x" + side.read_bytes()[1:])
    out = restore_routes.run_restore("S1", None, False)
    assert out.conversations[0].status == "written"
    assert side.is_file() and side.read_bytes().startswith(b"x"), "the only copy of those bytes was unlinked"
    assert ledger_of(offloaded).get(CONV).state == C.STATE_FAILED  # type: ignore[union-attr]


def test_retention_never_drops_the_offload_point_under_a_newer_point(offloaded: World, tmp_path: Path) -> None:
    verified = ledger_of(offloaded).get(CONV).point_id  # type: ignore[union-attr]
    elsewhere = tmp_path / "elsewhere.jsonl"
    elsewhere.write_bytes(jsonl(2, seed=7))
    file_newer_point(offloaded, jsonl(4, seed=97), elsewhere)
    newest = offloaded.vault.manifests.newest(CONV)
    assert retention.protection(offloaded.vault, CONV, newest) == retention.PROTECT_OFFLOADED  # type: ignore[arg-type]
    assert retention.thin_unit(offloaded.vault, CONV) == []
    assert verified in offloaded.vault.manifests.point_ids(CONV)
    ledger_of(offloaded).remove(CONV)
    assert verified in retention.thin_unit(offloaded.vault, CONV)


def fallback_point(body: bytes) -> FallbackPoint:
    return FallbackPoint(conversation_id=CONV, point_id="20991231T000000Z-import", reason=K.REASON_IMPORT, created_epoch=time.time(),
                         created_at="2099-12-31T00:00:00Z", family="claude", files=(incoming(f"projects/-Users-x-proj/{CONV}.jsonl", body, "/elsewhere/x.jsonl"),))


def test_an_import_over_an_offloaded_conversation_is_refused(offloaded: World) -> None:
    before = offloaded.vault.manifests.point_ids(CONV)
    [result] = adopt.adopt_points(offloaded.vault, [fallback_point(jsonl(3, seed=5))], lambda entry: None)
    assert result.status == adopt.REFUSED and "offloaded" in result.reason
    assert offloaded.vault.manifests.point_ids(CONV) == before
    ledger_of(offloaded).path.write_text("{ not json")
    [result] = adopt.adopt_points(offloaded.vault, [fallback_point(jsonl(3, seed=6))], lambda entry: None)
    assert result.status == adopt.REFUSED and offloaded.vault.manifests.point_ids(CONV) == before


def test_an_adopt_undo_never_takes_the_point_an_offload_depends_on(offloaded: World) -> None:
    verified = ledger_of(offloaded).get(CONV).point_id  # type: ignore[union-attr]
    path = offloaded.vault.manifests.unit_dir(CONV) / f"{verified}.json"
    undo = {"unit": CONV, "point_id": verified, "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "new_chunks": []}
    report = adopt.remove_adopted(offloaded.vault, [undo])
    assert report["kept"] == [f"{CONV}/{verified}"] and report["removed"] == [] and path.is_file()
    ledger_of(offloaded).remove(CONV)
    assert adopt.remove_adopted(offloaded.vault, [undo])["removed"] == [f"{CONV}/{verified}"] and not path.exists()


def test_a_restore_against_an_unreadable_ledger_fails_and_writes_nothing(offloaded: World) -> None:
    before = held(offloaded)
    ledger_of(offloaded).path.write_text("{ not json")
    out = restore_routes.run_restore("S1", None, False)
    assert [c.status for c in out.conversations] == ["failed"] and "ledger unreadable" in out.conversations[0].detail
    assert not offloaded.transcript(CONV).exists() and held(offloaded) == before


def test_an_unreadable_ledger_keeps_every_point_of_every_unit(offloaded: World, tmp_path: Path) -> None:
    verified = ledger_of(offloaded).get(CONV).point_id  # type: ignore[union-attr]
    elsewhere = tmp_path / "elsewhere.jsonl"
    elsewhere.write_bytes(jsonl(2, seed=7))
    file_newer_point(offloaded, jsonl(4, seed=96), elsewhere)
    good = ledger_of(offloaded).path.read_bytes()
    ledger_of(offloaded).path.write_text("{ not json")
    newest = offloaded.vault.manifests.newest(CONV)
    assert retention.protection(offloaded.vault, CONV, newest) == retention.PROTECT_OFFLOAD_UNKNOWN  # type: ignore[arg-type]
    assert retention.thin_unit(offloaded.vault, CONV) == [] and verified in offloaded.vault.manifests.point_ids(CONV)
    ledger_of(offloaded).path.write_bytes(good)
    ledger_of(offloaded).remove(CONV)
    assert verified in retention.thin_unit(offloaded.vault, CONV)
