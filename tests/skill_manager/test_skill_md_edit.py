
from __future__ import annotations

import hashlib
import io
import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skill_md_edit_routes, skills_manager_routes
from src.api.auth import require_auth
from src.core import slash_command_discovery as scd
from src.core.db_migration import ensure_db_migrated
from src.core.event_hub import EventHub
from src.core.live_ports import SystemClock
from src.core.skill_manager import local_skill_md
from src.core.skill_manager.skill_md_edit import MAX_EDIT_BYTES, save_edit
from src.core.skill_manager.skill_md_versions import SkillMdVersionStore
from src.core.skill_manager.types import OverrideError
from tests.helpers.catalog_app import StateOnlySettings
from tests.skill_manager.test_inventory_shadowing import NoIndex, NoLedger, make_skill

BASE = "/api/v1/skills/locations"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    claude = home / ".claude"
    plain = make_skill(claude / "skills", "plain")
    foreign = make_skill(tmp_path / "foreign", "outside")
    os.symlink(foreign, claude / "skills" / "linked")
    sneaky = make_skill(claude / "skills", "sneaky")
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("---\nname: sneaky\ndescription: d\n---\nsecret\n", encoding="utf-8")
    (sneaky / "SKILL.md").unlink()
    os.symlink(outside_file, sneaky / "SKILL.md")
    make_skill(claude / "plugins" / "cache" / "mk" / "plug" / "1.0.0" / "skills", "plug-skill")
    monkeypatch.setattr(scd, "CLAUDE_HOME", claude)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_manager_routes.settings, "auth_config_file", str(config))
    notified = []
    monkeypatch.setattr(skill_md_edit_routes.notifier, "notify", notified.append)
    app = FastAPI()
    app.include_router(skills_manager_routes.router, prefix="/api/v1")
    app.include_router(skill_md_edit_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.event_hub = EventHub()
    app.state.services = SimpleNamespace(
        settings_reader=StateOnlySettings(state),
        catalog=SimpleNamespace(ledger=NoLedger, index_cache=NoIndex()),
        clock=SystemClock(),
    )
    return SimpleNamespace(
        plain=plain, foreign=foreign, outside_file=outside_file, client=TestClient(app), notified=notified, state=state
    )


def loc(world, folder: str) -> str:
    body = world.client.get("/api/v1/skills").json()
    ids = [x["location_id"] for g in body["skills"] for x in g["locations"] if x["folder"] == folder]
    assert len(ids) == 1, (folder, ids)
    return ids[0]


def put(world, loc_id: str, content: str, base: str, **extra):
    return world.client.put(f"{BASE}/{loc_id}/skill-md", json={"content": content, "base_sha256": base, **extra})


def test_edit_versions_restore(world):
    lid = loc(world, "plain")
    md = world.plain / "SKILL.md"
    original = md.read_text(encoding="utf-8")
    got = world.client.get(f"{BASE}/{lid}/skill-md").json()
    assert got["sha256"] == sha(original)
    assert world.client.get(f"{BASE}/{lid}/skill-md/versions").json() == {"versions": [], "current": None}

    v1 = "---\nname: plain\ndescription: d\n---\nedited once\n"
    done = put(world, lid, v1, got["sha256"], note="first")
    assert done.status_code == 200, done.text
    assert md.read_text(encoding="utf-8") == v1 and done.json()["sha256"] == sha(v1)
    assert world.notified == ["local_skills"]
    assert not [p for p in os.listdir(world.plain) if p.startswith(".skill-md-")]

    stale = put(world, lid, "---\nname: plain\ndescription: d\n---\nlost\n", got["sha256"])
    assert stale.status_code == 409
    assert stale.json()["current_sha256"] == sha(v1) == stale.json()["detail"]["current_sha256"]
    assert md.read_text(encoding="utf-8") == v1

    got_list = world.client.get(f"{BASE}/{lid}/skill-md/versions").json()
    cur, older = got_list["current"], got_list["versions"]
    assert cur["id"] == done.json()["version_id"] and cur["note"] == "first" and cur["action"] == "edit" and cur["sha256"] == sha(v1)
    assert cur["lines"] == len(v1.splitlines()) and cur["size"] == len(v1.encode()) and cur["created_at"] > 0
    assert len(older) == 1 and older[0]["action"] == "baseline" and older[0]["note"] == "" and older[0]["sha256"] == sha(original)
    assert older[0]["lines"] == len(original.splitlines()) and older[0]["size"] == len(original.encode())
    one = world.client.get(f"{BASE}/{lid}/skill-md/versions/{older[0]['id']}").json()
    assert one == {"content": original, "sha256": sha(original)}
    assert world.client.get(f"{BASE}/{lid}/skill-md/versions/9999").status_code == 404

    back = world.client.post(f"{BASE}/{lid}/skill-md/versions/{older[0]['id']}/restore", json={"base_sha256": sha(v1)})
    assert back.status_code == 200 and md.read_text(encoding="utf-8") == original
    assert back.json()["sha256"] == sha(original)
    after = world.client.get(f"{BASE}/{lid}/skill-md/versions").json()
    assert after["current"]["id"] == back.json()["version_id"] and after["current"]["action"] == "restore"
    assert after["current"]["sha256"] == sha(original) and after["current"]["note"] == f"restored version {older[0]['id']}"
    redo = world.client.post(f"{BASE}/{lid}/skill-md/versions/{cur['id']}/restore", json={"base_sha256": sha(original)})
    assert redo.status_code == 200 and md.read_text(encoding="utf-8") == v1
    bad = world.client.post(f"{BASE}/{lid}/skill-md/versions/{cur['id']}/restore", json={"base_sha256": sha(original)})
    assert bad.status_code == 409


def test_refusals_write_nothing(world):
    text = "---\nname: x\ndescription: d\n---\nnew\n"
    foreign_md = world.foreign / "SKILL.md"
    before_foreign = foreign_md.read_bytes()
    linked = put(world, loc(world, "linked"), text, sha(before_foreign.decode()))
    assert linked.status_code == 409 and linked.json()["detail"]["code"] == "target_unsafe"
    assert foreign_md.read_bytes() == before_foreign
    before_out = world.outside_file.read_bytes()
    assert not [1 for g in world.client.get("/api/v1/skills").json()["skills"] for x in g["locations"] if x["folder"] == "sneaky"]
    root = {"path": str(world.plain.parent), "is_symlink": False, "read_only": False, "scope": "user"}
    with pytest.raises(OverrideError) as refused:
        save_edit(SkillMdVersionStore(world.state / "v.db"), {"folder": "sneaky"}, root, text, sha(before_out.decode()))
    assert refused.value.code == "target_unsafe"
    assert world.outside_file.read_bytes() == before_out
    plug = put(world, loc(world, "plug-skill"), text, "0" * 64)
    assert plug.status_code == 403 and plug.json()["detail"]["code"] == "read_only"

    lid = loc(world, "plain")
    md = world.plain / "SKILL.md"
    base = sha(md.read_text(encoding="utf-8"))
    token = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"
    secret = put(world, lid, f"---\nname: plain\ndescription: d\n---\nkey {token}\n", base)
    assert secret.status_code == 422 and secret.json()["detail"]["code"] == "secret_detected"
    assert token not in secret.text
    big = put(world, lid, "x" * (MAX_EDIT_BYTES + 1), base)
    assert big.status_code == 413
    assert sha(md.read_text(encoding="utf-8")) == base
    assert world.client.get(f"{BASE}/{lid}/skill-md/versions").json() == {"versions": [], "current": None}
    assert world.client.get(f"{BASE}/nope/skill-md/versions").status_code == 404
    assert not world.notified


def test_removed_secret_is_not_kept_and_versions_delete(world):
    lid = loc(world, "plain")
    md = world.plain / "SKILL.md"
    token = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"
    leaky = f"---\nname: plain\ndescription: d\n---\nkey {token}\n"
    md.write_text(leaky, encoding="utf-8")
    clean = "---\nname: plain\ndescription: d\n---\nclean\n"
    done = put(world, lid, clean, sha(leaky))
    assert done.status_code == 200, done.text
    listing = world.client.get(f"{BASE}/{lid}/skill-md/versions").json()["versions"]
    vid = listing[0]["id"]
    assert listing[0]["redacted"] is True and listing[0]["sha256"] == sha(leaky) and vid != done.json()["version_id"]
    got = world.client.get(f"{BASE}/{lid}/skill-md/versions/{vid}")
    assert got.status_code == 409 and token not in got.text
    back = world.client.post(f"{BASE}/{lid}/skill-md/versions/{vid}/restore", json={"base_sha256": sha(clean)})
    assert back.status_code == 409 and md.read_text(encoding="utf-8") == clean
    assert token.encode() not in (world.state / "skill_md_versions.db").read_bytes()
    assert (os.stat(world.state / "skill_md_versions.db").st_mode & 0o777) == 0o600
    assert world.client.delete(f"{BASE}/{lid}/skill-md/versions/{vid}").json() == {"deleted": True}
    assert world.client.delete(f"{BASE}/{lid}/skill-md/versions/{vid}").status_code == 404
    assert world.client.get(f"{BASE}/{lid}/skill-md/versions").json()["versions"] == []


def test_polish_hash_vanish_oversize_identity(world, monkeypatch):
    lid = loc(world, "plain")
    md = world.plain / "SKILL.md"
    first = md.read_text(encoding="utf-8")
    def read_then_rewrite(path, mode="r"):
        with open(path, mode) as handle:
            data = handle.read()
        md.write_text("---\nname: plain\ndescription: d\n---\nrewritten\n", encoding="utf-8")
        return io.BytesIO(data)

    with monkeypatch.context() as patched:
        patched.setattr(local_skill_md, "open", read_then_rewrite, raising=False)
        got = world.client.get(f"{BASE}/{lid}/skill-md").json()
    assert got["body"] == first and got["sha256"] == sha(first)
    md.write_text(first, encoding="utf-8")
    huge = "x" * (MAX_EDIT_BYTES * 8)
    assert put(world, lid, huge, sha(first)).status_code == 413
    def chunks():
        yield b'{"content": "'
        yield b"x" * (skill_md_edit_routes.MAX_SAVE_BODY + 10)
    assert world.client.put(f"{BASE}/{lid}/skill-md", content=chunks()).status_code == 413
    assert md.read_text(encoding="utf-8") == first
    from src.core.skill_manager import skill_md_edit as edit_mod
    with monkeypatch.context() as patched:
        patched.setattr(edit_mod, "_replace_file", lambda *a: (_ for _ in ()).throw(FileNotFoundError("gone")))
        gone = put(world, lid, first + "more\n", sha(first))
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "gone"
    assert put(world, lid, first + "edited\n", sha(first)).status_code == 200
    assert world.client.get(f"{BASE}/{lid}/skill-md/versions").json()["current"] is not None
    import shutil
    shutil.rmtree(world.plain)
    make_skill(world.plain.parent, "plain")
    again = world.client.get(f"{BASE}/{loc(world, 'plain')}/skill-md/versions").json()
    assert again == {"versions": [], "current": None}
