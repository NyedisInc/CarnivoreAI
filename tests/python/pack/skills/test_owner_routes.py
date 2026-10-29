
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.core.pack.skills.scan import scan_skill

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import auth as auth_mod  # noqa: E402
from src.api import pack_skills_routes as routes  # noqa: E402
from src.core.pack.machines.config_state import ConfigState  # noqa: E402
from src.core.pack.skills import wiring  # noqa: E402
from src.core.pack.skills.receiver import ReceiverState  # noqa: E402
from src.core.pack.skills.runtime import PeerView, SkillsSync  # noqa: E402
from src.core.pack.skills.targets import receiver_roots  # noqa: E402

BASE = "/api/v1"


def put(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Rig:

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.home = tmp / "home"
        (self.home / ".carnivore" / "accounts").mkdir(parents=True)
        put(self.home, ".claude/skills/sme/SKILL.md", "# sme\n")
        put(self.home, ".claude/skills/other/SKILL.md", "# other\n")
        self.cfg = tmp / "config.json"
        self.cfg.write_text("{}", encoding="utf-8")
        self.alpha = "A"
        self.rows: list = []
        self.notified = 0
        state = ReceiverState(tmp / "state" / "skills-state.json")
        self.sync = SkillsSync(
            install_id="A", state=state, alpha_id=lambda: self.alpha, choices=wiring.ConfigChoices(ConfigState(lambda: self.cfg)),
            family_roots=lambda: {"claude": self.home / ".claude" / "skills", "codex": self.home / ".agents" / "skills"},
            receiver_roots=lambda: receiver_roots(self.home, self.home / ".carnivore" / "accounts", []),
            peers=lambda: [PeerView("B", "studio", True, {"capabilities": ["pack.skills"]})], request_for=lambda _p: self.request,
            notify=self.bump, outbox=tmp / "outbox")
        self.sync.refresh_alpha()
        monkeypatch.setattr(wiring, "SYNC", self.sync)
        routes.TOKENS.clear()
        app = FastAPI()
        app.include_router(routes.router, prefix=BASE)
        app.dependency_overrides[auth_mod.require_auth] = lambda: None
        self.client = TestClient(app)

    def bump(self) -> None:
        self.notified += 1

    async def request(self, method, path, **_kw):
        assert (method, path) == ("GET", "/federation/pack/skills/inventory")
        return 200, {"skills": self.rows, "truncated": False, "applied_gen": 0}

    def stored(self) -> dict:
        return json.loads(self.cfg.read_text(encoding="utf-8")).get("pack_machines", {}).get("skills_sync", {})

    def choose(self, body: dict):
        return self.client.put(f"{BASE}/pack/skills/choices", json=body)


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


def test_owner_routes(rig: Rig):
    want = {"mode": "some", "include": [["claude", "sme"]], "exclude": []}

    assert rig.choose({**want, "dry_run": True}).status_code == 200
    rig.alpha = "B"
    rig.sync.refresh_alpha()
    refused = rig.choose({**want, "dry_run": True})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert (detail["code"], detail["alpha_install_id"], detail["alpha_label"]) == ("not_alpha", "B", "studio")
    assert rig.client.put(f"{BASE}/pack/skills/claude/sme", json={"synced": True, "dry_run": True}).status_code == 409
    rig.alpha = "A"
    rig.sync.refresh_alpha()

    assert rig.choose({**want, "dry_run": False}).status_code == 409
    assert rig.stored() == {}

    dry = rig.choose({**want, "dry_run": True}).json()
    assert dry["computers"][0]["label"] == "studio" and dry["computers"][0]["add"] == 1
    assert [s["name"] for s in dry["skills"]] == ["sme"]
    before = rig.notified
    done = rig.choose({**want, "dry_run": False, "plan_token": dry["plan_token"]})
    assert done.status_code == 200
    assert rig.stored() == {"mode": "some", "include": [["claude", "sme"]], "exclude": []}
    assert rig.notified > before
    assert rig.choose({**want, "mode": "all", "dry_run": False, "plan_token": dry["plan_token"]}).status_code == 409
    assert rig.stored()["mode"] == "some"

    wider = {"mode": "all", "include": [], "exclude": []}
    dry = rig.choose({**wider, "dry_run": True}).json()
    rig.rows = [["claude", "sme", "abc123", "f" * 64, False]]
    stale = rig.choose({**wider, "dry_run": False, "plan_token": dry["plan_token"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "plan_stale"
    assert rig.stored()["mode"] == "some"

    dry = rig.client.put(f"{BASE}/pack/skills/claude/sme", json={"synced": False, "remove_elsewhere": True, "dry_run": True}).json()
    ok = rig.client.put(f"{BASE}/pack/skills/claude/sme",
                        json={"synced": False, "remove_elsewhere": True, "dry_run": False, "plan_token": dry["plan_token"]})
    assert ok.status_code == 200 and rig.stored()["include"] == []
    assert [r[:2] for r in rig.sync.state.load()["queued"]["removals"]] == [["claude", "sme"]]

    view = rig.client.get(f"{BASE}/pack/skills").json()
    assert view["role"] == "alpha" and {r["name"] for r in view["rows"]} == {"sme", "other"}


def test_trash_placed_only_that_computer(rig: Rig):
    leaf = rig.home / ".claude" / "skills"
    put(leaf, "fromx/SKILL.md")
    put(leaf, "fromy/SKILL.md")
    rows = [{"family": "claude", "name": n, "root": str(leaf), "alpha": a, "gen": 1, "digest": scan_skill(leaf / n, n).digest, "state": "in sync", "reason": "",
             "at": 1, "placed": True} for n, a in (("fromx", "X"), ("fromy", "Y"))]
    data = rig.sync.state.load()
    data["applied"] = rows
    assert rig.sync.state.save(data)

    out = rig.client.post(f"{BASE}/pack/skills/trash-placed", json={"from_install_id": "X"})
    assert out.status_code == 200 and out.json()["trashed"] == 1
    trash = rig.home / ".claude" / ".carnivore-trash"
    assert not (leaf / "fromx").exists() and (leaf / "fromy").exists()
    assert [p.name.split("-")[0] for p in trash.iterdir() if not p.name.startswith(".")] == ["fromx"]
    assert [r["name"] for r in rig.sync.state.load()["applied"]] == ["fromy"]
    assert rig.client.post(f"{BASE}/pack/skills/trash-placed", json={"from_install_id": "Z"}).json()["trashed"] == 0
    assert (leaf / "fromy").exists()


def test_status_tool_reads_the_matrix():
    from src.core.mcp import pack_skills_tools

    assert [s.name for s in pack_skills_tools.SPECS] == ["pack_skills_status"]
    assert pack_skills_tools.SPECS[0].route == "src.api.pack_skills_routes:get_skills"
    assert pack_skills_tools.SPECS[0].gate == "read"


def test_one_name_switches_every_family_under_one_plan_token(rig: Rig):
    put(rig.home, ".agents/skills/sme/SKILL.md", "# sme codex\n")
    base = {"mode": "some", "include": [["claude", "other"]], "exclude": []}
    dry = rig.choose({**base, "dry_run": True}).json()
    assert rig.choose({**base, "dry_run": False, "plan_token": dry["plan_token"]}).status_code == 200

    url = f"{BASE}/pack/skills/claude/sme"
    body = {"synced": True, "families": ["claude", "codex"]}
    dry = rig.client.put(url, json={**body, "dry_run": True}).json()
    assert sorted((s["family"], s["name"]) for s in dry["skills"]) == [("claude", "sme"), ("codex", "sme")]
    assert dry["others"] == 1 and "claude/other" not in dry["computers"][0]["skills"]
    assert dry["computers"][0]["add"] == 2
    done = rig.client.put(url, json={**body, "dry_run": False, "plan_token": dry["plan_token"]})
    assert done.status_code == 200
    assert sorted(rig.stored()["include"]) == [["claude", "other"], ["claude", "sme"], ["codex", "sme"]]
    one = rig.client.put(url, json={"synced": True, "dry_run": False, "plan_token": dry["plan_token"]})
    assert one.status_code == 409

    wide = rig.choose({"mode": "all", "include": [], "exclude": [], "dry_run": True}).json()
    assert len(wide["skills"]) == 3 and wide["others"] == 0
