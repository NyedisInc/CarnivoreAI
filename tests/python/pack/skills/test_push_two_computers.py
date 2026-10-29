
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_skills_routes as routes  # noqa: E402
from src.api.peer_auth import Principal  # noqa: E402
from src.core.federation.grants import Grant  # noqa: E402
from src.core.federation.peer_client import PeerUnreachable  # noqa: E402
from src.core.pack.skills.doc import Choices  # noqa: E402
from src.core.pack.skills.runtime import PeerView, SkillsSync  # noqa: E402
from src.core.pack.skills.scan import scan_root  # noqa: E402
from src.core.pack.skills.targets import receiver_roots  # noqa: E402

BASE = "/api/v1"


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


class MemChoices:

    def __init__(self, choices: Choices = Choices()) -> None:
        self.value = choices

    def read(self) -> Choices:
        return self.value

    def write(self, choices: Choices) -> None:
        self.value = choices


class Cluster:

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.tmp, self.mp = tmp, monkeypatch
        self.alpha: dict[str, str] = {}
        self.offline: set[str] = set()
        self.caller = ""
        self.target = ""
        self.homes: dict[str, Path] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.applies_with_blob: list[tuple[str, str]] = []
        monkeypatch.setattr(routes, "RATE_PER_MINUTE", 100000)
        monkeypatch.setattr(routes.direction, "contained", lambda _peer: False)
        routes._STATES.clear()
        routes._HITS.clear()
        app = FastAPI()
        app.include_router(routes.router, prefix=BASE)
        app.dependency_overrides[routes._require_skills] = lambda: Principal(
            "peer", Grant("g1", self.caller, "k", "f", "x", ("skills",), None, "t", None, None))
        self.client = TestClient(app)
        monkeypatch.setattr(routes, "state_dir", lambda: self.tmp / self.target / "state")
        monkeypatch.setattr(routes, "roots_now", lambda: self.roots(self.target))
        monkeypatch.setattr(routes, "held_alpha", lambda: self.alpha[self.target])

    def roots(self, name: str):
        home = self.homes[name]
        return receiver_roots(home, home / ".carnivore" / "accounts", [])

    @contextmanager
    def active(self, name: str, caller: str):
        before = (self.target, self.caller)
        self.target, self.caller = name, caller
        try:
            yield
        finally:
            self.target, self.caller = before

    def add(self, name: str, relay: bool = True) -> "Computer":
        self.homes[name] = self.tmp / name / "home"
        self.alpha[name] = name
        (self.homes[name] / ".carnivore" / "accounts").mkdir(parents=True)
        if relay:
            (self.homes[name] / ".carnivore" / "accounts" / "abcdef012345-work-relay").mkdir()
        return Computer(self, name)


class Computer:
    def __init__(self, cluster: Cluster, name: str) -> None:
        self.cluster, self.name, self.home = cluster, name, cluster.homes[name]
        with cluster.active(name, name):
            state = routes.receiver_state()
        self.choices = MemChoices()
        self.others: dict[str, "Computer"] = {}
        self.sync = SkillsSync(
            install_id=name, state=state, alpha_id=lambda: cluster.alpha[name], choices=self.choices,
            family_roots=lambda: {"claude": self.home / ".claude" / "skills", "codex": self.home / ".agents" / "skills"},
            receiver_roots=lambda: cluster.roots(name), peers=self.views, request_for=self.request_for, notify=lambda: None,
            outbox=cluster.tmp / name / "outbox")

    @property
    def skills(self) -> Path:
        return self.home / ".claude" / "skills"

    def snapshot(self) -> dict:
        block = self.sync.skills_block()
        snap = {"label": self.name, "capabilities": ["pack.skills"]}
        if block:
            snap["skills"] = block
        return snap

    def views(self):
        return [PeerView(n, n, n not in self.cluster.offline, c.snapshot()) for n, c in self.others.items()]

    def request_for(self, peer: str):
        async def request(method, path, *, content=None, headers=None, json=None):
            if peer in self.cluster.offline:
                raise PeerUnreachable("link is down")
            self.cluster.calls.append((self.name, peer, path))
            with self.cluster.active(peer, self.name):
                kw = {k: v for k, v in (("json", json), ("content", content)) if v is not None}
                reply = self.cluster.client.request(method, BASE + path, headers=headers, **kw)
                if path.endswith("/apply"):
                    if json and json.get("blob_id"):
                        self.cluster.applies_with_blob.append((self.name, peer))
                    assert routes.WORKER.join(30)
            try:
                return reply.status_code, reply.json()
            except ValueError:
                return reply.status_code, None
        return request

    def beat(self, peer: str) -> bool:
        return self.sync.seen(peer, self.others[peer].snapshot())

    def pump(self, peer: str) -> str:
        outcome = "none"
        if self.beat(peer):
            outcome = asyncio.run(self.sync.deliver_pass(peer))
        self.beat(peer)
        return outcome


