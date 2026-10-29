
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import auth as auth_mod  # noqa: E402
from src.api import federation_pack_skills_routes as peer_routes  # noqa: E402
from src.api import pack_skills_routes as routes  # noqa: E402
from src.api.peer_auth import Principal  # noqa: E402
from src.core.federation.grants import Grant  # noqa: E402
from src.core.pack.machines.config_state import ConfigState  # noqa: E402
from src.core.pack.skills import take_export, wiring  # noqa: E402
from src.core.pack.skills.receiver import ReceiverState  # noqa: E402
from src.core.pack.skills.runtime import PeerView, SkillsSync  # noqa: E402
from src.core.pack.skills.scan import scan_root  # noqa: E402
from src.core.pack.skills.targets import receiver_roots  # noqa: E402

BASE = "/api/v1"
PEER = BASE + "/federation/pack/skills"
OLD_PEER_CAPS = ["pack.skills"]
NEW_PEER_CAPS = ["pack.skills", "pack.skills.take"]


def tree(path: Path) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(path))
            if full.is_symlink():
                out[rel] = ("link", os.readlink(full))
            elif full.is_dir():
                out[rel] = ("dir", "")
            else:
                out[rel] = ("file", hashlib.sha256(full.read_bytes()).hexdigest(), os.access(full, os.X_OK))
    return out


def write(root: Path, rel: str, text: str = "x\n", mode: int = 0o644) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)


