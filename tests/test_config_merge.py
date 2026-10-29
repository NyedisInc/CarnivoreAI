
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.config_merge import (  # noqa: E402
    ADDED,
    CANNOT_DETERMINE,
    CONFLICT,
    KEPT_CUSTOM,
    REMOVED_UPSTREAM,
    UNCHANGED,
    UPDATED_DEFAULT,
    apply_import,
    merge_config,
)


def outcome_for(result, path: str) -> str:
    for decision in result.decisions:
        if decision.path == path:
            return decision.outcome
    raise AssertionError(f"no decision recorded for {path}: "
                         f"{[d.path for d in result.decisions]}")


def chosen_for(result, path: str):
    for decision in result.decisions:
        if decision.path == path:
            return decision.chosen
    raise AssertionError(f"no decision recorded for {path}")


class TestTheThreeCases:

    def test_untouched_field_receives_the_new_default(self) -> None:
        result = merge_config(
            mine={"jwt_expiry_minutes": 30},
            theirs={"jwt_expiry_minutes": 45},
            base={"jwt_expiry_minutes": 30},
        )
        assert outcome_for(result, "jwt_expiry_minutes") == UPDATED_DEFAULT
        assert result.merged["jwt_expiry_minutes"] == 45

    def test_customised_field_survives_when_the_default_is_unchanged(self) -> None:
        result = merge_config(
            mine={"agents": {"codex_command": "MINE"}},
            theirs={"agents": {"codex_command": "codex"}},
            base={"agents": {"codex_command": "codex"}},
        )
        assert outcome_for(result, "agents.codex_command") == KEPT_CUSTOM
        assert result.merged["agents"]["codex_command"] == "MINE"

    def test_both_changed_is_a_conflict_and_keeps_his_value(self) -> None:
        result = merge_config(
            mine={"agents": {"codex_command": "MINE"}},
            theirs={"agents": {"codex_command": "codex-v2"}},
            base={"agents": {"codex_command": "codex"}},
        )
        assert outcome_for(result, "agents.codex_command") == CONFLICT
        assert result.merged["agents"]["codex_command"] == "MINE", (
            "a conflict must never silently adopt the upstream value"
        )

    def test_a_conflict_is_reported_not_buried(self) -> None:
        result = merge_config(
            mine={"a": "MINE"}, theirs={"a": "THEIRS"}, base={"a": "OLD"}
        )
        attention = result.needing_attention()
        assert len(attention) == 1
        decision = attention[0]
        assert decision.mine == "MINE"
        assert decision.theirs == "THEIRS"
        assert decision.base == "OLD"
        assert decision.note, "a conflict must explain itself"

    def test_the_three_cases_produce_three_different_outcomes(self) -> None:
        result = merge_config(
            mine={"untouched": 1, "customised": "MINE", "both": "MINE"},
            theirs={"untouched": 2, "customised": "d", "both": "THEIRS"},
            base={"untouched": 1, "customised": "d", "both": "OLD"},
        )
        outcomes = {
            outcome_for(result, "untouched"),
            outcome_for(result, "customised"),
            outcome_for(result, "both"),
        }
        assert len(outcomes) == 3, f"cases collapsed together: {outcomes}"


class TestNoRecordedBase:

    def test_a_differing_field_is_cannot_determine_not_a_guess(self) -> None:
        result = merge_config(mine={"a": "MINE"}, theirs={"a": "THEIRS"}, base=None)
        assert outcome_for(result, "a") == CANNOT_DETERMINE
        assert result.had_base is False

    def test_cannot_determine_still_keeps_his_value(self) -> None:
        result = merge_config(mine={"a": "MINE"}, theirs={"a": "THEIRS"}, base=None)
        assert result.merged["a"] == "MINE"

    def test_cannot_determine_reaches_the_attention_list(self) -> None:
        result = merge_config(mine={"a": "MINE"}, theirs={"a": "THEIRS"}, base=None)
        assert [d.path for d in result.needing_attention()] == ["a"]

    def test_identical_fields_are_still_quiet_without_a_base(self) -> None:
        result = merge_config(mine={"a": 1, "b": 2}, theirs={"a": 1, "b": 2}, base=None)
        assert result.needing_attention() == []
        assert outcome_for(result, "a") == UNCHANGED


class TestAdditionsAndRemovals:

    def test_a_brand_new_setting_is_added(self) -> None:
        result = merge_config(mine={}, theirs={"new": "v"}, base={})
        assert outcome_for(result, "new") == ADDED
        assert result.merged["new"] == "v"

    def test_a_setting_dropped_upstream_is_kept_and_reported(self) -> None:
        result = merge_config(
            mine={"terminal_commands": [{"id": "top", "command": "htop"}]},
            theirs={},
            base={},
        )
        assert outcome_for(result, "terminal_commands") == REMOVED_UPSTREAM
        assert result.merged["terminal_commands"] == [{"id": "top", "command": "htop"}]
        assert result.needing_attention(), "an upstream removal must be reported"

    def test_nested_maps_are_merged_key_by_key(self) -> None:
        result = merge_config(
            mine={"agents": {"claude_command": "claude", "codex_command": "MINE"}},
            theirs={"agents": {"claude_command": "claude", "hermes_command": "hermes"}},
            base={"agents": {"claude_command": "claude", "codex_command": "codex"}},
        )
        agents = result.merged["agents"]
        assert agents["codex_command"] == "MINE", "his edit was dropped"
        assert agents["hermes_command"] == "hermes", "the new default never arrived"

    def test_comment_keys_always_follow_the_new_defaults(self) -> None:
        result = merge_config(
            mine={"_comment_x": "old prose"},
            theirs={"_comment_x": "new prose"},
            base={"_comment_x": "old prose"},
        )
        assert result.merged["_comment_x"] == "new prose"


