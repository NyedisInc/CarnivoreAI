
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from src.core.pack.skills import warez_alpha, warez_receiver  # noqa: E402
from src.core.pack.skills.doc import Choices, build_document  # noqa: E402
from src.core.pack.skills.receiver import ReceiverState, validate_document  # noqa: E402
from src.core.pack.skills.scan import scan_root  # noqa: E402
from src.core.pack.skills.targets import SkillRoot  # noqa: E402
from src.core.skills import auto_update, update_holds  # noqa: E402
from src.core.skills.records import read_sidecar  # noqa: E402
from tests.helpers.catalog_app import catalog_app, ledger_rows  # noqa: E402
from tests.helpers.catalog_fixture import revocation_entry, sign_item_versions  # noqa: E402
from tests.helpers.catalog_surface import (  # noqa: E402
    build_skill, fixture_trust_root, item_for, keypairs, publish_index, serve_archive,
)

CLEAN = {"status": "reviewed", "verdict": "clean", "summary": "fine.", "warnings": [], "model": "m", "reviewed_at": "2026-09-19T00:00:00Z"}
BLOCKED = {**CLEAN, "verdict": "blocked", "warnings": [{"kind": "credential_access", "detail": "reads aws credentials", "file": "SKILL.md", "line": 1}]}
COMMITS = {v: (str(i) * 40)[:40] for i, v in enumerate(["0.9.0", "1.0.0", "1.1.0", "2.0.0", "risky"], start=1)}


def tree(path: Path) -> dict:
    out = {}
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            full = Path(base) / name
            out[str(full.relative_to(path))] = ("link", os.readlink(full)) if full.is_symlink() else (
                ("dir", "") if full.is_dir() else ("file", hashlib.sha256(full.read_bytes()).hexdigest()))
    return out


def entry(pkg, item_id: str, version: str, family: str = "claude") -> list:
    return [family, item_id.split("/")[1], item_id, "skill", version, pkg.digest, hashlib.sha256(b"b").hexdigest()]


def publish(tmp_path: Path, served: Path):
    index_kp, publisher_kp, _ = keypairs(tmp_path / "keys")
    pkgs, versions = {}, []
    for v in ("0.9.0", "1.0.0", "1.1.0", "2.0.0"):
        pkgs[v] = build_skill(tmp_path, publisher="alex", name="sme", label=v, files={"SKILL.md": f"# sme {v}\n".encode()})
        serve_archive(served, pkgs[v].tar_bytes, commit=COMMITS[v])
        versions.append(item_for(pkgs[v], publisher="alex", name="sme", commit=COMMITS[v], version=v)["versions"][0])
    sme = item_for(pkgs["2.0.0"], publisher="alex", name="sme", commit=COMMITS["2.0.0"], version="2.0.0")
    sme["versions"] = versions
    for v in sme["versions"]:
        v["review"] = CLEAN
    sign_item_versions(tmp_path, sme, publisher_kp)
    next(v for v in sme["versions"] if v["v"] == "1.1.0")["src"]["commit"] = "f" * 40
    pkgs["risky"] = build_skill(tmp_path, publisher="alex", name="risky", label="risky", files={"SKILL.md": b"# risky\n"})
    serve_archive(served, pkgs["risky"].tar_bytes, commit=COMMITS["risky"])
    risky = item_for(pkgs["risky"], publisher="alex", name="risky", commit=COMMITS["risky"], version="1.0.0")
    risky["versions"][0]["review"] = BLOCKED
    sign_item_versions(tmp_path, risky, publisher_kp)
    revoked = revocation_entry(tmp_path, kind="version", subject="alex/sme@0.9.0", since="2026-09-10T00:00:00+00:00", keypair=publisher_kp)
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[sme, risky], serial=1,
                  revocations={"keys": [], "versions": [revoked]})
    return fixture_trust_root(index_kp, publisher_kp), pkgs


