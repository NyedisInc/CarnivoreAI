from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401,E402
from src.core.app_alerts import service  # noqa: E402
from src.core.db import db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.pack.skills import alerts, owner, warez_receiver  # noqa: E402
from src.core.pack.skills.receiver import ReceiverState, validate_document  # noqa: E402
from src.core.pack.skills.runtime import SkillsSync  # noqa: E402
from src.core.pack.skills.targets import SkillRoot  # noqa: E402
from src.core.skills import update_holds  # noqa: E402
from tests.helpers.catalog_app import catalog_app, ledger_rows  # noqa: E402
from tests.helpers.catalog_fixture import sign_item_versions  # noqa: E402
from tests.helpers.catalog_surface import build_skill, fixture_trust_root, item_for, keypairs, publish_index, serve_archive  # noqa: E402

CLEAN = {"status": "reviewed", "verdict": "clean", "summary": "fine.", "warnings": [], "model": "m", "reviewed_at": "2026-09-19T00:00:00Z"}
D = "a" * 64


@pytest.fixture()
def alertdb(tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    assert ensure_db_migrated(sd).status == "ok"
    service.configure(db_path_for(sd), None)
    alerts.configure(alerts.Seams("ME", lambda: ("A", "A", 0), lambda i: {"X": "ripley", "A": "nostromo"}.get(i, ""), lambda i: False))
    yield
    alerts.configure(None)
    service.configure(None, None)


def open_rows(prefix):
    found = service.list_view(Path(service._db_path), include_closed=True, limit=200)["alerts"]
    return [r for r in found if r["key"].startswith(prefix)]


def test_A_trash_placed_keeps_a_warez_row_it_did_not_remove(tmp_path, alertdb):
    leaf = tmp_path / "home" / ".claude" / "skills"
    (leaf / "sme").mkdir(parents=True)
    (leaf / "sme" / "SKILL.md").write_text("# sme\n")
    (leaf / "sme" / ".carnivore-skill.json").write_text("{}")
    root = SkillRoot("claude", leaf, tmp_path / "home" / ".claude", tmp_path / "home" / ".claude" / ".carnivore-trash")
    state = ReceiverState(tmp_path / "s.json")
    data = state.load()
    data["applied"] = [{"family": "claude", "name": "sme", "root": str(leaf), "alpha": "X", "gen": 1, "digest": D, "state": "in sync",
                        "reason": "", "placed": True, "item": "alex/sme", "version": "1.0.0"}]
    state.save(data)
    alerts.check_placers(state)
    assert len([r for r in open_rows("pack_skills.placer_gone:X") if not r.get("resolved_at")]) == 1
    trashed = owner.trash_placed(state, "X", [root])
    alerts.check_placers(state)
    assert trashed == []
    assert (leaf / "sme" / "SKILL.md").exists()
    assert len(state.load()["applied"]) == 1
    assert len([r for r in open_rows("pack_skills.placer_gone:X") if not r.get("resolved_at")]) == 1


def test_B_hold_ends_on_an_alpha_change(tmp_path, monkeypatch):
    state = ReceiverState(tmp_path / "pack" / "skills-state.json")
    monkeypatch.setattr(update_holds, "_state_path", lambda: state.path)
    data = state.load()
    data["doc"] = {"v": 1, "alpha": "A", "gen": 1, "skills": [], "warez": [["claude", "sme", "alex/sme", "skill", "1.0.0", D, D]],
                   "removals": [], "unsynced": [], "held": []}
    data["ref_hold"] = True
    state.save(data)
    sync = SkillsSync(install_id="ME", state=state, alpha_id=lambda: "B", choices=None, family_roots=lambda: {}, receiver_roots=lambda: [],
                      peers=lambda: [], request_for=lambda _p: None, notify=lambda: None, outbox=tmp_path / "out", services=lambda: object())
    sync._loop = asyncio.new_event_loop()
    sync.refresh_alpha()
    sync.retry_refs()
    assert state.load()["ref_hold"] is False and not update_holds.held("alex/sme")
    sync.retry_refs()
    assert state.load()["ref_hold"] is False
    sync._loop.close()


def test_C_hold_covers_only_what_was_installed(tmp_path, monkeypatch):
    state = ReceiverState(tmp_path / "pack" / "skills-state.json")
    monkeypatch.setattr(update_holds, "_state_path", lambda: state.path)
    data = state.load()
    data["doc"] = {"alpha": "A", "warez": [["claude", "x", "alex/anything", "skill", "not-a-version", "z", "z"]]}
    data["ref_hold"] = True
    state.save(data)
    assert not update_holds.held("alex/anything")
    data["refs"] = {"alex/anything": {"outcome": "in sync", "version": "not-a-version"}}
    state.save(data)
    assert update_holds.held("alex/anything")


def test_D_malformed_install_pair_is_refused_by_the_body_model(tmp_path):
    state = ReceiverState(tmp_path / "s.json")
    doc = validate_document({"v": 1, "alpha": "A", "gen": 1, "skills": [], "warez": [["claude", "sme", "alex/sme", "skill", "1.0.0", D, D]]}, "A")
    from pydantic import ValidationError
    from src.api.federation_pack_skills_routes import ApplyBody

    with pytest.raises(ValidationError):
        ApplyBody(gen=1, install=[["claude", "sme", "extra"]])
    assert ApplyBody(gen=1, install=[["claude", "sme"]]).install == [["claude", "sme"]]


def _publish(tmp_path, served):
    index_kp, publisher_kp, _ = keypairs(tmp_path / "keys")
    pkg = build_skill(tmp_path, publisher="alex", name="sme", label="1", files={"SKILL.md": b"# sme 1\n"})
    serve_archive(served, pkg.tar_bytes, commit="1" * 40)
    sme = item_for(pkg, publisher="alex", name="sme", commit="1" * 40, version="1.0.0")
    sme["versions"][0]["review"] = CLEAN
    sign_item_versions(tmp_path, sme, publisher_kp)
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[sme], serial=1)
    return fixture_trust_root(index_kp, publisher_kp), pkg


