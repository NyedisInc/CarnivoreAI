
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cplugs.crate import constants as K
from src.cplugs.crate.entries_out import ScopeKeys, read_entries, slice_matching
from src.cplugs.crate.plan import build_plan
from src.cplugs.sdk import crate_sources as cs
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request, session_request
from tests.python.inventory.world import EPOCH_A, TMUX_A, UUID_A


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    return make_world(tmp_path)


def _records(world: SimpleNamespace, request) -> list:
    plan = build_plan(env_for(world), request)
    records, blockers = read_entries(plan.entries, plan.keys, world.locations)
    assert blockers == []
    return records


def _by(records: list, store: str) -> list:
    return [r for r in records if r["store"] == store]


def test_session_entries_each_handler(world: SimpleNamespace) -> None:
    records = _records(world, session_request())
    unread = {r["key"]: r["value"] for r in _by(records, cs.UNREAD_STORE)}
    assert unread == {f"row:{world.row_a}": {"auto": True, "manual": False},
                      f"{TMUX_A}@{EPOCH_A}": {"auto": True, "manual": False}}
    [pin] = _by(records, cs.CONFIG_STORE)
    assert pin["value"] == "work" and pin["file_index"] == 0 and pin["file_label"] == "config.json"
    [theme_pin] = _by(records, cs.PINNED_THEMES_FILE)
    assert theme_pin["value"] == "dracula"
    [journal] = _by(records, cs.JOURNAL)
    assert list(journal["value"]["sessions"].values()) == [{"session_uuid": UUID_A}]
    prefs = {r["key"]: r for r in _by(records, cs.PREFERENCES)}
    arrangement = prefs["ui_preferences.values.drawer_arrangement"]["slice"]
    assert {tuple(s["path"]) for s in arrangement} == {("pinned", 0), ("order", 0), ("bands", "g:x", 0)}
    grid = prefs[f"ui_preferences.values.terminal_layouts.sessions.{TMUX_A}:{EPOCH_A}"]
    assert grid["value"] == {"layout": {"v": 1, "rows": [1]}}
    [theme] = _by(records, cs.STORE_THEME_DOTFILE)
    assert theme["value"]["text"] == "acid_trip\n"
    assert not _by(records, cs.RENAME_STORE)


def test_project_entries_folds_and_trust(world: SimpleNamespace) -> None:
    records = _records(world, project_request(world))
    folds = {(r["key"], json.dumps(r["match"])): r["slice"] for r in _by(records, cs.PREFERENCES) if "match" in r}
    assert folds[("ui_preferences.values.drawer_arrangement.collapsed", f'"p:{world.p1}"')] == [{"path": [0], "value": f"p:{world.p1}"}]
    [trust] = _by(records, cs.CLAUDE_JSON_STORE)
    assert trust["value"] == {"trusted": True} and trust["file_label"] == ".claude.json"


def test_claude_json_yields_only_the_trust_boolean(world: SimpleNamespace) -> None:
    canary = "mcp-canary-" + secrets.token_hex(8)
    path = Path(world.home) / ".claude.json"
    data = json.loads(path.read_text())
    data["projects"][world.root1].update({"mcpServers": {"x": {"env": {"TOKEN": canary}}}, "allowedTools": ["Bash"]})
    path.write_text(json.dumps(data))
    records = _records(world, project_request(world))
    [trust] = _by(records, cs.CLAUDE_JSON_STORE)
    assert trust["value"] == {"trusted": True}
    assert canary not in json.dumps(records) and "allowedTools" not in json.dumps(records)


def test_an_unknown_store_and_an_unreadable_file_are_blockers(world: SimpleNamespace, tmp_path: Path) -> None:
    keys = ScopeKeys({UUID_A}, {world.row_a})
    odd = cs.Artifact(store="mystery.json", kind=cs.KIND_ENTRY, what="k", count=1, locator={"file": "/x", "key": "k"})
    broken = tmp_path / "unread_state.json"
    broken.write_text("{not json")
    bad = cs.Artifact(store=cs.UNREAD_STORE, kind=cs.KIND_ENTRY, what="row:1", count=1,
                      locator={"file": str(broken), "key": "row:1"})
    records, blockers = read_entries([odd, bad], keys, world.locations)
    assert records == [] and len(blockers) == 2
    assert "no crate policy for entry store mystery.json" in blockers[0] and "could not be read" in blockers[1]


def test_a_large_theme_file_is_refused(world: SimpleNamespace) -> None:
    (Path(world.root1) / ".cc.theme").write_text("x" * 5000)
    plan = build_plan(env_for(world), session_request())
    assert [b["code"] for b in plan.blockers] == ["entry_unreadable"]


def test_slice_matching_walks_lists_and_keys() -> None:
    value = {"pinned": ["u1", "u2"], "bands": {"g": ["u1"]}, "u1": {"x": 1}, "other": [{"deep": ["u1"]}]}
    got = slice_matching(value, {"u1"})
    assert {tuple(s["path"]) for s in got} == {("pinned", 0), ("bands", "g", 0), ("u1",), ("other", 0, "deep", 0)}
    assert slice_matching(None, {"u1"}) == [] and slice_matching(["a"], set()) == []


@pytest.mark.parametrize("how", ["symlink", "hardlink"])
def test_a_cc_theme_linked_to_a_credential_file_is_never_read(world: SimpleNamespace, how: str) -> None:
    canary = "sk-ant-oat01-" + secrets.token_hex(16)
    cred = Path(world.locations.claude_homes()[0]) / ".credentials.json"
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": canary}}))
    theme = Path(world.root1) / ".cc.theme"
    theme.unlink()
    if how == "symlink":
        theme.symlink_to(cred)
    else:
        os.link(cred, theme)
    plan = build_plan(env_for(world), project_request(world))
    records, blockers = read_entries(plan.entries, plan.keys, world.locations)
    assert canary not in json.dumps(records)
    assert any(".cc.theme is not read" in b for b in blockers), blockers
    assert any(b["code"] == K.B_ENTRY and ".cc.theme" in b["detail"] for b in plan.blockers)
