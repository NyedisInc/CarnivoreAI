from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401,E402
from src.api import federation_pack_skills_routes as routes  # noqa: E402
from src.core.pack.skills import apply as skills_apply  # noqa: E402
from src.core.pack.skills import owner, warez_receiver, wiring  # noqa: E402
from src.core.pack.skills.doc import Choices  # noqa: E402
from src.core.pack.skills.receiver import ReceiverState, validate_document  # noqa: E402
from src.core.pack.skills.scan import RootScan  # noqa: E402
from src.core.pack.skills.targets import SkillRoot  # noqa: E402
from src.core.skills import install_by_reference as ibr  # noqa: E402
from tests.helpers.catalog_app import catalog_app, ledger_rows  # noqa: E402
from tests.helpers.catalog_fixture import sign_item_versions  # noqa: E402
from tests.helpers.catalog_surface import build_skill, fixture_trust_root, item_for, keypairs, publish_index, serve_archive  # noqa: E402

CLEAN = {"status": "reviewed", "verdict": "clean", "summary": "fine.", "warnings": [], "model": "m", "reviewed_at": "2026-09-19T00:00:00Z"}
BLOCKED = {**CLEAN, "verdict": "blocked", "warnings": [{"kind": "credential_access", "detail": "reads aws credentials", "file": "SKILL.md", "line": 1}]}
BODY = hashlib.sha256(b"b").hexdigest()


def _publish(tmp_path, served, review=CLEAN, *, serve=True, scripts=False):
    index_kp, publisher_kp, _ = keypairs(tmp_path / "keys")
    files = {"SKILL.md": b"# sme\n", **({"run.sh": b"#!/bin/sh\n"} if scripts else {})}
    pkg = build_skill(tmp_path, publisher="alex", name="sme", label="1", files=files, exec_paths=("run.sh",) if scripts else ())
    if serve:
        serve_archive(served, pkg.tar_bytes, commit="1" * 40)
    sme = item_for(pkg, publisher="alex", name="sme", commit="1" * 40, version="1.0.0", **({"scripts": 1} if scripts else {}))
    sme["versions"][0]["review"] = review
    sign_item_versions(tmp_path, sme, publisher_kp)
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[sme], serial=1)
    return fixture_trust_root(index_kp, publisher_kp), pkg


def _run(app, tmp_path, pkg, *, alpha="X", gen=1, install=True, retry_only=False, body=BODY, roots=None, state=None, family="claude"):
    home = app.roots.home
    leaf = home / ".claude" / "skills"
    leaf.mkdir(parents=True, exist_ok=True)
    roots = roots or [SkillRoot("claude", leaf, home / ".claude", home / ".claude" / ".carnivore-trash")]
    state = state or ReceiverState(tmp_path / "pack" / "skills-state.json")
    loop = app.client.portal.call(asyncio.get_running_loop)
    row = [family, "sme", "alex/sme", "skill", "1.0.0", pkg.digest, body]
    doc = validate_document({"v": 1, "alpha": alpha, "gen": gen, "skills": [], "warez": [row]}, alpha)
    saved = state.load()
    saved["doc"], saved["applied_gen"] = doc, gen
    state.save(saved)
    ctx = warez_receiver.Context(state, roots, app.services, loop, alpha, gen, lambda: True)
    warez_receiver.run(doc, ctx, [[family, "sme"]] if install else None, retry_only=retry_only)
    return doc, ctx, roots, state, leaf


def _app(tmp_path, **kw):
    served = tmp_path / "served"
    served.mkdir()
    trust, pkg = _publish(tmp_path, served, **kw)
    return catalog_app(tmp_path, served, trust_root=trust), pkg


def test_an_item_the_owner_uninstalled_here_is_reinstalled_while_alpha_names_it(tmp_path, monkeypatch):
    from src.api.catalog_installed_support import uninstall_with

    ctx_mgr, pkg = _app(tmp_path)
    with ctx_mgr as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        doc, ctx, roots, state, leaf = _run(app, tmp_path, pkg)
        assert (leaf / "sme" / "SKILL.md").exists() and len(ledger_rows(app)) == 1
        monkeypatch.setattr(routes, "refs_context", lambda: (app.services, ctx.loop))
        assert routes._need_refs(doc, state) == []
        uninstall_with(app.services, ledger_rows(app)[0].install_id)
        assert ledger_rows(app) == [] and not (leaf / "sme").exists()
        assert routes._need_refs(doc, state) == [["claude", "sme"]]
        warez_receiver.run(doc, ctx, None, retry_only=True)
        assert (leaf / "sme" / "SKILL.md").exists() and len(ledger_rows(app)) == 1


