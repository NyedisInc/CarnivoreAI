
import json
from pathlib import Path

from src.core.mods import inventory, owner_state, registry
from tests.mods.test_mod_registry import KEY, _world


def _mods(home, files):
    return inventory.build_inventory(home, files, [])["mods"]


def test_wanted_on_and_dropped_is_restored_wanted_off_is_untouched(tmp_path):
    home, primary, files = _world(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    mod = str(home / ".claude" / "mods" / "alpha")
    registry.register(mod, home=home, account_files=files)
    owner_state.record(mod, True, state_dir=state)
    doc = json.loads(primary.read_text())
    doc["env"].pop(KEY)
    primary.write_text(json.dumps(doc))
    files[2].write_text("{}")
    assert _mods(home, files)[0]["state"] == "off"
    restored = owner_state.restore_dropped(_mods(home, files), home=home, account_files=files, state_dir=state)
    assert restored == [mod]
    assert mod in json.loads(primary.read_text())["env"][KEY]
    assert owner_state.load(state)["restored"]
    registry.unregister(mod, home=home, account_files=files)
    owner_state.record(mod, False, state_dir=state)
    assert owner_state.restore_dropped(_mods(home, files), home=home, account_files=files, state_dir=state) == []
    assert mod not in json.loads(primary.read_text()).get("env", {}).get(KEY, "")
    assert owner_state.load(state)["restored"] == {}


def test_offered_is_remembered(tmp_path):
    owner_state.mark_offered("nyedis/x", state_dir=tmp_path)
    assert owner_state.was_offered("nyedis/x", state_dir=tmp_path) and not owner_state.was_offered("nyedis/y", state_dir=tmp_path)
