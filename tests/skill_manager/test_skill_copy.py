
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skills_command_routes, skills_manager_routes
from src.api.auth import require_auth
from src.core.skill_manager import copy_skill as copy_module
from tests.helpers.catalog_app import StateOnlySettings, register_projects
from src.core.db_migration import ensure_db_migrated


class Ledger:

    managed: list = []

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def list(self) -> tuple:
        return tuple(SimpleNamespace(install_id=str(i), item_id=f"pub/item{i}") for i, _ in enumerate(Ledger.managed))

    def targets(self, install_id: str) -> tuple:
        return (SimpleNamespace(path=Ledger.managed[int(install_id)]),)


def cols(body: dict, label: str, harness: str) -> dict:
    return next(c for c in body["columns"] if c["label"] == label and c["harness"] == harness)


def test_skill_copy(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    live, bare = tmp_path / "live", tmp_path / "bare"
    for path in (live, bare):
        (path / ".git").mkdir(parents=True)
    src = live / ".claude" / "skills" / "tool"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: tool\ndescription: d\nallowed-tools: Bash\n---\nbody\n", encoding="utf-8")
    (src / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    os.chmod(src / "scripts" / "run.sh", 0o755)
    (src / ".carnivore-skill.json").write_text("{}", encoding="utf-8")
    outside, trash_out = tmp_path / "outside", tmp_path / "trash_out"
    outside.mkdir()
    trash_out.mkdir()
    os.chmod(trash_out, 0o755)
    ln1, ln3 = tmp_path / "ln1", tmp_path / "ln3"
    for path in (ln1, ln3):
        (path / ".git").mkdir(parents=True)
    (ln1 / ".claude").symlink_to(outside)
    (ln3 / ".claude" / "skills" / "tool").mkdir(parents=True)
    (ln3 / ".claude" / "skills" / "tool" / "SKILL.md").write_text("---\nname: tool\ndescription: old\n---\nold\n", encoding="utf-8")
    (ln3 / ".claude" / ".carnivore-trash").symlink_to(trash_out)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    register_projects(state, [live, bare, home, ln1, ln3])
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_manager_routes.settings, "auth_config_file", str(config))
    Ledger.managed = []
    notified, staged_parents, swaps = [], [], []
    monkeypatch.setattr(copy_module.notifier, "notify", notified.append)
    real_copy, real_swap = copy_module.copy_tree, copy_module.swap_in
    monkeypatch.setattr(copy_module, "copy_tree", lambda s, d, **kw: (staged_parents.append(Path(d).parent.name), real_copy(s, d, **kw))[1])
    monkeypatch.setattr(copy_module, "swap_in", lambda *a, **kw: (swaps.append(a[1]), real_swap(*a, **kw))[1])
    app = FastAPI()
    app.include_router(skills_command_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.services = SimpleNamespace(
        settings_reader=StateOnlySettings(state), catalog=SimpleNamespace(ledger=Ledger),
        clock=SimpleNamespace(now=lambda: 1_790_000_000.0),
    )
    client = TestClient(app)

    matrix = client.get("/api/v1/skills/command-center").json()
    live_cl, bare_cl, bare_cx = cols(matrix, "project-0", "claude"), cols(matrix, "project-1", "claude"), cols(matrix, "project-1", "codex")
    home_cl = cols(matrix, "project-2", "claude")
    loc = next(r for r in matrix["rows"] if r["name"] == "tool")["cells"][live_cl["column_id"]][0]["location_id"]

    def post(targets, dry_run=True, **extra):
        body = {"source_location_id": loc, "source_column_id": live_cl["column_id"], "targets": targets, "dry_run": dry_run, **extra}
        return client.post("/api/v1/skills/copy", json=body)

    both = [{"column_id": bare_cl["column_id"]}, {"column_id": bare_cx["column_id"]}]
    dry = post(both).json()
    assert dry["source"]["scripts"] == ["scripts/run.sh"] and dry["source"]["exec_files"] == ["scripts/run.sh"]
    assert len(dry["source"]["source_digest"]) == 64 and dry["generation"] == matrix["generation"]
    assert [r["status"] for r in dry["results"]] == ["would_copy", "would_copy"]
    assert dry["results"][0]["creates_root"] and dry["results"][1]["ignored_frontmatter"] == ["allowed-tools"]
    assert not (bare / ".claude").exists() and not (bare / ".agents").exists() and not notified
    assert post(both, dry_run=False).status_code == 400
    stale = post(both, dry_run=False, generation="old", source_digest=dry["source"]["source_digest"])
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale" and not (bare / ".claude").exists()
    done = post(both, dry_run=False, generation=dry["generation"], source_digest=dry["source"]["source_digest"]).json()
    assert [r["status"] for r in done["results"]] == ["copied", "copied"]
    for root in (bare / ".claude" / "skills", bare / ".agents" / "skills"):
        assert os.access(root / "tool" / "scripts" / "run.sh", os.X_OK)
        assert not (root / "tool" / ".carnivore-skill.json").exists()
        assert [p.name for p in root.iterdir()] == ["tool"]
    assert staged_parents and all(p.startswith(".carnivore-staging-") for p in staged_parents)
    assert notified and set(notified) == {"local_skills"}
    (bare / ".claude" / "skills" / "tool" / "old.txt").write_text("old", encoding="utf-8")
    again = post([{"column_id": bare_cl["column_id"], "replace": True}]).json()
    assert again["results"][0]["status"] == "would_replace"
    swapped = post([{"column_id": bare_cl["column_id"], "replace": True}], dry_run=False,
                   generation=again["generation"], source_digest=again["source"]["source_digest"]).json()
    assert swapped["results"][0]["status"] == "replaced" and len(swaps) == 1
    trashed = Path(swapped["results"][0]["trashed_to"])
    assert trashed.parent == bare / ".claude" / ".carnivore-trash" and (trashed / "old.txt").read_text() == "old"
    assert not (bare / ".claude" / "skills" / "tool" / "old.txt").exists()
    assert [p.name for p in (bare / ".claude" / "skills").iterdir()] == ["tool"]
    assert post([{"column_id": bare_cl["column_id"]}]).json()["results"][0]["status"] == "skipped"
    Ledger.managed = [str(bare / ".agents" / "skills" / "tool")]
    managed_target = post([{"column_id": bare_cx["column_id"], "replace": True}]).json()
    assert managed_target["results"][0]["status"] == "use_catalog_uninstall"
    Ledger.managed = [str(src)]
    managed_source = post(both).json()
    assert {r["status"] for r in managed_source["results"]} == {"use_catalog_install"}
    assert managed_source["results"][0]["item_id"] == "pub/item0"
    Ledger.managed = []
    home_try = post([{"column_id": home_cl["column_id"]}]).json()["results"][0]
    assert home_try["status"] == "refused" and home_try["code"] == "home_folder" and not (home / ".claude" / "skills").exists()
    ln1_cl = cols(matrix, "project-3", "claude")
    for dry_flag in (True, False):
        now = post([{"column_id": ln1_cl["column_id"]}]).json()
        extra = {} if dry_flag else {"generation": now["generation"], "source_digest": now["source"]["source_digest"]}
        res = post([{"column_id": ln1_cl["column_id"]}], dry_run=dry_flag, **extra).json()["results"][0]
        assert res["status"] == "refused" and res["code"] == "target_unsafe"
    assert os.listdir(outside) == []
    ln3_cl = cols(matrix, "project-4", "claude")
    fresh = post([{"column_id": ln3_cl["column_id"], "replace": True}]).json()
    assert fresh["results"][0]["status"] == "would_replace" and fresh["results"][0]["trash_new"] is False
    trashed = post([{"column_id": ln3_cl["column_id"], "replace": True}], dry_run=False, generation=fresh["generation"],
                   source_digest=fresh["source"]["source_digest"]).json()["results"][0]
    assert trashed["status"] == "refused" and trashed["code"] == "target_unsafe"
    assert os.listdir(trash_out) == [] and (trash_out.stat().st_mode & 0o777) == 0o755
    assert "old" in (ln3 / ".claude" / "skills" / "tool" / "SKILL.md").read_text()
    assert [p.name for p in (ln3 / ".claude" / "skills").iterdir()] == ["tool"]
    pre = post(both).json()
    os.chmod(src / "SKILL.md", 0o755)
    late = post(both, dry_run=False, generation=pre["generation"], source_digest=pre["source"]["source_digest"])
    assert late.status_code == 409 and late.json()["detail"]["code"] == "stale"
    os.chmod(src / "SKILL.md", 0o644)
    (src / "link").symlink_to(tmp_path)
    linked = post(both)
    assert linked.status_code == 409 and linked.json()["detail"]["code"] == "symlink_in_skill"