class Rig:

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.tmp = tmp
        self.a_home, self.b_home, self.a_state, self.b_state = tmp / "a-home", tmp / "b-home", tmp / "a-state", tmp / "b-state"
        write(self.b_home, ".claude/skills/thoronly/SKILL.md", "# studio only\n")
        write(self.b_home, ".claude/skills/thoronly/scripts/run.sh", "#!/bin/sh\n", 0o755)
        write(self.b_home, ".claude/skills/thoronly/node_modules/p/i.js", "studio's build\n")
        write(self.b_home, ".claude/skills/sme/SKILL.md", "# sme, studio's edit\n")
        write(self.b_home, ".claude/skills/catalogued/SKILL.md", "# from the catalog\n")
        write(self.b_home, ".claude/skills/catalogued/.carnivore-skill.json", "{}\n")
        write(self.b_home, ".claude/skills/leaky/SKILL.md", "# leaky\n")
        write(self.b_home, ".claude/skills/leaky/.env", "TOKEN=abc\n")
        write(self.a_home, ".claude/skills/sme/SKILL.md", "# sme on alpha\n")
        write(self.a_home, ".claude/skills/sme/node_modules/q/i.js", "alpha's build\n")
        write(self.tmp, "elsewhere/keep.md", "not ours\n")
        (self.a_home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
        os.symlink(self.tmp / "elsewhere", self.a_home / ".claude" / "skills" / "linked")
        accounts = self.a_home / ".carnivore" / "accounts"
        (accounts / "abcdef012345-work-relay").mkdir(parents=True)
        write(accounts, "nyedis/auth.json", "{}\n")
        self.accounts = accounts
        self.calls: list[tuple[str, str]] = []
        self.caps = NEW_PEER_CAPS
        self.up = True
        self.caller = "A"

        monkeypatch.setattr(peer_routes, "state_dir", lambda: self.b_state)
        monkeypatch.setattr(peer_routes, "roots_now", lambda: receiver_roots(self.b_home, self.b_home / ".carnivore" / "accounts", []))
        monkeypatch.setattr(peer_routes, "held_alpha", lambda: "A")
        monkeypatch.setattr(peer_routes.direction, "contained", lambda _peer: False)
        peer_routes._STATES.clear()
        peer_routes._HITS.clear()
        b_app = FastAPI()
        b_app.include_router(peer_routes.router, prefix=BASE)
        b_app.dependency_overrides[peer_routes._require_skills] = self.principal
        self.b = TestClient(b_app)

        self.cfg = tmp / "config.json"
        self.cfg.write_text("{}", encoding="utf-8")
        self.alpha_id = "A"
        self.sync = SkillsSync(
            install_id="A", state=ReceiverState(self.a_state / "skills-state.json"), alpha_id=lambda: self.alpha_id,
            choices=wiring.ConfigChoices(ConfigState(lambda: self.cfg)),
            family_roots=lambda: {"claude": self.a_home / ".claude" / "skills", "codex": self.a_home / ".agents" / "skills"},
            receiver_roots=lambda: receiver_roots(self.a_home, accounts, []),
            peers=lambda: [PeerView("B", "studio", self.up, {"capabilities": self.caps})], request_for=lambda _p: self.request,
            notify=lambda: None, outbox=tmp / "outbox")
        self.sync.refresh_alpha()
        monkeypatch.setattr(wiring, "SYNC", self.sync)
        routes.TOKENS.clear()
        a_app = FastAPI()
        a_app.include_router(routes.router, prefix=BASE)
        a_app.dependency_overrides[auth_mod.require_auth] = lambda: None
        self.a = TestClient(a_app)

    def principal(self) -> Principal:
        return Principal("peer", Grant("g1", self.caller, "k", "f", "alpha", ("skills",), None, "t", None, None))

    async def request(self, method, path, json=None, **_kw):
        self.calls.append((method, path))
        reply = self.b.request(method, BASE + path, json=json)
        return reply.status_code, reply.json()

    def take(self, name: str = "thoronly", family: str = "claude", dry_run: bool = True, token: str | None = None):
        body = {"from_install_id": "B", "family": family, "name": name, "dry_run": dry_run, **({"plan_token": token} if token else {})}
        return self.a.post(f"{BASE}/pack/skills/take", json=body)

    def take_through(self, name: str = "thoronly") -> dict:
        dry = self.take(name)
        assert dry.status_code == 200, dry.text
        done = self.take(name, dry_run=False, token=dry.json()["plan_token"])
        assert done.status_code == 200, done.text
        return done.json()

    def leftovers(self) -> list[str]:
        found = [p.name for p in (self.a_state / "skills-take").iterdir()] if (self.a_state / "skills-take").exists() else []
        export = self.b_state / "pack" / "skills-export"
        return found + ([p.name for p in export.iterdir()] if export.exists() else [])

    def hostile(self, monkeypatch, member: tarfile.TarInfo | None, data: bytes = b"", skill: str = "thoronly", tamper: bool = False) -> None:
        scan = scan_root(self.b_home / ".claude" / "skills", "claude").skills["thoronly"]

        def make(_roots, family, name, directory):
            listing = {"v": 1, "skills": {f"claude/{skill}": [{"path": f.path, "size": f.size, "mode": f.mode, "sha256": f.sha256} for f in scan.files]}}
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            blob_id = "hostile-0123456789"
            out = directory / f"{blob_id}.tgz"
            with tarfile.open(out, "w:gz") as tar:
                raw = json.dumps(listing).encode()
                info = tarfile.TarInfo("files.json")
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
                for f in scan.files:
                    body = (self.b_home / ".claude" / "skills" / "thoronly" / f.path).read_bytes()
                    body = body + b"!" if tamper and f.path == "SKILL.md" else body
                    item = tarfile.TarInfo(f"claude/{skill}/{f.path}")
                    item.size, item.mode = len(body), 0o755 if f.mode == "100755" else 0o644
                    tar.addfile(item, io.BytesIO(body))
                if member is not None:
                    member.size = len(data)
                    tar.addfile(member, io.BytesIO(data))
            return {"blob_id": blob_id, "size": out.stat().st_size, "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "digest": scan.digest}

        monkeypatch.setattr(peer_routes.take_export, "make_export", make)


@pytest.fixture()
def rig(tmp_path, monkeypatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


def test_a_take_lands_the_peers_bytes_and_trashes_alphas_old_copy(rig: Rig) -> None:
    accounts_before, elsewhere = tree(rig.accounts / "nyedis"), tree(rig.tmp / "elsewhere")
    default = rig.a_home / ".claude" / "skills"
    before = tree(rig.a_home)

    dry = rig.take("thoronly")
    assert dry.status_code == 200, dry.text
    shown = dry.json()
    assert (shown["from"], shown["here"], shown["scripts"]) == ("studio", "absent", ["scripts/run.sh"]) and shown["plan_token"]
    assert tree(rig.a_home) == before and rig.leftovers() == []

    assert rig.take("thoronly", dry_run=False).status_code == 409
    assert tree(rig.a_home) == before
    done = rig.take("thoronly", dry_run=False, token=shown["plan_token"])
    assert done.status_code == 200 and done.json()["ok"] is True, done.text
    relay = rig.accounts / "abcdef012345-work-relay" / "skills" / "thoronly"
    for live in (default / "thoronly", relay):
        assert (live / "SKILL.md").read_text() == "# studio only\n"
        assert os.access(live / "scripts" / "run.sh", os.X_OK)
        assert not (live / "node_modules").exists()
    assert rig.take("thoronly", dry_run=False, token=shown["plan_token"]).status_code == 409
    assert tree(rig.accounts / "nyedis") == accounts_before and not (rig.accounts / "nyedis" / "skills").exists()
    assert tree(rig.tmp / "elsewhere") == elsewhere and rig.leftovers() == []
    assert any(path.endswith("/done") for _m, path in rig.calls)

    assert rig.take("sme").json()["here"] == "differs"
    assert rig.take_through("sme")["ok"] is True
    assert (default / "sme" / "SKILL.md").read_text() == "# sme, studio's edit\n"
    assert (default / "sme" / "node_modules" / "q" / "i.js").read_text() == "alpha's build\n"
    kept = [p for p in (rig.a_home / ".claude" / ".carnivore-trash").iterdir() if p.name.startswith("sme-")]
    assert len(kept) == 1 and (kept[0] / "SKILL.md").read_text() == "# sme on alpha\n"
    assert rig.leftovers() == []


def test_the_token_is_bound_to_the_bytes_that_were_shown(rig: Rig) -> None:
    dry = rig.take("sme").json()
    write(rig.b_home, ".claude/skills/sme/SKILL.md", "# changed after the dry run\n")
    before = tree(rig.a_home)
    stale = rig.take("sme", dry_run=False, token=dry["plan_token"])
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "plan_stale"
    assert tree(rig.a_home) == before and rig.leftovers() == []
    assert rig.take_through("sme")["ok"] is True


@pytest.mark.parametrize("name,kind,link,tamper", [("claude/thoronly/../../x", tarfile.REGTYPE, "", False), ("/abs/evil", tarfile.REGTYPE, "", False),
                                                    ("claude/thoronly/a\0b", tarfile.REGTYPE, "", False),
                                                    ("claude/thoronly/link", tarfile.SYMTYPE, "/etc/hosts", False), ("", None, "", True)])
def test_a_hostile_copy_changes_nothing(rig: Rig, monkeypatch, name: str, kind, link: str, tamper: bool) -> None:
    before = {p: tree(p) for p in (rig.a_home, rig.tmp / "elsewhere")}
    member = None
    if kind is not None:
        member = tarfile.TarInfo(name)
        member.type, member.linkname = kind, link
    rig.hostile(monkeypatch, None)
    ok = rig.take("thoronly")
    assert ok.status_code == 200, ok.text
    rig.hostile(monkeypatch, member, b"evil" if kind == tarfile.REGTYPE else b"", tamper=tamper)
    for dry in (True, False):
        answer = rig.take("thoronly", dry_run=dry, token=None if dry else "a-token")
        assert (answer.status_code, answer.json()["detail"]["code"]) == (409, "bad_bundle"), answer.text
    assert {p: tree(p) for p in before} == before
    assert rig.leftovers() == [] or rig.leftovers() == ["hostile-0123456789.tgz"]
    assert not (rig.tmp / "x").exists()


def test_another_skills_name_in_the_copy_is_refused(rig: Rig, monkeypatch) -> None:
    before = tree(rig.a_home)
    rig.hostile(monkeypatch, None, skill="sme")
    answer = rig.take("thoronly")
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "bad_bundle"
    assert tree(rig.a_home) == before


@pytest.mark.parametrize("name,code", [("catalogued", "catalog_skill"), ("leaky", "skill_held"), ("nothere", "not_found")])
def test_the_peer_will_not_export_what_may_not_travel(rig: Rig, name: str, code: str) -> None:
    before = tree(rig.a_home)
    answer = rig.take(name)
    assert answer.json()["detail"]["code"] == code
    assert tree(rig.a_home) == before and rig.leftovers() == []
    assert rig.take("thoronly").status_code == 200


def test_alpha_will_not_write_through_a_link(rig: Rig) -> None:
    write(rig.b_home, ".claude/skills/linked/SKILL.md", "# studio's linked\n")
    elsewhere = tree(rig.tmp / "elsewhere")
    done = rig.take_through("linked")
    assert done["ok"] is False and "skill folder is a link" in " ".join(done["conflicts"])
    assert tree(rig.tmp / "elsewhere") == elsewhere and os.path.islink(rig.a_home / ".claude" / "skills" / "linked")


def test_only_the_held_alpha_is_served_by_the_peer(rig: Rig) -> None:
    rig.caller = "SOMEONE-ELSE"
    for call in (lambda: rig.b.post(f"{PEER}/export", json={"family": "claude", "name": "thoronly"}),
                 lambda: rig.b.get(f"{PEER}/export/abcdefgh12345?offset=0"), lambda: rig.b.post(f"{PEER}/export/abcdefgh12345/done")):
        answer = call()
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "not_alpha"
    rig.caller = "A"
    assert rig.b.post(f"{PEER}/export", json={"family": "claude", "name": "thoronly"}).status_code == 200
    assert rig.b.get(f"{PEER}/export/..%2F..%2Fetc%2Fpasswd?offset=0").status_code in (400, 404)


def test_a_computer_that_is_not_alpha_cannot_take(rig: Rig) -> None:
    assert rig.take().status_code == 200
    rig.alpha_id = "B"
    rig.sync.refresh_alpha()
    refused = rig.take()
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "not_alpha"


def test_an_older_peer_answers_the_update_state_with_no_call(rig: Rig, monkeypatch) -> None:
    rig.caps = OLD_PEER_CAPS
    rig.calls.clear()
    old = rig.take()
    assert old.status_code == 409 and old.json()["detail"]["code"] == "needs_update" and "older carnivore" in old.json()["detail"]["detail"]
    assert rig.calls == []
    rig.caps, rig.up = NEW_PEER_CAPS, False
    assert rig.take().json()["detail"]["code"] == "offline" and rig.calls == []
    rig.up = True
    monkeypatch.setattr(routes.direction, "contained", lambda _peer: True)
    assert rig.take().json()["detail"]["code"] == "computer_one_way" and rig.calls == []
    monkeypatch.setattr(routes.direction, "contained", lambda _peer: False)
    assert rig.take().status_code == 200
    assert take_export.CHUNK_BYTES > 0 and "pack.skills.take" in peer_routes.pack_capabilities.names()


def test_a_catalog_install_on_alpha_is_never_replaced(rig: Rig) -> None:
    write(rig.a_home, ".claude/skills/sme/.carnivore-skill.json", "{}\n")
    default = rig.a_home / ".claude"
    before = tree(default)
    done = rig.take_through("sme")
    assert done["ok"] is False and done["placed"] == 1 and len(done["conflicts"]) == 1 and "installed from warez" in done["conflicts"][0]
    assert tree(default) == before


def test_a_case_variant_folder_on_alpha_is_never_replaced(rig: Rig) -> None:
    import shutil
    shutil.rmtree(rig.a_home / ".claude" / "skills" / "sme")
    write(rig.a_home, ".claude/skills/SME/SKILL.md", "# alpha upper\n")
    before = tree(rig.a_home / ".claude")
    done = rig.take_through("sme")
    assert done["ok"] is False and done["placed"] == 1 and "case" in " ".join(done["conflicts"])
    assert tree(rig.a_home / ".claude") == before and sorted(os.listdir(rig.a_home / ".claude" / "skills")) == ["SME", "linked"]


@pytest.mark.parametrize("edit", ["edit", "catalog"])
def test_a_change_on_alpha_after_the_dry_run_refuses_the_token(rig: Rig, edit: str) -> None:
    dry = rig.take("sme").json()
    if edit == "edit":
        write(rig.a_home, ".claude/skills/sme/SKILL.md", "# alpha edited after the dry run\n")
    else:
        write(rig.a_home, ".claude/skills/sme/.carnivore-skill.json", "{}\n")
    before = tree(rig.a_home)
    stale = rig.take("sme", dry_run=False, token=dry["plan_token"])
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "plan_stale"
    assert tree(rig.a_home) == before and rig.leftovers() == []


def test_stale_exports_and_staging_are_purged_and_the_folder_is_capped(rig: Rig, monkeypatch) -> None:
    export, staging = rig.b_state / "pack" / "skills-export", rig.a_state / "skills-take"
    export.mkdir(parents=True)
    staging.mkdir(parents=True)
    old = export / "oldexport0001.tgz"
    old.write_bytes(b"x")
    stale_stage, fresh_stage = staging / "take-aaaa", staging / "take-bbbb"
    for folder in (stale_stage, fresh_stage):
        folder.mkdir()
        (folder / "f").write_text("x")
    ago = os.stat(old).st_mtime - 2 * take_export.PURGE_SECONDS
    for path in (old, stale_stage):
        os.utime(path, (ago, ago))
    take_export.purge(export)
    take_export.purge(staging)
    assert not old.exists() and not stale_stage.exists() and fresh_stage.exists()
    monkeypatch.setattr(take_export, "MAX_FOLDER_BYTES", 10)
    refused = rig.b.post(f"{PEER}/export", json={"family": "claude", "name": "thoronly"})
    assert refused.status_code == 429 and refused.json()["detail"]["code"] == "export_busy" and list(export.iterdir()) == []
    monkeypatch.undo()