def test_alpha_sends_catalog_folders_as_references_only(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    for name, text in (("mine", "# mine\n"), ("cat", "# cat\n"), ("edited", "# edited\n"), ("orphan", "# o\n"), ("partial", "# p\n")):
        (root / name).mkdir(parents=True)
        (root / name / "SKILL.md").write_text(text)
    for name in ("cat", "edited", "orphan", "partial"):
        (root / name / ".carnivore-skill.json").write_text("{}")
    from src.core.skill_watch.sentinel import measure_folder

    def row(name, digest, body="b" * 64):
        return SimpleNamespace(install_id=f"i-{name}", item_id=f"alex/{name}", kind="skill", name=name, version="1.0.0", digest=digest,
                               scope="global", consented_body_sha=body)

    rows = [row("cat", measure_folder(root / "cat")[0]), row("edited", "0" * 64), row("partial", measure_folder(root / "partial")[0], None)]

    class Ledger:
        def forked_ids(self): return frozenset()
        def list(self): return rows
        def targets(self, install_id): return [SimpleNamespace(harness="claude", path=str(root / install_id[2:]))]

    class Ctx:
        def __enter__(self): return Ledger()
        def __exit__(self, *a): return False

    services = SimpleNamespace(catalog=SimpleNamespace(ledger=lambda: Ctx()))
    plan = warez_alpha.plan(services, {"claude": root})
    doc = build_document(alpha="A", gen=1, made_at=1, choices=Choices(mode="all"), scans={"claude": scan_root(root, "claude")},
                         warez=plan.entries, catalog_held=plan.held, catalog_pairs=plan.pairs).document
    assert [s[1] for s in doc["skills"]] == ["mine"]
    assert [(w[1], w[2], w[4]) for w in doc["warez"]] == [("cat", "alex/cat", "1.0.0")]
    assert {(h[1], h[2]) for h in doc["held"]} == {("edited", warez_alpha.REASON_EDITED), ("orphan", warez_alpha.REASON_NO_RECORD),
                                                  ("partial", warez_alpha.REASON_INCOMPLETE)}


def test_receiver_installs_the_same_item_and_version_from_its_own_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    served = tmp_path / "served"
    served.mkdir()
    trust, pkgs = publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        home = app.roots.home
        relay = tmp_path / "relay"
        (relay).mkdir()
        roots = [SkillRoot("claude", home / ".claude" / "skills", home / ".claude", home / ".claude" / ".carnivore-trash"),
                 SkillRoot("claude", relay / "skills", relay, home / ".claude" / ".carnivore-trash")]
        state = ReceiverState(tmp_path / "pack" / "skills-state.json")
        monkeypatch.setattr(update_holds, "_state_path", lambda: state.path)
        loop = app.client.portal.call(asyncio.get_running_loop)
        gen = [0]

        def apply(rows, *, install=True):
            gen[0] += 1
            doc = validate_document({"v": 1, "alpha": "A", "gen": gen[0], "skills": [], "warez": rows}, "A")
            saved = state.load()
            saved["doc"], saved["applied_gen"] = doc, gen[0]
            state.save(saved)
            ctx = warez_receiver.Context(state, roots, app.services, loop, "A", gen[0], lambda: True)
            warez_receiver.run(doc, ctx, [[r[0], r[1]] for r in rows] if install else None)
            return doc

        def code(item):
            return state.load()["refs"][item]["code"]

        apply([entry(pkgs["1.0.0"], "alex/sme", "1.0.0")])
        installed = home / ".claude" / "skills" / "sme"
        assert read_sidecar(installed).version == "1.0.0"
        assert read_sidecar(relay / "skills" / "sme").version == "1.0.0"
        row = [r for r in ledger_rows(app) if r.item_id == "alex/sme"][0]
        assert (row.version, row.consent_via) == ("1.0.0", "pack")
        assert not (home / ".agents" / "skills" / "sme").exists()
        assert state.load()["ref_hold"] is True and update_holds.held("alex/sme")
        assert "alex/sme" not in {r.item_id for r in auto_update.candidate_rows(app.services)}

        before = (tree(home), tree(relay), ledger_rows(app))
        for version, expect in (("0.9.0", "version_revoked"), ("1.1.0", "signature_failed")):
            apply([entry(pkgs[version], "alex/sme", version)])
            assert code("alex/sme") == expect
        apply([["claude", "sme", "alex/sme", "skill", "1.0.0", "e" * 64, "b" * 64]])
        assert code("alex/sme") == "digest_differs"
        apply([entry(pkgs["risky"], "alex/risky", "1.0.0")])
        assert code("alex/risky") == "review_not_clean"
        apply([["claude", "sme", "alex/sme", "skill", "not-a-version", pkgs["1.0.0"].digest, "b" * 64]])
        assert code("alex/sme") == "bad_entry"
        assert (tree(home), tree(relay), ledger_rows(app)) == before

        apply([entry(pkgs["2.0.0"], "alex/sme", "2.0.0")])
        assert read_sidecar(installed).version == "2.0.0" and read_sidecar(relay / "skills" / "sme").version == "2.0.0"
        apply([entry(pkgs["1.0.0"], "alex/sme", "1.0.0")])
        assert read_sidecar(installed).version == "1.0.0"
        assert not list((home / ".claude" / ".carnivore-trash").glob("sme-*"))
        seen = len(app.server.seen())
        before = (tree(home), tree(relay), ledger_rows(app))
        apply([entry(pkgs["2.0.0"], "alex/sme", "2.0.0")], install=False)
        apply([])
        assert len(app.server.seen()) == seen and (tree(home), tree(relay), ledger_rows(app)) == before
        warez_receiver.clear_hold(state)
        assert not update_holds.held("alex/sme")
