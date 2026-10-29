
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.core.approvals import beast_grid_migration as migration
from src.core.approvals.beast_grid import cell_defaults
from src.cplugs.host import state as owner_state


def _state(state_dir: Path, entries: Dict[str, Any]) -> None:
    path = owner_state.state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": owner_state.STATE_VERSION, "cplugs": entries}))


def _config(tmp_path: Path, doc: Dict[str, Any]) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(doc))
    return path


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def test_owners_stored_grid_and_scope_move_as_stored_and_only_once(tmp_path: Path) -> None:
    _state(tmp_path, {"beastmode": {"enabled": True, "grants": ["agent_writes"], "revision": 5, "settings": {
        "agentWritesOff": True, "folderTrustOn": False, "trustScope": "every", "junk": 1, "claudePermissionOn": "yes"}}})
    config = _config(tmp_path, {"mcp": {"beast_mode": True, "enabled": True}, "unrelated": 1})
    assert migration.migrate(tmp_path, config) is True
    written = _read(config)
    assert written["mcp"]["beast_grid"] == {"agentWritesOff": True, "folderTrustOn": False}, "known bool boxes only"
    assert written["mcp"]["beast_trust_scope"] == "every"
    assert written["mcp"]["beast_mode"] is True and written["unrelated"] == 1, "nothing else is touched"
    assert owner_state.stored_entry(tmp_path, "beastmode")["revision"] == 5, "the old entry is never deleted"
    written["mcp"]["beast_grid"]["agentWritesOff"] = False
    config.write_text(json.dumps(written))
    assert migration.migrate(tmp_path, config) is False
    assert _read(config)["mcp"]["beast_grid"]["agentWritesOff"] is False


def test_a_plugin_stored_off_carries_over_as_every_box_unticked(tmp_path: Path) -> None:
    _state(tmp_path, {"beastmode": {"enabled": False, "grants": [], "revision": 2, "settings": {"folderTrustOn": True, "trustScope": "projects"}}})
    config = _config(tmp_path, {"mcp": {}})
    assert migration.migrate(tmp_path, config)
    assert _read(config)["mcp"]["beast_grid"] == {key: False for key in cell_defaults()}


def test_a_fresh_install_is_marked_with_an_empty_grid_so_it_runs_once(tmp_path: Path) -> None:
    config = _config(tmp_path, {"other": 1})
    assert migration.migrate(tmp_path, config) is True
    assert _read(config)["mcp"] == {"beast_grid": {}} and "beast_trust_scope" not in _read(config)["mcp"]
    assert migration.migrate(tmp_path, config) is False


def test_an_unknown_scope_is_dropped_so_it_reads_the_narrow_default(tmp_path: Path) -> None:
    _state(tmp_path, {"beastmode": {"enabled": True, "settings": {"trustScope": "everything"}}})
    config = _config(tmp_path, {})
    migration.migrate(tmp_path, config)
    assert "beast_trust_scope" not in _read(config)["mcp"]


def test_a_missing_or_broken_config_is_logged_and_retried_next_boot(tmp_path: Path) -> None:
    assert migration.migrate(tmp_path, tmp_path / "nope.json") is False
    broken = tmp_path / "config.json"
    broken.write_text("{not json")
    assert migration.migrate(tmp_path, broken) is False


def test_the_retired_auto_answer_entry_maps_through_the_rename_rule(tmp_path: Path) -> None:
    _state(tmp_path, {"autoanswer": {"enabled": True, "settings": {"folderTrust": False, "devChannels": True, "trustScope": "every", "chromeDecline": "no"}}})
    config = _config(tmp_path, {})
    migration.migrate(tmp_path, config)
    mcp = _read(config)["mcp"]
    assert mcp["beast_grid"] == {"devChannelsOff": True, "devChannelsOn": True, "folderTrustOff": False, "folderTrustOn": False}
    assert mcp["beast_trust_scope"] == "every"


def test_the_retired_auto_answer_plugin_stored_off_unticks_the_startup_rows_only(tmp_path: Path) -> None:
    _state(tmp_path, {"autoanswer": {"enabled": False, "settings": {"folderTrust": True}}})
    config = _config(tmp_path, {})
    migration.migrate(tmp_path, config)
    grid = _read(config)["mcp"]["beast_grid"]
    assert set(grid) == {f"{stem}{col}" for stem in migration.AUTOANSWER_SWITCHES for col in ("Off", "On")} and not any(grid.values())


def test_the_beastmode_entry_wins_over_a_stale_auto_answer_entry(tmp_path: Path) -> None:
    _state(tmp_path, {"autoanswer": {"enabled": True, "settings": {"folderTrust": False}},
                      "beastmode": {"enabled": True, "settings": {"codexApprovalOff": True}}})
    config = _config(tmp_path, {})
    migration.migrate(tmp_path, config)
    assert _read(config)["mcp"]["beast_grid"] == {"codexApprovalOff": True}
