
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_skills_routes as routes  # noqa: E402
from src.api.peer_auth import Principal  # noqa: E402
from src.core.federation.grants import Grant  # noqa: E402
from src.core.live_install_roots import LiveInstallRoots  # noqa: E402
from src.core.pack.skills.bundle import build_bundle  # noqa: E402
from src.core.pack.skills.doc import Choices, build_document  # noqa: E402
from src.core.pack.skills.scan import scan_root  # noqa: E402
from src.core.pack.skills.targets import receiver_roots  # noqa: E402
from src.core.pack.transport import blobs  # noqa: E402

BASE = "/api/v1/federation/pack/skills"


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
                out[rel] = ("file", hashlib.sha256(full.read_bytes()).hexdigest())
    return out


def write(root: Path, rel: str, text: str = "x\n", mode: int = 0o644) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)


class Rig:

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.tmp, self.home = tmp, tmp / "home"
        self.alpha = tmp / "alpha"
        self.state = tmp / "state"
        write(self.alpha, ".claude/skills/sme/SKILL.md", "# sme from alpha\n")
        write(self.alpha, ".claude/skills/sme/scripts/run.sh", "#!/bin/sh\n", 0o755)
        write(self.alpha, ".agents/skills/cx/SKILL.md", "# cx\n")
        write(self.home, ".claude/skills/sme/SKILL.md", "# my own edit\n")
        write(self.home, ".claude/skills/sme/node_modules/pkg/i.js", "built here\n")
        write(self.home, ".claude/skills/localonly/SKILL.md", "# mine\n")
        write(self.home, ".claude/skills/synced/SKILL.md", "claude's own\n")
        accounts = self.home / ".carnivore" / "accounts"
        (accounts / "abcdef012345-work-relay").mkdir(parents=True)
        write(accounts, "nyedis/auth.json", "{}\n")
        (accounts / "claude-evergreen").mkdir()
        os.symlink(self.home / ".claude" / "skills", accounts / "claude-evergreen" / "skills")
        write(self.tmp, "elsewhere/keep.md", "not ours\n")
        (accounts / "linkacct").mkdir()
        os.symlink(self.tmp / "elsewhere", accounts / "linkacct" / "skills")
        self.dirs = [str(accounts / "claude-evergreen"), str(accounts / "linkacct")]
        self.caller = "ALPHA"
        monkeypatch.setattr(routes, "state_dir", lambda: self.state)
        monkeypatch.setattr(routes, "roots_now", lambda: receiver_roots(self.home, accounts, self.dirs))
        monkeypatch.setattr(routes, "held_alpha", lambda: "ALPHA")
        monkeypatch.setattr(routes.direction, "contained", lambda _peer: False)
        routes._STATES.clear()
        routes._HITS.clear()
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/api/v1")
        self.app.dependency_overrides[routes._require_skills] = self.principal
        self.client = TestClient(self.app)

    def principal(self) -> Principal:
        grant = Grant("g1", self.caller, "k", "f", "alpha", ("skills",), None, "t", None, None)
        return Principal("peer", grant)

    def document(self, gen: int, mode: str = "all") -> dict:
        scans = {"claude": scan_root(self.alpha / ".claude" / "skills", "claude"),
                 "codex": scan_root(self.alpha / ".agents" / "skills", "codex")}
        return build_document(alpha="ALPHA", gen=gen, made_at=1000, choices=Choices(mode=mode), scans=scans).document

    def bundle(self, pairs) -> Path:
        out = self.tmp / f"b{len(list(self.tmp.glob('b*.tgz')))}.tgz"
        items = []
        for family, name in pairs:
            root = self.alpha / (".claude" if family == "claude" else ".agents") / "skills"
            items.append((family, name, root / name, scan_root(root, family).skills[name].files))
        build_bundle(out, items)
        return out

    def hostile(self, member: tarfile.TarInfo, data: bytes = b"") -> Path:
        scan = scan_root(self.alpha / ".claude" / "skills", "claude").skills["sme"]
        listing = {"v": 1, "skills": {"claude/sme": [{"path": f.path, "size": f.size, "mode": f.mode, "sha256": f.sha256} for f in scan.files]}}
        out = self.tmp / "hostile.tgz"
        with tarfile.open(out, "w:gz") as tar:
            raw = json.dumps(listing).encode()
            info = tarfile.TarInfo("files.json")
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
            for f in scan.files:
                body = (self.alpha / ".claude" / "skills" / "sme" / f.path).read_bytes()
                info = tarfile.TarInfo(f"claude/sme/{f.path}")
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
        return out

    def upload(self, path: Path) -> tuple[str, str]:
        blob_id, data = blobs.new_id(), path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        put = self.client.put(f"{BASE}/blobs/{blob_id}?offset=0", content=data, headers={"X-Chunk-Sha256": sha})
        assert put.status_code == 200, put.text
        seal = self.client.post(f"{BASE}/blobs/{blob_id}/seal", json={"size": len(data), "sha256": sha, "kind": "tar"})
        assert seal.status_code == 200, seal.text
        return blob_id, sha

    def deliver(self, doc: dict, bundle: Path | None = None) -> dict:
        offer = self.client.post(f"{BASE}/offer", json=doc)
        assert offer.status_code == 200, offer.text
        body = {"gen": doc["gen"], "blob_id": None, "blob_sha256": None}
        if bundle is not None:
            body["blob_id"], body["blob_sha256"] = self.upload(bundle)
        apply = self.client.post(f"{BASE}/apply", json=body)
        assert apply.status_code == 202, apply.text
        assert routes.WORKER.join(30)
        return offer.json()

    def leftovers(self) -> list[str]:
        found = [p.name for p in (self.state / "pack").glob("skills-stage-*")] if (self.state / "pack").exists() else []
        inbox = self.state / "pack" / "skills-inbox"
        return found + ([p.name for p in inbox.iterdir()] if inbox.exists() else [])