def test_a_terminal_fetch_conflict_is_not_refetched_for_the_same_ref_until_the_network_is_back():
    rec = {"gen": 1, "outcome": "conflict", "code": "consent_mismatch", "version": "1.0.0", "digest": "d", "body": "b", "attempts": 0}
    assert warez_receiver._due(rec, 2, 0.0, True, False, same_ref=True) is False
    assert warez_receiver._due(rec, 2, 0.0, True, False, same_ref=False) is True
    assert warez_receiver._due({**rec, "code": "version_revoked"}, 2, 0.0, True, False, same_ref=True) is True


def test_a_refresh_the_ref_pass_triggered_does_not_reset_the_retry_counters(tmp_path, monkeypatch):
    state = ReceiverState(tmp_path / "skills-state.json")
    data = state.load()
    data["refs"] = {"alex/sme": {"code": "unreachable", "attempts": 2, "next_at": 99.0, "outcome": "unknown"}}
    state.save(data)
    calls = []
    monkeypatch.setattr(wiring, "SYNC", SimpleNamespace(state=state, retry_refs=lambda: calls.append(1)))
    with warez_receiver._RUN_LOCK:
        asyncio.run(wiring.after_index_refresh())
    assert state.load()["refs"]["alex/sme"]["attempts"] == 2 and calls == []
    asyncio.run(wiring.after_index_refresh())
    assert state.load()["refs"]["alex/sme"]["attempts"] == 0 and calls == [1]


@pytest.mark.parametrize("on", [True, False])
def test_an_overridden_review_syncs_only_when_the_switch_is_on(tmp_path, monkeypatch, on):
    monkeypatch.setattr(ibr, "SYNC_OVERRIDDEN_REVIEWS", on)
    ctx_mgr, pkg = _app(tmp_path, review={**BLOCKED, "override": {"reason": "the aws read is the point of this skill"}})
    with ctx_mgr as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        _doc, _ctx, _roots, state, leaf = _run(app, tmp_path, pkg)
        if on:
            assert (leaf / "sme" / "SKILL.md").exists() and len(ledger_rows(app)) == 1
        else:
            assert state.load()["refs"]["alex/sme"]["code"] == "review_not_clean" and ledger_rows(app) == [] and not (leaf / "sme").exists()


