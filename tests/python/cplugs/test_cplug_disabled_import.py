
from pathlib import Path

from src.core import ui_preferences
from src.cplugs.host import runtime, state as owner_state
from src.cplugs.host.legacy_disabled import import_disabled_plugins

MANIFESTS = {d.id: d.manifest for d in runtime.definitions()}


def _on(state_dir: Path, cplug_id: str) -> bool:
    return owner_state.get(state_dir, MANIFESTS[cplug_id]).enabled


def test_a_legacy_off_switch_becomes_an_off_plugin_and_the_rest_stay_on(tmp_path):
    assert _on(tmp_path, "unread") and _on(tmp_path, "share")
    assert import_disabled_plugins(tmp_path, ["mark-unread"], MANIFESTS) == ["unread"]
    assert not _on(tmp_path, "unread") and _on(tmp_path, "share")
    assert owner_state.get(tmp_path, MANIFESTS["unread"]).stored


def test_share_maps_too_and_a_retired_or_unknown_id_is_ignored(tmp_path):
    written = import_disabled_plugins(tmp_path, ["share-read-only", "open-as-component", "from-a-newer-build", 7], MANIFESTS)
    assert written == ["share"]
    assert not _on(tmp_path, "share") and _on(tmp_path, "unread")


def test_a_plugin_with_stored_state_is_never_overwritten_and_a_second_run_writes_nothing(tmp_path):
    from dataclasses import replace

    owner_state.update(tmp_path, MANIFESTS["unread"], None, lambda st: replace(st, enabled=True))
    assert import_disabled_plugins(tmp_path, ["mark-unread"], MANIFESTS) == []
    assert _on(tmp_path, "unread")
    assert import_disabled_plugins(tmp_path, ["share-read-only"], MANIFESTS) == ["share"]
    revision = owner_state.get(tmp_path, MANIFESTS["share"]).revision
    assert import_disabled_plugins(tmp_path, ["share-read-only"], MANIFESTS) == []
    assert owner_state.get(tmp_path, MANIFESTS["share"]).revision == revision


def test_the_retired_field_is_still_accepted_so_a_stored_value_never_422s():
    assert ui_preferences.validate_changes({"disabled_plugins": ["mark-unread", "Whatever Odd", "mark-unread"]}) == {
        "disabled_plugins": ["mark-unread", "Whatever Odd"]}