@pytest.fixture()
def rig(tmp_path, monkeypatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


def test_only_the_held_alpha_may_send(rig: Rig, monkeypatch) -> None:
    doc = rig.document(1)
    rig.caller = "SOMEONE-ELSE"
    for call in (lambda: rig.client.post(f"{BASE}/offer", json=doc), lambda: rig.client.post(f"{BASE}/apply", json={"gen": 1}),
                 lambda: rig.client.get(f"{BASE}/inventory"), lambda: rig.client.get(f"{BASE}/blobs/b-0123456789ab"),
                 lambda: rig.client.put(f"{BASE}/blobs/b-0123456789ab?offset=0", content=b"x", headers={"X-Chunk-Sha256": "0" * 64})):
        answer = call()
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "not_alpha"
        assert answer.json()["detail"]["held_alpha"] == "ALPHA"
    rig.caller = "ALPHA"
    monkeypatch.setattr(routes.direction, "contained", lambda _peer: True)
    refused = rig.client.post(f"{BASE}/offer", json=doc)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "alpha_one_way"
    monkeypatch.setattr(routes.direction, "contained", lambda _peer: False)
    assert rig.client.post(f"{BASE}/offer", json=doc).status_code == 200


def test_a_lower_generation_is_refused_with_the_receivers_gen(rig: Rig) -> None:
    rig.deliver(rig.document(5), rig.bundle([("claude", "sme"), ("codex", "cx")]))
    stale = rig.client.post(f"{BASE}/offer", json=rig.document(4))
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale" and stale.json()["applied_gen"] == 5
    assert rig.client.post(f"{BASE}/offer", json=rig.document(5)).status_code == 200


@pytest.mark.parametrize("name,kind,link", [("claude/sme/../../x", tarfile.REGTYPE, ""), ("/abs/evil", tarfile.REGTYPE, ""),
                                            ("claude/sme/a\0b", tarfile.REGTYPE, ""), ("claude/sme/link", tarfile.SYMTYPE, "/etc/hosts")])
def test_hostile_bundles_change_nothing(rig: Rig, name: str, kind: bytes, link: str) -> None:
    before = {p: tree(p) for p in (rig.home, rig.tmp / "elsewhere")}
    member = tarfile.TarInfo(name)
    member.type, member.linkname = kind, link
    rig.deliver(rig.document(1), rig.hostile(member, b"evil" if kind == tarfile.REGTYPE else b""))
    assert {p: tree(p) for p in before} == before
    assert rig.leftovers() == []
    assert not (rig.tmp / "x").exists()


def test_a_valid_apply_replaces_keeps_machine_local_and_stays_inside_its_roots(rig: Rig) -> None:
    accounts = rig.home / ".carnivore" / "accounts"
    codex_home, elsewhere = tree(accounts / "nyedis"), tree(rig.tmp / "elsewhere")
    offer = rig.deliver(rig.document(1), rig.bundle([("claude", "sme"), ("codex", "cx")]))
    assert offer["need"] == [["claude", "sme"], ["codex", "cx"]]

    default = rig.home / ".claude" / "skills" / "sme"
    relay = accounts / "abcdef012345-work-relay" / "skills" / "sme"
    for live in (default, relay):
        assert (live / "SKILL.md").read_text() == "# sme from alpha\n"
        assert os.access(live / "scripts" / "run.sh", os.X_OK)
    assert (default / "node_modules" / "pkg" / "i.js").read_text() == "built here\n"
    assert not (relay / "node_modules").exists()
    assert (rig.home / ".agents" / "skills" / "cx" / "SKILL.md").read_text() == "# cx\n"
    assert (rig.home / ".claude" / "skills" / "localonly" / "SKILL.md").read_text() == "# mine\n"
    assert (rig.home / ".claude" / "skills" / "synced" / "SKILL.md").read_text() == "claude's own\n"
    assert tree(accounts / "nyedis") == codex_home
    assert not (accounts / "nyedis" / "skills").exists() and not (accounts / "nyedis" / ".claude.json").exists()
    assert tree(rig.tmp / "elsewhere") == elsewhere
    assert os.readlink(accounts / "linkacct" / "skills") == str(rig.tmp / "elsewhere")

    trash = rig.home / ".claude" / ".carnivore-trash"
    sweeper_trash = LiveInstallRoots(settings_reader=SimpleNamespace()).trash_dir("claude", "global", None)
    assert trash.relative_to(rig.home) == sweeper_trash.relative_to(Path.home())
    kept = [p for p in trash.iterdir() if p.name.startswith("sme-")]
    assert len(kept) == 1 and (kept[0] / "SKILL.md").read_text() == "# my own edit\n"

    rows = json.loads((rig.state / "pack" / "skills-state.json").read_text())
    states = {(r["family"], r["name"], r["root"]): r["state"] for r in rows["applied"]}
    assert rows["applied_gen"] == 1
    assert states[("claude", "sme", str(rig.home / ".claude" / "skills"))] == "in sync"
    assert any(r["state"] == "conflict" and r["reason"] == "skills folder is a link" for r in rows["applied"])
    assert rig.leftovers() == []

    write(rig.alpha, ".claude/skills/sme/SKILL.md", "# sme, second edit\n")
    rig.deliver(rig.document(2), rig.bundle([("claude", "sme")]))
    assert (default / "SKILL.md").read_text() == "# sme, second edit\n"
    assert [p.name for p in trash.iterdir() if p.name.startswith("sme-")] == [p.name for p in kept]
    assert rig.leftovers() == []


def test_calls_are_rate_limited_per_grant(rig: Rig) -> None:
    doc = rig.document(1)
    answers = [rig.client.post(f"{BASE}/offer", json=doc).status_code for _ in range(routes.RATE_PER_MINUTE + 1)]
    assert answers[:routes.RATE_PER_MINUTE] == [200] * routes.RATE_PER_MINUTE and answers[-1] == 429
