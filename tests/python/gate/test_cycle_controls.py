
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

import pytest

from src.cplugs.host import dependencies, developer_mode, mcp as cplug_mcp, purge_guard, purge_kept, routes as host_routes, runtime, state as owner_state
from tests.python.cplugs import removability
from tests.python.gate import cycle
from tests.python.gate.test_plugin_cycle import build_version


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies, "app_version", build_version)
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    monkeypatch.setattr(runtime, "_host", None)


def _no_purge(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(purge_guard, "purge", lambda folder, plugin_id, root, key=None: None)


def _purge_eats_kept(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(host_routes, "_owned_files", lambda cplug_id: ("time-machine",))


def _forget_nothing(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(owner_state, "forget", lambda state_dir, cplug_id: False)


def _always_on(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(runtime.Host, "enabled", lambda self, cplug_id: True)


def _never_on(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(runtime.Host, "enabled", lambda self, cplug_id: False)


def _price_hides_kept(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(purge_kept, "kept_stores", lambda state_dir, decls, settings: [])


def _enable_refused(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(dependencies, "enable_blockers", lambda manifest: {"core": ["nothing"]})


def _second_enable_refused(mp: pytest.MonkeyPatch) -> None:
    real = dependencies.enable_blockers
    calls = {"n": 0}

    def blockers(manifest):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return real(manifest) if calls["n"] == 1 else {"core": ["nothing"]}

    mp.setattr(dependencies, "enable_blockers", blockers)


def _tools_never_available(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(cplug_mcp, "available", lambda name, live=None, enabled_memo=None: False)


def _disable_refused(mp: pytest.MonkeyPatch) -> None:
    real = host_routes._check

    def check(d, body):  # type: ignore[no-untyped-def]
        if body.enabled is False:
            raise host_routes._error(422, "core_cannot_disable", "forced by the control")
        return real(d, body)

    mp.setattr(host_routes, "_check", check)


def _no_slices(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(cycle, "slice_paths", lambda: {})


def _purge_explodes(mp: pytest.MonkeyPatch) -> None:
    def boom(folder, plugin_id, root):  # type: ignore[no-untyped-def]
        raise OSError("forced by the control")

    mp.setattr(purge_guard, "purge", boom)


def _shared_catalog_holds_keys(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(removability, "assert_no_dangling_assets", lambda pid: (_ for _ in ()).throw(AssertionError("the shared catalog still holds the plugin's keys")))
    mp.setattr(cycle, "assert_no_dangling_assets", removability.assert_no_dangling_assets)


CASES: Dict[str, tuple] = {
    "enable_refused": ("flow", _enable_refused, "enable", ()),
    "host_says_off_while_on": ("reviewboard", _never_on, "use", ("enable",)),
    "tools_not_listed": ("reviewboard", _tools_never_available, "tools_listed_on", ("enable", "use")),
    "disable_refused": ("unread", _disable_refused, "disable", ("enable", "use")),
    "route_still_served_off": ("save", _always_on, "routes_refused_off", ("enable", "use", "disable")),
    "tools_still_listed_off": ("reviewboard", _always_on, "tools_unlisted_off", ("enable", "use", "disable")),
    "price_hides_kept": ("save", _price_hides_kept, "purge_priced", ("enable", "disable")),
    "purge_explodes": ("share", _purge_explodes, "purge_runs", ("enable", "disable", "purge_priced")),
    "purge_deletes_nothing": ("flow", _no_purge, "files_gone", ("purge_priced", "purge_runs")),
    "purge_eats_kept_store": ("save", _purge_eats_kept, "kept_stores_stay", ("purge_runs", "files_gone")),
    "state_entry_stays": ("unread", _forget_nothing, "state_entry_gone", ("purge_runs", "files_gone")),
    "not_back_to_default": ("unread", _forget_nothing, "back_to_default", ("purge_runs",)),
    "strings_outside_slice": ("flow", _no_slices, "strings_styles_own", ("purge_runs",)),
    "shared_catalog_keys": ("share", _shared_catalog_holds_keys, "strings_styles_own", ("purge_runs",)),
    "re_enable_refused": ("crate", _second_enable_refused, "re_enable", ("purge_runs", "state_entry_gone")),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_broken_behavior_turns_its_check_red(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_id, breaker, red, green = CASES[name]
    breaker(monkeypatch)
    outcome = cycle.run_cycle(plugin_id, tmp_path)
    status, detail = outcome.checks[red]
    assert status == cycle.FAIL, f"{name}: {plugin_id}/{red} stayed {status} ({detail}) with the behavior broken"
    for check in green:
        assert outcome.checks[check][0] == cycle.PASS, f"{name}: {plugin_id}/{check} should still pass but is {outcome.checks[check]}"


def test_the_unbroken_cycle_is_green_for_the_control_plugins(tmp_path: Path) -> None:
    for plugin_id in sorted({c[0] for c in CASES.values()}):
        outcome = cycle.run_cycle(plugin_id, tmp_path / plugin_id)
        bad = {k: v for k, v in outcome.checks.items() if v[0] == cycle.FAIL and k != "strings_styles_own"}
        assert bad == {}, f"{plugin_id}: {bad}"
