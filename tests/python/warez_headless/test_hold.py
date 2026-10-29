
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, List

from scripts.crate.errors import ApiError
from scripts.warez import cli, hold
from scripts.warez.hold import HoldStore
from tests.python.warez_headless.test_update import NEW, OLD, CatalogHost, FakeUpdateHost, statuses

ITEM = "nyedis/calming"


def held_host(tmp_path: Path) -> "tuple[CatalogHost, HoldStore]":
    host = CatalogHost(pins=False)
    host.latest = OLD
    store = HoldStore(tmp_path, "m1")
    assert statuses(hold.hold(host, ITEM, "theme", store))["record"] == "pass"
    return host, store


def test_hold_leaves_the_item_installed_and_records_it(tmp_path: Path) -> None:
    host, store = held_host(tmp_path)
    rec = json.loads((tmp_path / "m1.json").read_text())[ITEM]
    assert host.row is not None and host.row["install_id"] == rec["install_id"] == "ins_calming"
    assert rec["version"] == OLD and rec["digest"] == "dig-" + OLD and rec["kind"] == "theme"
    assert rec["snapshot"] == {"ledger": [], "listing": ["claude"]} and not any(c.startswith("DELETE") for c in host.calls)
    assert [r.status for r in hold.hold(host, ITEM, "theme", store)] == ["skip"]


def test_hold_records_nothing_when_the_install_fails_or_the_item_is_already_there(tmp_path: Path) -> None:
    class Refusing(FakeUpdateHost):

        def request(self, method: str, path: str, body: Any = None) -> Any:
            if path.endswith("/catalog/install"):
                raise ApiError("no", status=409, code="name_taken")
            return super().request(method, path, body)

    store = HoldStore(tmp_path, "m1")
    results = hold.hold(Refusing(), ITEM, "theme", store)
    assert statuses(results)["install"] == "fail" and store.get(ITEM) is None
    there = CatalogHost()
    there.row = {"install_id": "x", "item_id": ITEM, "version": OLD, "digest": "d", "revision": 1}
    assert [r.status for r in hold.hold(there, ITEM, "theme", store)] == ["skip"] and store.get(ITEM) is None


def test_a_held_update_runs_badge_update_use_uninstall_restore_and_forgets_the_hold(tmp_path: Path) -> None:
    host, store = held_host(tmp_path)
    host.latest = NEW
    results = hold.run_held_update(host, ITEM, store.get(ITEM), store)
    assert [r.step for r in results] == list(hold.HELD_STEPS)
    assert {r.status for r in results} <= {"pass", "skip"} and statuses(results)["update"] == "pass"
    assert host.row is None and host.themes == ["claude"] and store.get(ITEM) is None


def test_a_held_update_with_no_newer_version_fails_the_badge_and_still_restores(tmp_path: Path) -> None:
    host, store = held_host(tmp_path)
    got = statuses(hold.run_held_update(host, ITEM, store.get(ITEM), store))
    assert got["badge"] == "fail" and "update" not in got and got["restore"] == "pass" and host.row is None


def test_a_held_install_changed_behind_our_back_fails_the_hold_step_and_keeps_the_record(tmp_path: Path) -> None:
    host, store = held_host(tmp_path)
    host.row["digest"] = "other"
    results = hold.run_held_update(host, ITEM, store.get(ITEM), store)
    assert statuses(results) == {"hold": "fail"} and host.row is not None and store.get(ITEM) is not None


def test_release_uninstalls_without_updating_and_restores(tmp_path: Path) -> None:
    host, store = held_host(tmp_path)
    host.latest = NEW
    got = statuses(hold.release(host, ITEM, store))
    assert got == {"uninstall": "pass", "purge": "skip", "restore": "pass"}
    assert host.row is None and store.get(ITEM) is None and not any(c.endswith("/update") for c in host.calls)


def test_release_of_something_not_held_fails_and_of_a_gone_install_just_restores(tmp_path: Path) -> None:
    host, store = held_host(tmp_path)
    assert statuses(hold.release(host, "no/such", store)) == {"uninstall": "fail"}
    host.row, _ = None, host.themes.remove("calming")
    assert statuses(hold.release(host, ITEM, store)) == {"uninstall": "skip", "restore": "pass"} and store.get(ITEM) is None


def run_cli(host: FakeUpdateHost, tmp_path: Path, *argv: str) -> "tuple[int, List[str]]":
    out = io.StringIO()
    code = cli.main(list(argv) + ["--host", "m1", "--state-dir", str(tmp_path), "--item", ITEM], factory=lambda _a: host, out=out, err=io.StringIO())
    return code, out.getvalue().splitlines()


def test_cli_hold_then_update_from_then_nothing_left(tmp_path: Path) -> None:
    host = CatalogHost(pins=False)
    host.latest = OLD
    code, rows = run_cli(host, tmp_path, "hold")
    assert code == 0 and host.row is not None and any(" record " in r for r in rows)
    host.latest = NEW
    code, rows = run_cli(host, tmp_path, "test", "--update-from", OLD)
    assert code == 0 and [r.split()[2] for r in rows if r.startswith(ITEM)] == list(hold.HELD_STEPS)
    assert host.row is None and not (json.loads((tmp_path / "m1.json").read_text()))


def test_cli_update_from_prefers_a_hold_and_otherwise_keeps_the_pinned_path(tmp_path: Path) -> None:
    _, rows = run_cli(CatalogHost(pins=False), tmp_path, "test", "--update-from", OLD)
    install = [r for r in rows if " install " in r][-1]
    assert "FAIL" in install and "cannot pin" in install


def test_cli_release_unwinds_a_hold(tmp_path: Path) -> None:
    host = CatalogHost(pins=False)
    run_cli(host, tmp_path, "hold")
    code, _ = run_cli(host, tmp_path, "release")
    assert code == 0 and host.row is None