@pytest.mark.parametrize("fail", [False, True])
def test_E_handmade_displaced_is_reported_even_when_install_fails(tmp_path, monkeypatch, alertdb, fail):
    served = tmp_path / "served"
    served.mkdir()
    trust, pkg = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        home = app.roots.home
        leaf = home / ".claude" / "skills"
        (leaf / "sme").mkdir(parents=True)
        (leaf / "sme" / "SKILL.md").write_text("# my own private sme\n")
        if fail:
            from src.core.skills import installer

            def boom(*a, **k):
                raise OSError(28, "disk full")
            monkeypatch.setattr(installer, "copy_tree", boom)
        roots = [SkillRoot("claude", leaf, home / ".claude", home / ".claude" / ".carnivore-trash")]
        state = ReceiverState(tmp_path / "pack" / "skills-state.json")
        loop = app.client.portal.call(asyncio.get_running_loop)
        row = ["claude", "sme", "alex/sme", "skill", "1.0.0", pkg.digest, hashlib.sha256(b"b").hexdigest()]
        doc = validate_document({"v": 1, "alpha": "X", "gen": 1, "skills": [], "warez": [row]}, "X")
        ctx = warez_receiver.Context(state, roots, app.services, loop, "X", 1, lambda: True)
        warez_receiver.run(doc, ctx, [["claude", "sme"]])
        trash = list(app.services.install_roots.trash_dir("claude", "global", None).glob("sme-*"))
        print("refs", state.load()["refs"], "trash", trash, "leaf", list(leaf.iterdir()) if leaf.exists() else None)
        assert any((t / "SKILL.md").read_text() == "# my own private sme\n" for t in trash)
        replaced = open_rows("pack_skills.edit")
        assert len(replaced) == 1


def test_F_alpha_dropping_a_ref_keeps_the_placed_record(tmp_path, alertdb):
    from src.core.pack.skills import apply as ap

    leaf = tmp_path / "home" / ".claude" / "skills"
    (leaf / "sme").mkdir(parents=True)
    (leaf / "sme" / "SKILL.md").write_text("# sme\n")
    (leaf / "sme" / ".carnivore-skill.json").write_text("{}")
    state = ReceiverState(tmp_path / "s.json")
    data = state.load()
    data["applied"] = [{"family": "claude", "name": "sme", "root": str(leaf), "alpha": "X", "gen": 1, "digest": D, "state": "in sync",
                        "reason": "", "placed": True, "item": "alex/sme", "version": "1.0.0"}]
    state.save(data)
    doc = validate_document({"v": 1, "alpha": "X", "gen": 2, "skills": [], "warez": []}, "X")
    ap.apply_document(doc, None, [], state)
    assert len(state.load()["applied"]) == 1
    alerts.check_placers(state)
    assert len([r for r in open_rows("pack_skills.placer_gone:X") if not r.get("resolved_at")]) == 1
    assert (leaf / "sme" / "SKILL.md").exists()


def test_G_a_bundle_carrying_a_sidecar_is_refused(tmp_path, monkeypatch):
    from src.core.pack.skills import rules
    from src.core.pack.skills.bundle import BundleError, build_bundle, read_bundle
    from src.core.pack.skills.scan import scan_root

    src = tmp_path / "alpha" / ".claude" / "skills"
    (src / "evil").mkdir(parents=True)
    (src / "evil" / "SKILL.md").write_text("# evil\n")
    (src / "evil" / ".carnivore-skill.json").write_text('{"publisher": "alex", "name": "evil", "version": "9.9.9"}')
    monkeypatch.setattr(rules, "IGNORED_BASENAMES", frozenset({".DS_Store"}))
    skill = scan_root(src, "claude").skills["evil"]
    assert any(f.path == ".carnivore-skill.json" for f in skill.files)
    build_bundle(tmp_path / "b.tgz", [("claude", "evil", src / "evil", skill.files)])
    monkeypatch.undo()
    with pytest.raises(BundleError):
        read_bundle(tmp_path / "b.tgz", tmp_path / "stage")


def test_H_trash_placed_uninstalls_the_catalog_install_it_placed(tmp_path, alertdb):
    served = tmp_path / "served"
    served.mkdir()
    trust, pkg = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        home = app.roots.home
        leaf = home / ".claude" / "skills"
        leaf.mkdir(parents=True, exist_ok=True)
        roots = [SkillRoot("claude", leaf, home / ".claude", home / ".claude" / ".carnivore-trash")]
        state = ReceiverState(tmp_path / "pack" / "skills-state.json")
        loop = app.client.portal.call(asyncio.get_running_loop)
        row = ["claude", "sme", "alex/sme", "skill", "1.0.0", pkg.digest, hashlib.sha256(b"b").hexdigest()]
        doc = validate_document({"v": 1, "alpha": "X", "gen": 1, "skills": [], "warez": [row]}, "X")
        ctx = warez_receiver.Context(state, roots, app.services, loop, "X", 1, lambda: True)
        warez_receiver.run(doc, ctx, [["claude", "sme"]])
        assert (leaf / "sme" / "SKILL.md").exists() and any(r.get("placed") for r in state.load()["applied"])
        assert owner.trash_placed(state, "X", roots, None, app.services) == [("claude", "sme")]
        assert not (leaf / "sme").exists() and state.load()["applied"] == []
        assert ledger_rows(app) == []
