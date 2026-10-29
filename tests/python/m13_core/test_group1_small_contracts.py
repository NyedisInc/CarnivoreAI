from pathlib import Path

from src.core import slash_command_discovery as scd
from src.core.trail_reader import TrailReadResult, prior_interrupt_uuid
from src.core.trail_entry import TrailEntry


def test_plugin_scan_uses_the_passed_claude_home(tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setattr(scd, "CLAUDE_HOME", other)
    home = tmp_path / "given"
    cmds = home / "plugins" / "cache" / "mkt" / "demo" / "1.0.0" / "commands"
    cmds.mkdir(parents=True)
    (cmds / "hello.md").write_text("# Hello\n")
    groups = scd.build_command_groups(claude_home=home)
    assert "plugin:demo" in [g.id for g in groups]


def _entry(uuid: str, kind: str, frm: str, to: str, status: str = "started") -> TrailEntry:
    return TrailEntry(entry_uuid=uuid, kind=kind, status=status, started_at="t",
                      from_version=frm, to_version=to)


def test_prior_interrupt_requires_same_kind_and_from_version() -> None:
    old = _entry("a", "config", "1", "2")
    new = _entry("b", "schema", "1", "2")
    read = TrailReadResult(status="ok", entries=[old, new], corrupt_line_no=None, error=None, line_count=2)
    assert prior_interrupt_uuid(read, new) is None
    same = _entry("c", "schema", "1", "2")
    read2 = TrailReadResult(status="ok", entries=[old, same, new], corrupt_line_no=None, error=None, line_count=3)
    assert prior_interrupt_uuid(read2, new) == "c"


def test_rules_module_does_not_import_unused_phantom() -> None:
    from src.core import session_uuid_backfill_rules as r
    assert not hasattr(r, "UUID_PHANTOM")


def test_skill_watch_store_recreates_its_schema_after_the_file_is_deleted(tmp_path: Path) -> None:
    from src.core.skill_watch.store import SkillWatchStore

    path = tmp_path / "skill_watch.db"
    store = SkillWatchStore(path)
    store.set_tripwire_offset("t1", 5)
    path.unlink()
    store.set_tripwire_offset("t1", 9)
    assert store.tripwire_offset("t1") == 9


def test_reused_pid_running_something_else_evicts_the_cached_version() -> None:
    from src.core.sessions import agent_update as au

    pid = 424242
    au.forget_running_version(pid)
    assert au.running_claude_version(pid, path_reader=lambda p: "/x/versions/2.1.283") == "2.1.283"
    assert au.running_claude_version(pid, path_reader=lambda p: "/usr/bin/vim") is None
    assert au.running_claude_version(pid, path_reader=lambda p: None) is None