@pytest.fixture()
def pair(tmp_path, monkeypatch):
    cluster = Cluster(tmp_path, monkeypatch)
    a, b = cluster.add("A", relay=False), cluster.add("B")
    a.others, b.others = {"B": b}, {"A": a}
    cluster.alpha.update(A="A", B="A")
    write(a.home, ".claude/skills/sme/SKILL.md", "# sme v1\n")
    write(a.home, ".claude/skills/sme/scripts/run.sh", "#!/bin/sh\n", 0o755)
    write(a.home, ".claude/skills/other/SKILL.md", "# not chosen\n")
    write(b.home, ".claude/skills/sme/SKILL.md", "# b's own sme\n")
    write(b.home, ".claude/skills/sme/node_modules/pkg/i.js", "built on b\n")
    write(b.home, ".claude/skills/bonly/SKILL.md", "# only on b\n")
    a.choices.write(Choices(mode="some", include=frozenset({("claude", "sme")})))
    return cluster, a, b


def set_alpha(cluster: Cluster, a: Computer, b: Computer, who: str) -> None:
    cluster.alpha.update(A=who, B=who)
    a.sync.refresh_alpha()
    b.sync.refresh_alpha()


def save_by_rename(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def test_choice_edit_and_receiver_drift_follow_alpha_and_stop_at_three(pair) -> None:
    cluster, a, b = pair
    assert b.sync.skills_block() is None
    published = a.sync.publish_pass()
    assert (published.outcome, published.gen) == ("published", 1)
    assert a.sync.publish_pass().outcome == "unchanged"
    assert a.pump("B") == "synced"
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# sme v1\n"
    assert (b.skills / "sme" / "node_modules" / "pkg" / "i.js").read_text() == "built on b\n"
    assert (b.skills / "bonly" / "SKILL.md").exists() and not (b.skills / "other").exists()
    assert os.access(b.skills / "sme" / "scripts" / "run.sh", os.X_OK)
    doc = a.sync.published()
    got = b.sync.state.load()
    assert got["applied_gen"] == 1 and got["doc"]["skills"] == doc["skills"]
    assert b.sync.skills_block()["applied_gen"] == 1 and b.sync.skills_block()["off_count"] == 0
    assert a.pump("B") == "none"
    save_by_rename(a.skills / "sme" / "SKILL.md", "# sme v2\n")
    assert a.sync.publish_pass().gen == 2
    assert a.pump("B") == "synced"
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# sme v2\n"
    (b.skills / "sme" / "SKILL.md").write_text("# edited on b\n")
    assert b.sync.skills_block()["off_count"] == 0
    b.sync.check_pass()
    assert b.sync.skills_block()["off_count"] == 1
    assert a.pump("B") == "synced"
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# sme v2\n"
    kept = sorted(p.read_text() for p in b.home.glob(".claude/.carnivore-trash/sme-*/SKILL.md"))
    assert kept == ["# b's own sme\n", "# edited on b\n"]
    before = len(cluster.applies_with_blob)
    for attempt in range(6):
        (b.skills / "sme" / "SKILL.md").write_text(f"# rewritten {attempt}\n")
        b.sync.check_pass()
        a.pump("B")
    assert len(cluster.applies_with_blob) - before == 1
    row = a.sync.status()["peers"]["B"]
    assert row["conflicts"] == [["claude", "sme", "keeps changing on B"]]
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# rewritten 5\n"
    assert b.sync.skills_block()["off_count"] == 0
    a.sync.reset_caps()
    asyncio.run(a.sync.deliver_all())
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# sme v2\n"


def test_deleting_the_folder_on_alpha_removes_nothing_anywhere(pair) -> None:
    cluster, a, b = pair
    a.sync.publish_pass()
    assert a.pump("B") == "synced"
    trash = b.home / ".claude" / ".carnivore-trash"
    assert trash.exists()
    before = (tree(b.home), tree(trash))
    shutil.rmtree(a.skills / "sme")
    gone = a.sync.publish_pass()
    assert gone.outcome == "published"
    doc = a.sync.published()
    assert doc["skills"] == [] and doc["removals"] == [] and ["claude", "sme", "missing on alpha"] in doc["held"]
    a.pump("B")
    assert (tree(b.home), tree(trash)) == before
    assert (b.skills / "sme" / "SKILL.md").exists()


def test_a_receiver_that_is_behind_or_differs_becomes_alpha_and_holds(pair) -> None:
    cluster, a, b = pair
    a.sync.publish_pass()
    assert a.pump("B") == "synced"
    save_by_rename(a.skills / "sme" / "SKILL.md", "# sme v2\n")
    a.sync.publish_pass()
    b.sync.check_pass()
    set_alpha(cluster, a, b, "B")
    calls = len(cluster.calls)
    held = b.sync.publish_pass()
    assert held.outcome == "hold" and b.sync.published() is None
    assert b.sync.status()["hold"] == {"differs": 0, "behind": True}
    assert b.beat("A") is False and len(cluster.calls) == calls
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# sme v1\n"
    set_alpha(cluster, a, b, "A")
    assert a.pump("B") == "synced"
    (b.skills / "sme" / "SKILL.md").write_text("# edited on b\n")
    set_alpha(cluster, a, b, "B")
    differs = b.sync.publish_pass()
    assert differs.outcome == "hold" and b.sync.status()["hold"] == {"differs": 1, "behind": False}
    (b.skills / "sme" / "SKILL.md").write_text("# sme v2\n")
    done = b.sync.publish_pass()
    assert (done.outcome, done.gen) == ("published", 3)
    assert b.choices.read().mode == "some"
    assert b.sync.status()["hold"] is None
    keep = (tree(a.home), tree(b.home))
    assert asyncio.run(b.sync.deliver_pass("A")) == "synced"
    assert (tree(a.home), tree(b.home)) == keep
    assert a.sync.state.load()["applied_gen"] == 3


def test_an_offline_receiver_catches_up_on_connect_and_a_stale_answer_does_not_wedge(pair) -> None:
    cluster, a, b = pair
    cluster.offline.add("B")
    a.sync.publish_pass()
    assert asyncio.run(a.sync.deliver_pass("B")) == "failed"
    assert a.sync.status()["peers"]["B"]["state"] == "offline"
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# b's own sme\n"
    cluster.offline.discard("B")
    asyncio.run(a.sync.on_connect("B"))
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# sme v1\n"
    state = b.sync.state.load()
    state["applied_gen"] = 7
    b.sync.state.save(state)
    save_by_rename(a.skills / "sme" / "SKILL.md", "# sme v2\n")
    assert a.sync.publish_pass().gen == 8
    state["applied_gen"] = 11
    b.sync.state.save(state)
    b.sync.check_pass()
    assert asyncio.run(a.sync.deliver_pass("B")) == "synced"
    assert a.sync.published()["gen"] == 12 and b.sync.state.load()["applied_gen"] == 12
    assert (b.skills / "sme" / "SKILL.md").read_text() == "# sme v2\n"


def test_a_catalog_installed_copy_on_a_receiver_is_a_conflict_alpha_never_calls_in_sync(pair) -> None:
    from src.core.pack.skills import owner
    from src.core.skills.records import SIDECAR_NAME

    cluster, a, b = pair
    write(b.home, ".claude/skills/sme/" + SIDECAR_NAME, "{}")
    before = tree(b.skills / "sme")
    assert a.sync.publish_pass().outcome == "published"
    a.pump("B")
    assert tree(b.skills / "sme") == before
    b.sync.check_pass()
    a.beat("B")
    peer = a.sync.status()["peers"]["B"]
    assert peer["state"] != "in sync"
    inventories = asyncio.run(owner.fetch_inventories(a.sync.peer_views(), a.sync.request_to))
    scans = {f: scan_root(r, f) for f, r in a.sync.roots().items()}
    mx = owner.matrix(a.sync, a.choices.read(), scans, inventories, "A")
    cells = {(r["family"], r["name"]): r["cells"]["B"] for r in mx["rows"]}
    assert cells[("claude", "sme")] == "conflict"
