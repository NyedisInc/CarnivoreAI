
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

from src.core.crate_format.backup_files import is_backup_point_file
from src.core.crate_import import backups_in
from src.core.crate_import.env import ImportEnv
from src.core.deepsearch import fallback_hook as fb
from src.core.inventory import plugin_stores
from src.core.inventory.locations import Locations
from src.cplugs.crate import constants as K
from src.cplugs.crate.backup_points import plan_backups
from src.cplugs.sdk import data_decl

FOLDER = {"own": "excluded", "share": "excluded", "reason": "the points of every conversation", "purge": "kept"}


def vault_decl(**extra: Any) -> dict:
    return {"id": "vault", "kind": "folder", "root_setting": "where", "default": "vault", "scope_by": "session_uuid", "policy": FOLDER,
            "provides": "backup_points", **extra}


def test_the_declaration_parses_and_the_contract_checks_it() -> None:
    fields = {"where": {"type": "string"}}
    assert data_decl.parse_data([vault_decl()], fields)[0].provides == data_decl.PROVIDES_BACKUP_POINTS
    assert data_decl.problems_in([vault_decl(provides="teapot")], fields)
    not_a_folder = {k: v for k, v in vault_decl(kind="db").items() if k not in ("default",)}
    assert any("only a kind folder" in p for p in data_decl.problems_in([not_a_folder], fields))
    twice = [vault_decl(), vault_decl(id="vault2")]
    assert any("already provided" in p for p in data_decl.problems_in(twice, fields))


def test_the_save_plugin_declares_it() -> None:
    from src.cplugs.registry import CPLUGS

    save = next(d.manifest for d in CPLUGS if d.id == "save")
    assert [d.id for d in save.data if d.provides == data_decl.PROVIDES_BACKUP_POINTS] == ["vault"]
    others = [d.id for d in CPLUGS if d.id != "save" and any(x.provides for x in d.manifest.data or ())]
    assert others == []


def locs(tmp: Path, enabled: bool) -> Locations:
    return Locations(state_dir=tmp, config_path=tmp / "config.json", plugin_enabled={"save": enabled})


def test_a_provider_that_is_off_provides_nothing(tmp_path: Path) -> None:
    assert plugin_stores.backup_provider(locs(tmp_path, False)) is None
    assert plugin_stores.backup_provider(locs(tmp_path, True)).plugin_id == "save"


def point(conversation: str = "c1", point_id: str = "20261019T101010Z-kill") -> fb.FallbackPoint:
    file = fb.FallbackPointFile(role="transcript", home="claude", rel="projects/-p/c1.jsonl", source_path="/x/c1.jsonl", length=3, sha256="ab" * 32)
    return fb.FallbackPoint(conversation, point_id, "kill", 1.0, "2026-10-19T10:10:10Z", "claude", (file,))


class Source:

    def list_points(self, conversation: str) -> List[fb.FallbackPoint]:
        return [point(conversation)]


def test_the_points_are_filed_under_the_provider_the_contract_names() -> None:
    walk = plan_backups(["c1"], "vaultx", sources=[Source()])
    assert walk.blockers == [] and walk.files
    assert {f.home for f in walk.files} == {"plugin-vaultx"} and {f.plugin for f in walk.files} == {"vaultx"}
    assert {f.provides for f in walk.files} == {"backup_points"} and walk.files[0].rel.startswith("backups/c1/")


def test_no_enabled_provider_is_the_backups_unavailable_blocker() -> None:
    assert [c for c, _ in plan_backups(["c1"], None, sources=[Source()]).blockers] == [K.B_BACKUPS_OFF]
    assert [c for c, _ in plan_backups(["c1"], "save", sources=[]).blockers] == [K.B_BACKUPS_OFF]


def test_a_crate_written_before_the_contract_still_reads() -> None:
    rel = "backups/c1/p1/point.json"
    assert is_backup_point_file("plugin_file", "plugin-save", rel, {})
    assert is_backup_point_file("plugin_file", "plugin-vaultx", rel, {"provides": "backup_points"})
    assert not is_backup_point_file("plugin_file", "plugin-vaultx", rel, {})
    assert not is_backup_point_file("plugin_file", "plugin-vaultx", "other/c1", {"provides": "backup_points"})
    assert not is_backup_point_file("transcript", "plugin-save", rel, {})
    record = SimpleNamespace(role="plugin_file", home="plugin-save", rel=rel, extra={})
    assert backups_in._own_record(record)


def test_the_import_plan_says_whether_a_provider_takes_the_points(tmp_path: Path) -> None:
    taker = SimpleNamespace(adopt_points=lambda *a, **k: [], list_points=lambda c: [])
    base = dict(state=tmp_path, projects_dir=str(tmp_path), claude_homes=(tmp_path,), codex_home=tmp_path, install_id="i", panes=lambda: None)
    on = ImportEnv(**base, backup_sources=lambda: [taker])
    off = ImportEnv(**base, backup_sources=lambda: [])
    for env, enabled in ((on, True), (off, False)):
        view = backups_in.plan_view({}, env, filing=True, excluded=[])
        assert view["provider_enabled"] is enabled
