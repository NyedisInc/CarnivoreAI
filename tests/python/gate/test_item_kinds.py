
from __future__ import annotations

from pathlib import Path

import pytest

from src.api import catalog_mod_gates
from tests.helpers.clean_room_kits import KINDS, keys, run_kind, served  # noqa: F401
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_install_use_remove_leaves_nothing(kind: str, tmp_path: Path, served: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    facts = run_kind(kind, tmp_path, served, keys, monkeypatch)
    assert facts["install_status"] == 200, facts["install_text"]
    assert all(facts["landed"]) and facts["landed"], f"{kind}: the installed files are not on disk as real files: {facts['landed']} expected {facts['landed_at']} ledger says {facts['where']}"
    assert facts["listed"], f"{kind}: GET /catalog/installed does not list it"
    assert facts["remove_status"] == 200, facts["remove_text"]
    assert facts["displaced_exist"], f"{kind}: the removed copy was deleted instead of displaced to the trash"
    assert not any(facts["still_landed"]), f"{kind}: files remain where it was installed"
    assert facts["ledger_left"] == [], f"{kind}: ledger rows remain: {facts['ledger_left']}"
    assert facts["staging_left"] == [], f"{kind}: staging copies remain: {facts['staging_left']}"
    assert facts["residue"] == [], f"{kind}: residue after remove: {facts['residue'][:6]}"


def test_a_leftover_file_is_seen(tmp_path: Path, served: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    facts = run_kind("skill", tmp_path, served, keys, monkeypatch, plant=True)
    assert facts["residue"], "the planted leftover was not reported"
    assert any(facts["still_landed"])


def test_a_settings_file_that_still_names_a_removed_mod_is_seen(tmp_path: Path, served: Path, keys, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_mod_gates, "unregister_before_uninstall", lambda targets: None)
    facts = run_kind("mod", tmp_path, served, keys, monkeypatch)
    assert "a settings file still names the removed item" in facts["residue"], facts["residue"]


def test_every_kind_the_installer_knows_has_a_case_here() -> None:
    from src.core.skills import kinds  # noqa: PLC0415

    assert set(kinds.KINDS) - {"cplug"} == set(KINDS), set(kinds.KINDS) ^ set(KINDS)


@pytest.mark.xfail(strict=True, reason="#1944: the declarative widget kind has no catalog install path yet (docs/extension-contract.md section 9; Phase 6)")
def test_a_widget_installs_and_removes_cleanly() -> None:
    from src.core.skills import kinds  # noqa: PLC0415

    assert "widget" in kinds.KINDS


@pytest.mark.xfail(strict=True, reason="#1239: the Carnivore plugin (cplug) catalog kind has no install path yet (S11); third-party plugins arrive after 1.0")
def test_a_third_party_carnivore_plugin_installs_and_removes_cleanly() -> None:
    assert "cplug" in KINDS
