
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.core.plugin_health.gather import build_report
from src.core.plugin_health import model
from src.core.plugin_health.claude_plugins import measured_digest
from src.core.skills import kinds
from src.core.skills.ledger_types import HARNESS_CLAUDE, InstallTarget
from src.cplugs.host import identity, sidecar_registry, sideload
from src.cplugs.host import state as owner_state
from tests.python.plugin_health.world import FAR_FUTURE, make_world, write_code

EXPIRED = "2020-01-01T00:00:00Z"


@pytest.fixture
def world(tmp_path):
    w = make_world(tmp_path)
    try:
        yield w
    finally:
        sidecar_registry.install(None)


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def by_id(report) -> dict:
    return {r.id: r for r in report.rows}


def build_shaped_like_joes(w, tmp_path: Path) -> Path:
    w.install_catalog("acme/okclock", enabled=True)
    w.install_catalog("acme/offone", enabled=False)
    w.install_catalog("acme/newone")
    w.install_catalog("acme/revoked", enabled=True)
    w.install_catalog("acme/staleidx", enabled=True)
    w.install_catalog("acme/untrusted", trust=True, enabled=True)
    source = write_code(tmp_path / "dev" / "gonedev", "gonedev")
    w.install_catalog("local/gonedev", enabled=True, local_source=source)
    w.settle()
    w.rt.supervisor.override_index("okclock", True)
    w.set_index({"expires_at": EXPIRED, "revoked": [{"id": "acme/revoked"}]})
    return source


def add_claude_plugins(w, tmp_path: Path) -> None:
    for name in ("clean", "edited"):
        folder = tmp_path / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("hello\n")
        digest = measured_digest(folder)
        w.add_ledger(w.item(f"rea/{name}", kind=kinds.KIND_PLUGIN, digest=digest, consented=digest), (InstallTarget(f"inst-rea-{name}", HARNESS_CLAUDE, str(folder)),))
    (tmp_path / "skills" / "edited" / "SKILL.md").write_text("changed after consent\n")


def add_leftovers(w) -> None:
    path = owner_state.state_path(w.state)
    data = json.loads(path.read_text())
    for i in range(16 - len(data["cplugs"])):
        data["cplugs"][f"ghost{i}"] = {"enabled": False, "grants": [], "settings": {}, "revision": 1, "digest": ""}
    path.write_text(json.dumps(data))
    (w.state / "cplugs" / ("ab" * 16)).mkdir(parents=True)
    (w.state / "cplugs" / ("ab" * 16) / "note.txt").write_text("x" * 100)
    (w.state / "cplugs" / "oldplugin").mkdir()
    identity.register_install(w.state, "removedone", "acme/removedone", frozenset())


def test_every_row_has_its_word_and_reason_and_a_read_changes_nothing(world, tmp_path):
    w = world
    build_shaped_like_joes(w, tmp_path)
    add_claude_plugins(w, tmp_path)
    add_leftovers(w)
    before = snapshot(tmp_path)

    report = build_report(w.host, w.rt)

    rows = by_id(report)
    expect = {
        "acme/okclock": (model.WORD_ON, None, model.BUTTON_TURN_OFF),
        "acme/offone": (model.WORD_OFF, None, model.BUTTON_TURN_ON),
        "acme/newone": (model.WORD_NEEDS_APPROVAL, model.REASON_NEW_INSTALL, model.BUTTON_REVIEW),
        "acme/revoked": (model.WORD_HELD, model.REASON_REVOKED, model.BUTTON_OPEN_CATALOG),
        "acme/staleidx": (model.WORD_HELD, model.REASON_INDEX_EXPIRED, model.BUTTON_OPEN_CATALOG),
        "acme/untrusted": (model.WORD_HELD, model.REASON_TRUST_REFUSED, None),
        "rea/clean": (model.WORD_ON, None, model.BUTTON_TURN_OFF),
        "rea/edited": (model.WORD_NEEDS_APPROVAL, model.REASON_CHANGED_ON_DISK, model.BUTTON_REVIEW),
    }
    for item_id, (word, reason, button) in expect.items():
        got = rows[item_id]
        assert (got.word, got.reason, got.button) == (word, reason, button), item_id
    assert rows["local/gonedev"].word == model.WORD_ON
    assert rows["acme/okclock"].source == model.SOURCE_CATALOG and rows["local/gonedev"].source == model.SOURCE_FOLDER
    assert rows["rea/clean"].kind == model.KIND_CLAUDE_CODE_PLUGIN
    assert any(r.kind == model.KIND_FEATURE and r.source == model.SOURCE_BUILT_IN for r in report.rows)

    assert [o.key for o in report.orphan_data] == ["ab" * 16, "oldplugin"] and report.orphan_data[0].bytes == 100
    assert report.orphan_data[0].button == model.BUTTON_DELETE_DATA
    assert [r.name for r in report.removed] == ["removedone"]
    assert sorted(report.stale_state) == [f"ghost{i}" for i in range(len(report.stale_state))] and len(report.stale_state) >= 7
    assert report.counts()[model.WORD_HELD] == 3 and report.problems == []
    assert snapshot(tmp_path) == before