class TestListsAreAtomic:

    def test_a_customised_list_is_not_rewritten(self) -> None:
        result = merge_config(
            mine={"cmds": ["/review", "/mine"]},
            theirs={"cmds": ["/review", "/plan"]},
            base={"cmds": ["/review"]},
        )
        assert result.merged["cmds"] == ["/review", "/mine"]

    def test_new_upstream_items_are_offered_but_not_applied(self) -> None:
        result = merge_config(
            mine={"cmds": ["/review", "/mine"]},
            theirs={"cmds": ["/review", "/plan", "/test"]},
            base={"cmds": ["/review"]},
        )
        assert result.importable["cmds"] == ["/plan", "/test"]
        assert "/plan" not in result.merged["cmds"], "applied without being asked"

    def test_an_explicit_import_appends_and_preserves_his_order(self) -> None:
        merged = apply_import({"cmds": ["/review", "/mine"]}, "cmds", ["/plan", "/test"])
        assert merged["cmds"] == ["/review", "/mine", "/plan", "/test"]

    def test_importing_twice_does_not_duplicate(self) -> None:
        once = apply_import({"cmds": ["/a"]}, "cmds", ["/b"])
        twice = apply_import(once, "cmds", ["/b"])
        assert twice["cmds"] == ["/a", "/b"]

    def test_importing_into_a_non_list_raises(self) -> None:
        with pytest.raises(KeyError):
            apply_import({"a": "scalar"}, "a", ["x"])


class TestTheRealConfigFiles:

    def test_the_shipped_example_merges_against_itself_cleanly(self) -> None:
        example = json.loads((REPO_ROOT / "config.example.json").read_text())
        result = merge_config(mine=example, theirs=example, base=example)
        assert result.needing_attention() == []
        assert result.changes() == []


class TestTheCommandLineTool:

    def _run(self, tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "config_upgrade.py"), *args,
             "--state-dir", str(tmp_path / "state")],
            capture_output=True,
            text=True,
        )

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"a": "MINE"}))
        defaults = tmp_path / "defaults.json"
        defaults.write_text(json.dumps({"a": "THEIRS"}))
        before = config.read_text()

        self._run(tmp_path, ["--config", str(config), "--defaults", str(defaults)])

        assert config.read_text() == before, "a dry run modified the config"

    def test_needing_attention_exits_2_not_0(self, tmp_path: Path) -> None:
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"a": "MINE"}))
        defaults = tmp_path / "defaults.json"
        defaults.write_text(json.dumps({"a": "THEIRS"}))

        proc = self._run(tmp_path, ["--config", str(config), "--defaults", str(defaults)])
        assert proc.returncode == 2, proc.stdout + proc.stderr

    def test_apply_backs_up_before_writing(self, tmp_path: Path) -> None:
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"a": 1}))
        defaults = tmp_path / "defaults.json"
        defaults.write_text(json.dumps({"a": 1, "b": 2}))

        proc = self._run(
            tmp_path, ["--config", str(config), "--defaults", str(defaults), "--apply"]
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

        backups = list((tmp_path / "state" / "config-backups").glob("config.*.json"))
        assert len(backups) == 1, "no backup was taken"
        assert json.loads(backups[0].read_text()) == {"a": 1}

        manifest = (tmp_path / "state" / "config-backups" / ".manifest").read_text()
        assert "BACKED_UP" in manifest

    def test_apply_records_a_base_so_the_next_upgrade_can_classify(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"a": 1}))
        defaults = tmp_path / "defaults.json"
        defaults.write_text(json.dumps({"a": 1}))

        self._run(
            tmp_path, ["--config", str(config), "--defaults", str(defaults), "--apply"]
        )
        base = tmp_path / "state" / "config-base.json"
        assert base.exists(), "no base recorded; every later upgrade stays ambiguous"
        assert json.loads(base.read_text()) == {"a": 1}

    def test_corrupt_config_refuses_to_merge(self, tmp_path: Path) -> None:
        config = tmp_path / "config.json"
        config.write_text("{ this is not json")
        defaults = tmp_path / "defaults.json"
        defaults.write_text(json.dumps({"a": 1}))

        proc = self._run(
            tmp_path, ["--config", str(config), "--defaults", str(defaults), "--apply"]
        )
        assert proc.returncode == 1
        assert config.read_text() == "{ this is not json", "corrupt file was overwritten"


def test_a_deleted_default_stays_deleted_and_a_changed_one_is_a_conflict():
    from src.core.config_merge import CONFLICT, KEPT_CUSTOM, merge_config

    same = merge_config({}, {"a": 1}, base={"a": 1})
    assert "a" not in same.merged
    assert [d.outcome for d in same.decisions] == [KEPT_CUSTOM]

    changed = merge_config({}, {"a": 2}, base={"a": 1})
    assert "a" not in changed.merged
    assert [d.outcome for d in changed.decisions] == [CONFLICT]

    nobase = merge_config({}, {"a": 1})
    assert nobase.merged == {"a": 1}