def test_an_unreachable_archive_is_a_retry_and_a_wrong_manifest_sha_is_a_consent_mismatch(tmp_path):
    ctx_mgr, pkg = _app(tmp_path, serve=False)
    with ctx_mgr as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        home = app.roots.home
        (home / ".codex").mkdir(exist_ok=True)
        (home / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
        before = _tree(home / ".agents")
        _doc, _ctx, _roots, state, leaf = _run(app, tmp_path, pkg)
        rec = state.load()["refs"]["alex/sme"]
        assert (rec["code"], rec["attempts"]) in (("unreachable", 1), ("unknown", 1)) and ledger_rows(app) == []
        assert _tree(home / ".agents") == before


def test_a_script_carrying_item_with_the_wrong_manifest_sha_is_a_consent_mismatch(tmp_path):
    ctx_mgr, pkg = _app(tmp_path, scripts=True)
    with ctx_mgr as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        _doc, _ctx, _roots, state, leaf = _run(app, tmp_path, pkg)
        assert state.load()["refs"]["alex/sme"]["code"] == "consent_mismatch" and ledger_rows(app) == [] and not (leaf / "sme").exists()


def _tree(path: Path) -> dict:
    return {str(p.relative_to(path)): p.is_dir() for p in sorted(path.rglob("*"))}


def test_remove_everywhere_uninstalls_a_catalog_install_the_pack_placed_and_keeps_the_owners_own(tmp_path):
    ctx_mgr, pkg = _app(tmp_path)
    with ctx_mgr as app:
        assert app.client.post("/catalog/index/refresh").status_code == 200
        _doc, ctx, roots, state, leaf = _run(app, tmp_path, pkg)
        assert (leaf / "sme").exists()
        drop = validate_document({"v": 1, "alpha": "X", "gen": 2, "skills": [], "removals": [["claude", "sme", 1]]}, "X")
        skills_apply.apply_document(drop, None, roots, state, services=app.services)
        assert not (leaf / "sme").exists() and ledger_rows(app) == []
        state.save({**state.load(), "applied": []})
        _run(app, tmp_path, pkg, gen=3, state=state)
        state.save({**state.load(), "applied": []})
        again = validate_document({"v": 1, "alpha": "X", "gen": 4, "skills": [], "removals": [["claude", "sme", 2]]}, "X")
        skills_apply.apply_document(again, None, roots, state, services=app.services)
        assert (leaf / "sme" / "SKILL.md").exists() and len(ledger_rows(app)) == 1


def _sync(doc, peers, gen=3):
    return SimpleNamespace(status=lambda: {"alpha": "A", "gen": gen, "problem": None, "hold": False, "peers": peers},
                           published=lambda: doc)


def test_the_preview_the_matrix_and_the_receiver_view_know_catalog_references():
    ref = ["claude", "sme", "alex/sme", "skill", "1.0.0", "d" * 64, BODY]
    same = owner.Inventory("t", "studio", "ok", warez=(("claude", "sme", "alex/sme", "1.0.0"),))
    older = owner.Inventory("r", "ripley", "ok", warez=(("claude", "sme", "alex/sme", "0.9.0"),))
    none = owner.Inventory("n", "newt", "ok")
    other = owner.Inventory("o", "ovo", "ok", warez=(("claude", "sme", "eve/other", "1.0.0"),))
    out = owner.preview(Choices(mode="all"), {}, [same, older, none, other], [ref], {("claude", "sme")})
    words = {c["label"]: c["skills"]["claude/sme"] for c in out["computers"]}
    assert words["studio"] == "already the same" and words["ripley"] == "will change alex/sme to 1.0.0"
    assert words["newt"] == "will install alex/sme 1.0.0 from warez" and words["ovo"].startswith("conflict: another catalog item")
    assert out["skills"][0]["warez"] is True and out["skills"][0]["size"] == 0 and out["total_bytes"] == 0
    peer = {"state": "in sync", "conflicts": []}
    assert owner._cell(True, ("claude", "sme"), "d", peer, same, ("alex/sme", "1.0.0")) == "in sync"
    assert owner._cell(True, ("claude", "sme"), "d", peer, older, ("alex/sme", "1.0.0")) == "differs"
    assert owner._cell(True, ("claude", "sme"), "d", peer, none, ("alex/sme", "1.0.0")) == "missing"
    bad = owner.Inventory("b", "bad", "ok", conflicts=(("claude", "sme", "review not clean, install it there by hand"),))
    assert owner._cell(True, ("claude", "sme"), "d", peer, bad, ("alex/sme", "1.0.0")) == "conflict"
    doc = {"skills": [], "warez": [ref], "held": []}
    view = owner.matrix(_sync(doc, {"t": {**peer, "label": "studio"}}), Choices(mode="all"), {"claude": RootScan({}, [])}, [same], "A")
    row = next(r for r in view["rows"] if r["name"] == "sme")
    assert row["state"] == "synced" and row["cells"]["t"] == "in sync" and row["warez"] == {"item": "alex/sme", "version": "1.0.0"}


def test_the_receiver_view_lists_catalog_rows_with_who_placed_them(tmp_path):
    state = ReceiverState(tmp_path / "skills-state.json")
    ref = ["claude", "sme", "alex/sme", "skill", "1.0.0", "d" * 64, BODY]
    data = state.load()
    data["doc"] = {"alpha": "A", "gen": 2, "skills": [], "warez": [ref]}
    data["applied"] = [{"family": "claude", "name": "sme", "root": "/r", "alpha": "A", "state": "in sync", "placed": True, "item": "alex/sme"}]
    state.save(data)
    view = owner.receiver_view(SimpleNamespace(state=state), "A", "nostromo")
    row = view["rows"][0]
    assert (row["name"], row["state"], row["warez"]["item"], row["placed_by"]["label"]) == ("sme", "in sync", "alex/sme", "nostromo")