def test_a_deleted_sideload_source_is_held_missing_and_an_unreadable_one_is_held_unreadable(world, tmp_path):
    w = world
    source = build_shaped_like_joes(w, tmp_path)
    import shutil

    shutil.move(str(source), str(tmp_path / "Trash-gonedev"))
    row = by_id(build_report(w.host, w.rt))["local/gonedev"]
    assert (row.word, row.reason) == (model.WORD_HELD, model.REASON_FOLDER_MISSING)

    kept = tmp_path / "Trash-gonedev"
    shutil.move(str(kept), str(source))
    os.chmod(source, 0o000)
    try:
        row = by_id(build_report(w.host, w.rt))["local/gonedev"]
        assert (row.word, row.reason) == (model.WORD_HELD, model.REASON_FOLDER_UNREADABLE)
    finally:
        os.chmod(source, 0o755)


def test_switches_that_hold_everything_give_a_reason_each(world, tmp_path):
    w = world
    build_shaped_like_joes(w, tmp_path)
    w.rt.supervisor.set_safe_mode(True)
    rows = by_id(build_report(w.host, w.rt))
    assert (rows["acme/okclock"].word, rows["acme/okclock"].reason, rows["acme/okclock"].button) == (
        model.WORD_HELD, model.REASON_THIRD_PARTY_OFF, model.BUTTON_TURN_ON_THIRD_PARTY)
    sideload.set_switch(w.state, False)
    rows = by_id(build_report(w.host, w.rt))
    assert (rows["local/gonedev"].word, rows["local/gonedev"].reason) == (model.WORD_HELD, model.REASON_SIDELOAD_OFF)


def test_a_report_without_a_runtime_says_so_instead_of_guessing(world, tmp_path):
    w = world
    build_shaped_like_joes(w, tmp_path)
    report = build_report(w.host, None)
    assert "runtime_unavailable" in report.problems
    assert by_id(report)["acme/okclock"].reason == model.REASON_RUNTIME_DOWN


def test_boot_logs_one_line_of_counts_with_no_paths_and_changes_nothing(tmp_path):
    import asyncio

    from structlog.testing import capture_logs

    from src.cplugs.host import owner_switch

    w = make_world(tmp_path, real_host=True)
    try:
        build_shaped_like_joes(w, tmp_path)
        owner_switch.write(w.state, True)

        async def no_fetch(*args, **kwargs):
            pass

        w.rt.index.sync = w.rt.index.ensure = no_fetch
        before = snapshot(tmp_path)
        with capture_logs() as logs:
            asyncio.run(w.rt.start())
        lines = [e for e in logs if e["event"] == "plugin_health_boot"]
        assert len(lines) == 1
        line = lines[0]
        assert line["held"] == 3 and line["needs_approval"] == 1 and line["problems"] == []
        assert str(tmp_path) not in json.dumps(line, default=str)
        assert snapshot(tmp_path) == before
    finally:
        sidecar_registry.install(None)
