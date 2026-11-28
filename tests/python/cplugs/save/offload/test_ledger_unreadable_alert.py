
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from src.core.backup_health import vault_check, vault_record
from src.core.deepsearch.fallback_hook import AdoptedPoint
from src.plugins.save.offload import ledger as ledger_mod
from src.plugins.save.offload import offload_routes, upkeep
from src.plugins.save.vault import adopt, retention
from src.plugins.save.vault.old_sources import apply as import_apply
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, ledger_of
from tests.python.cplugs.save.vault_helpers import World

CONV = conv_id(1)
NOW = 2_000_000_000.0
LEDGER_ALERT = "backup_health.vault_ledger_unreadable"
REPO = Path(__file__).resolve().parents[5]


@pytest.fixture
def offloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = build_fleet(tmp_path, monkeypatch, 1)
    assert {c.status for c in offload_routes._run("S1", False).conversations} == {"offloaded"}
    vault_record.update(world.state, active=True, last_ok_at=NOW, swept_at=NOW, uncovered=0, on_disk=0)
    return world


def break_ledger(world: World, text: str = "{ not json") -> None:
    path = ledger_of(world).path
    stamp = path.stat().st_mtime_ns + 5_000_000_000 if path.exists() else None
    path.write_text(text)
    if stamp is not None:
        os.utime(path, ns=(stamp, stamp))


def firing(world: World) -> dict:
    return {v.key: v for v in vault_check.check_vault(world.state, NOW) if v.state == "firing"}


def test_an_unreadable_ledger_raises_one_sticky_alert_that_clears_when_it_reads_again(offloaded: World) -> None:
    good = ledger_of(offloaded).path.read_bytes()
    break_ledger(offloaded)
    upkeep.run(offloaded.vault, offloaded.state, NOW)
    upkeep.run(offloaded.vault, offloaded.state, NOW + 60)
    ledger_alerts = {k: v for k, v in firing(offloaded).items() if k.startswith(LEDGER_ALERT)}
    assert list(ledger_alerts) == [LEDGER_ALERT]
    verdict = ledger_alerts[LEDGER_ALERT]
    assert verdict.sticky and verdict.severity == "error" and "vault-offload.json" in verdict.params["targets"]
    ledger_of(offloaded).path.write_bytes(good)
    upkeep.run(offloaded.vault, offloaded.state, NOW + 120)
    assert not [k for k in firing(offloaded) if k.startswith(LEDGER_ALERT)]


def test_the_keepers_log_an_unreadable_ledger_once_per_change(offloaded: World) -> None:
    break_ledger(offloaded)
    prior = offloaded.vault.manifests.newest(CONV)
    with capture_logs() as logs:
        for _ in range(3):
            assert retention.may_replace(offloaded.vault, CONV, prior) is False  # type: ignore[arg-type]
        break_ledger(offloaded, "{ still not json")
        assert retention.may_replace(offloaded.vault, CONV, prior) is False  # type: ignore[arg-type]
    assert [e["event"] for e in logs].count("offload_ledger_unreadable_for_keepers") == 2


def test_the_keepers_parse_the_ledger_once_until_it_is_written(offloaded: World, monkeypatch: pytest.MonkeyPatch) -> None:
    parsed: list = []
    real = ledger_mod.read_file
    monkeypatch.setattr(ledger_mod, "read_file", lambda path, state_dir=None: parsed.append(path) or real(path, state_dir))
    root = offloaded.vault.root
    first = ledger_mod.offloaded_units(root)
    count = len(parsed)
    for _ in range(5):
        assert ledger_mod.offloaded_units(root) == first and first.holds(CONV)
    assert len(parsed) == count
    ledger_of(offloaded).remove(CONV)
    assert not ledger_mod.offloaded_units(root).holds(CONV)


def test_the_import_receipt_headline_counts_the_refused_points() -> None:
    filed = AdoptedPoint("c1", "p1", adopt.ADOPTED, "p1")
    refused = AdoptedPoint("c2", "p2", adopt.REFUSED, reason="this conversation is offloaded; restore it before importing another copy")
    blind = AdoptedPoint("c3", "p3", adopt.REFUSED, reason=adopt.REASON_LEDGER_UNREADABLE)
    clean = import_apply.receipt_of("r1", [filed], {}, None)["headline"]
    mixed = import_apply.receipt_of("r2", [filed, refused], {}, None)["headline"]
    ledger = import_apply.receipt_of("r3", [filed, refused, blind], {}, None)["headline"]
    assert clean == {"key": "cplug.save.import.receipt.headline", "params": {"filed": 1, "refused": 0, "ledger_unreadable": 0}}
    assert mixed == {"key": "cplug.save.import.receipt.headline_refused", "params": {"filed": 1, "refused": 1, "ledger_unreadable": 0}}
    assert ledger == {"key": "cplug.save.import.receipt.headline_ledger_unreadable", "params": {"filed": 1, "refused": 2, "ledger_unreadable": 1}}
    catalog = (REPO / "web" / "src" / "plugins" / "save" / "catalog.en.js").read_text(encoding="utf-8")
    keys = set(re.findall(r"^\s*'([^']+)':", catalog, re.M))
    assert {clean["key"], mixed["key"], ledger["key"]} <= keys
