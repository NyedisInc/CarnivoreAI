
from __future__ import annotations

from pathlib import Path

from src.plugins.save.vault import constants as K
from src.plugins.save.vault import gone_watch, retention
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl

NOW = 2_000_000_000.0


def _conv(i: int) -> str:
    return f"{i:08d}-aaaa-bbbb-cccc-1234567890ab"


def _hit(world: World, count: int = 12, lost: int = 10) -> dict:
    for i in range(count):
        world.write_conversation(jsonl(5, seed=i), conv=_conv(i), enc=f"-proj-{i}", subagents=0, tool_results=0)
        world.capture(conv=_conv(i))
    retention.assess(world.vault, now=NOW)
    for i in range(lost):
        world.transcript(_conv(i), f"-proj-{i}").unlink()
    report = retention.assess(world.vault, now=NOW + 60)["mass_gone"]
    assert report and report["count"] == lost
    return report


def test_a_hit_writes_the_freeze_and_a_quiet_vault_does_not(tmp_path):
    world = World(tmp_path / "hit")
    report = _hit(world)
    assert gone_watch.frozen(world.vault.root)["count"] == report["count"]
    assert (world.vault.root / K.FREEZE_FILE).is_file()
    quiet = World(tmp_path / "quiet")
    for i in range(12):
        quiet.write_conversation(jsonl(5, seed=i), conv=_conv(i), enc=f"-proj-{i}", subagents=0, tool_results=0)
        quiet.capture(conv=_conv(i))
    retention.assess(quiet.vault, now=NOW)
    for i in range(9):
        quiet.transcript(_conv(i), f"-proj-{i}").unlink()
    assert retention.assess(quiet.vault, now=NOW + 60)["mass_gone"] is None
    assert gone_watch.frozen(quiet.vault.root) is None


def test_a_frozen_vault_thins_nothing(tmp_path):
    world = World(tmp_path)
    world.side_history(8)
    _hit(world)
    world.side_history(6, size=4099)
    assert len(world.vault.manifests.point_ids("side-databases")) > K.MAX_POINTS_PER_UNIT
    before = world.vault.manifests.point_ids("side-databases")
    retention.assess(world.vault, now=NOW + 120)
    assert world.vault.manifests.point_ids("side-databases") == before
    assert gone_watch.clear_freeze(world.vault.root) is True
    retention.assess(world.vault, now=NOW + 180)
    assert len(world.vault.manifests.point_ids("side-databases")) == K.MAX_POINTS_PER_UNIT


def test_a_frozen_vault_does_not_supersede_a_conversations_prior_point_unless_it_only_extends(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    world.capture()
    (world.vault.root / K.FREEZE_FILE).write_text('{"count": 10, "samples": [], "at": 1, "step": 0}', encoding="utf-8")
    world.transcript().write_bytes(jsonl(25, seed=9))
    assert world.capture(reason="follow").status == "written"
    assert len(world.vault.manifests.point_ids(CONV)) == 2


def test_a_frozen_vault_collects_no_blobs(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    world.capture()
    world.vault.blobs.put(b"an orphaned chunk no manifest names" * 50)
    blobs_before = sorted(sha for sha, _path in world.vault.blobs.all_blobs())
    (world.vault.root / K.FREEZE_FILE).write_text('{"count": 10}', encoding="utf-8")
    result = retention.collect_garbage(world.vault, grace=0)
    assert result.get("skipped") == 1 and result["removed"] == 0
    assert sorted(sha for sha, _path in world.vault.blobs.all_blobs()) == blobs_before
    gone_watch.clear_freeze(world.vault.root)
    assert retention.collect_garbage(world.vault, grace=0)["removed"] > 0


def test_an_unreadable_freeze_still_freezes(tmp_path):
    (tmp_path / K.FREEZE_FILE).write_text("{not json", encoding="utf-8")
    assert gone_watch.frozen(tmp_path) == {"unreadable": True}


def test_clearing_does_not_rearm_for_the_same_event_but_a_grown_one_freezes_again(tmp_path):
    units = {f"u{i}": f"/p/{i}" for i in range(10)}
    assert gone_watch.observe(tmp_path, {}, NOW) is None
    assert gone_watch.observe(tmp_path, units, NOW + 60)["count"] == 10
    assert gone_watch.clear_freeze(tmp_path) is True and gone_watch.clear_freeze(tmp_path) is False
    assert gone_watch.observe(tmp_path, units, NOW + 120)["count"] == 10
    assert gone_watch.frozen(tmp_path) is None
    grown = {**units, **{f"v{i}": f"/q/{i}" for i in range(10)}}
    assert gone_watch.observe(tmp_path, grown, NOW + 180)["step"] == 1
    assert gone_watch.frozen(tmp_path)["count"] == 20


def test_an_unwritable_freeze_is_retried_on_the_next_pass(tmp_path, monkeypatch):
    units = {f"u{i}": f"/p/{i}" for i in range(10)}
    gone_watch.observe(tmp_path, {}, NOW)
    real = gone_watch.layout.atomic_write_json

    def failing(path: Path, data: object) -> None:
        if Path(path).name == K.FREEZE_FILE:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(gone_watch.layout, "atomic_write_json", failing)
    assert gone_watch.observe(tmp_path, units, NOW + 60) is not None and gone_watch.frozen(tmp_path) is None
    monkeypatch.setattr(gone_watch.layout, "atomic_write_json", real)
    gone_watch.observe(tmp_path, units, NOW + 120)
    assert gone_watch.frozen(tmp_path) is not None


def test_the_alert_carries_a_clear_freeze_action_to_a_real_route():
    from src.core.app_alerts import kinds
    from src.plugins.save import settings_routes
    from src.plugins.sdk.routing import cplug_router

    action = kinds.clear_freeze_action()
    assert any(a["id"] == "clear_freeze" for a in kinds.BY_TITLE["app_alert.backup_health.vault_frozen.title"].actions)
    router = cplug_router("save")
    settings_routes.add_to(router)
    assert any(f"/api/v1{r.path}" == f"/api/v1{action['route']}" and "POST" in r.methods for r in router.routes)
