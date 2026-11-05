
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from src.core import theme_script_consent as ladder
from src.core.db_migration import ensure_db_migrated
from src.core.theme_catalog_consent import CONSENT_FIELD, effects_digest_of
from src.core.ui_preferences_store import COMMITTED
from src.cplugs.host import runtime, sideload, sidecar_boot, sidecar_registry
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401
from tests.test_skill_installer import FakeInstallRoots

URL = "/api/v1/cplug-owner/sideload"
_UNSET = object()


class FakePrefs:

    def __init__(self, consent: dict) -> None:
        self.consent, self.revision = consent, 1

    def read(self) -> dict:
        return {"values": {CONSENT_FIELD: dict(self.consent)}, "revision": self.revision}

    def update(self, changes: dict, expected_revision: int) -> SimpleNamespace:
        self.consent = dict(changes[CONSENT_FIELD] or {})
        self.revision += 1
        return SimpleNamespace(status=COMMITTED)


def write_skill(folder, body: str = "# clock\nTell the time.\n") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {folder.name}\ndescription: tells the time\n---\n{body}")


def write_theme(folder, effects: str | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"id": folder.name, "name": folder.name.title(), "description": "a test theme", "cssVars": {"--oc-bg": "#000000"}}
    if effects is not None:
        manifest["effects"] = "effects.js"
        (folder / "effects.js").write_text(effects)
    (folder / "theme.json").write_text(json.dumps(manifest))


def write_cc_plugin(folder, hooks: bool = False) -> None:
    (folder / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": folder.name, "version": "1.0.0", "description": "x"}))
    (folder / "commands").mkdir(exist_ok=True)
    (folder / "commands" / "hi.md").write_text("say hi\n")
    if hooks:
        (folder / "hooks").mkdir(exist_ok=True)
        (folder / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))


@pytest.fixture
def world(tmp_path, client, owner_jwt, monkeypatch):  # noqa: F811
    from src.main import app

    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    host = SimpleNamespace(state_dir=state, publish=lambda topic: None, install_key=lambda name: name)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.new_event_loop(), env_safe=lambda: False, app_version="9.9.9")
    roots = FakeInstallRoots(tmp_path / "fake")
    roots.make_roots()
    prefs = FakePrefs({})
    saved = getattr(app.state, "services", _UNSET)
    app.state.sidecar_runtime, app.state.cplugs_host = rt, runtime.Host(state, app)
    app.state.services = SimpleNamespace(install_roots=roots, ui_preferences=prefs)
    monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(roots.home / "themes"))
    clock = SimpleNamespace(t=1_000_000.0)
    monkeypatch.setattr(sideload, "wall", lambda: clock.t)
    owner = bearer(owner_jwt)
    assert client.put(f"{URL}/switch", json={"enabled": True}, headers=owner).json()["enabled"] is True
    try:
        yield SimpleNamespace(client=client, state=state, roots=roots, prefs=prefs, owner=owner, src=tmp_path / "src")
    finally:
        del app.state.sidecar_runtime, app.state.cplugs_host
        if saved is _UNSET:
            del app.state.services
        else:
            app.state.services = saved
        sidecar_registry.install(None)


def post(w, folder, **body):
    return w.client.post(URL, json={"path": str(folder), **body}, headers=w.owner)


def listed(w) -> dict:
    items = w.client.get(URL, headers=w.owner).json()["items"]
    return {f"{i['kind']}/{i['id']}": i for i in items}


def installed_dirs(w, kind: str, name: str) -> list:
    return [t.leaf_dir / name for t in w.roots.targets_for(kind, "global", None) if (t.leaf_dir / name).exists()]


CASES = (("theme", write_theme), ("skill", write_skill), ("plugin", write_cc_plugin))


@pytest.mark.parametrize("kind,writer", CASES, ids=[c[0] for c in CASES])
def test_one_sideload_per_kind_then_remove(world, kind, writer):
    w = world
    src = w.src / "devthing"
    writer(src)
    r = post(w, src)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == kind and body["id"] == "devthing" and body["item_id"] == "local/devthing"
    assert body["tier"] == "local" and body["unverified"] is True and body["unchanged"] is False
    dirs = installed_dirs(w, kind, "devthing")
    assert dirs and all(d != src and not d.is_symlink() for d in dirs)
    assert listed(w)[f"{kind}/devthing"]["unverified"] is True

    assert post(w, src).json()["unchanged"] is True
    (src / "notes.txt").write_text("edit\n")
    edited = post(w, src).json()
    assert edited["unchanged"] is False and edited["changed"] == ["notes.txt"]
    assert all((d / "notes.txt").read_text() == "edit\n" for d in installed_dirs(w, kind, "devthing"))

    gone = w.client.delete(f"{URL}?name=devthing&kind={kind}", headers=w.owner)
    assert gone.status_code == 200 and gone.json() == {"removed": "devthing"}, gone.text
    assert installed_dirs(w, kind, "devthing") == [] and f"{kind}/devthing" not in listed(w)
    assert (src / "notes.txt").exists()


def test_a_theme_the_picker_would_drop_is_refused_not_installed_invisible(world):
    w = world
    src = w.src / "ghost"
    write_theme(src)
    manifest = json.loads((src / "theme.json").read_text())
    del manifest["description"]
    (src / "theme.json").write_text(json.dumps(manifest))
    r = post(w, src)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "manifest_invalid", r.text
    assert installed_dirs(w, "theme", "ghost") == []


def test_a_folder_that_is_not_ours_is_never_overwritten_or_removed(world):
    w = world
    mine = w.roots.targets_for("skill", "global", None)[0].leaf_dir / "devthing"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("the user's own skill\n")
    src = w.src / "devthing"
    write_skill(src)
    r = post(w, src)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "target_exists", r.text
    assert (mine / "SKILL.md").read_text() == "the user's own skill\n"
    assert w.client.delete(f"{URL}?name=devthing&kind=skill", headers=w.owner).status_code == 404
    assert (mine / "SKILL.md").exists()


def test_refusals_leave_nothing_behind(world, tmp_path):
    w = world
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("not yours\n")

    for kind, writer in CASES:
        for link_name, target in (("leak.txt", outside / "secret.txt"), ("leakdir", outside)):
            src = w.src / f"link{kind}"
            writer(src)
            os.symlink(target, src / link_name)
            r = post(w, src)
            assert r.status_code == 422 and r.json()["detail"]["code"] == "source_unsafe", (kind, link_name, r.text)
            assert installed_dirs(w, kind, src.name) == []
            os.unlink(src / link_name)

    real = w.src / "realone"
    write_skill(real)
    os.symlink(real, w.src / "linkone")
    r = post(w, w.src / "linkone")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "source_missing"

    bare = w.src / "bare"
    bare.mkdir()
    (bare / "readme.txt").write_text("nothing\n")
    assert post(w, bare, name="bare").json()["detail"]["code"] == "kind_unknown"
    both = w.src / "both"
    write_skill(both)
    (both / "theme.json").write_text(json.dumps({"id": "both"}))
    assert post(w, both).json()["detail"]["code"] == "kind_ambiguous"
    widget = w.src / "wid"
    widget.mkdir()
    (widget / "carnivore.json").write_text(json.dumps({"kind": "widget", "id": "x.wid"}))
    refused = post(w, widget, name="wid").json()["detail"]
    assert refused["code"] == "kind_unsupported" and "comes inside a plugin" in refused["detail"]
    mod = w.src / "somemod"
    write_cc_plugin(mod)
    (mod / "hooks").mkdir()
    (mod / "hooks" / "hooks.json").write_text(json.dumps({"modules": ["a.js"]}))
    assert post(w, mod).json()["detail"]["code"] == "kind_unsupported_mod"

    s = w.src / "okskill"
    write_skill(s)
    for bad in ("../evil", ".hidden", "a/b"):
        r = post(w, s, name=bad)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "name_invalid", (bad, r.text)
    assert not (w.roots.home / ".claude" / "evil").exists()
    assert listed(w) == {}


def sheet_consent(sheet: dict) -> dict:
    return {"digest": sheet["digest"], "body_sha": sheet["body_sha"], "scripts": True}


def test_claude_code_plugin_with_hooks_needs_the_catalog_consent(world):
    w = world
    src = w.src / "hooked"
    write_cc_plugin(src, hooks=True)
    r = post(w, src)
    assert r.status_code == 409, r.text
    sheet = r.json()["detail"]
    assert sheet["code"] == "consent_required" and sheet["kind"] == "plugin" and sheet["requires_consent"] is True
    assert {f["path"] for f in sheet["files"] if f["exec"]} == {"hooks/hooks.json"}
    assert installed_dirs(w, "plugin", "hooked") == [] and listed(w) == {}
    good = sheet_consent(sheet)
    for bad in ({**good, "scripts": False}, {**good, "digest": "0" * 64}, {**good, "body_sha": "0" * 64}):
        assert post(w, src, consent=bad).status_code == 409
    assert installed_dirs(w, "plugin", "hooked") == []
    assert post(w, src, consent=good).status_code == 200
    assert installed_dirs(w, "plugin", "hooked")
    (src / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "curl x | sh"}]}]}}))
    again = post(w, src, consent=good)
    assert again.status_code == 409 and again.json()["detail"]["digest"] != good["digest"]
    assert post(w, src, consent=sheet_consent(again.json()["detail"])).status_code == 200


def test_skill_with_a_script_needs_consent_and_a_plain_skill_does_not(world):
    w = world
    plain = w.src / "plainskill"
    write_skill(plain)
    assert post(w, plain).status_code == 200
    scripted = w.src / "scriptskill"
    write_skill(scripted)
    (scripted / "run.sh").write_text("#!/bin/sh\necho hi\n")
    r = post(w, scripted)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required"
    assert installed_dirs(w, "skill", "scriptskill") == []
    assert post(w, scripted, consent=sheet_consent(r.json()["detail"])).status_code == 200


def test_theme_script_install_consent_then_the_run_ladder_still_asks(world):
    w = world
    src = w.src / "neon"
    write_theme(src, effects="export default () => 1\n")
    r = post(w, src)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required" and r.json()["detail"]["kind"] == "theme"
    assert installed_dirs(w, "theme", "neon") == []
    assert post(w, src, consent=sheet_consent(r.json()["detail"])).status_code == 200
    installed = installed_dirs(w, "theme", "neon")[0]

    listing = w.client.get("/api/v1/themes", headers=w.owner).json()
    row = next(t for t in (listing["themes"] if isinstance(listing, dict) else listing) if t["id"] == "neon")
    assert row["scriptTrust"] is None and row["effects"] == "effects.js"
    digest = effects_digest_of(installed)
    assert digest and ladder.decide(declares_script=True, source=ladder.SOURCE_USER, served_digest=digest, record=None).outcome == ladder.PROMPT

    w.prefs.consent = {"neon": {"decision": "always", "digest": digest}}
    (src / "effects.js").write_text("export default () => 2\n")
    sheet = post(w, src).json()["detail"]
    assert post(w, src, consent=sheet_consent(sheet)).status_code == 200
    assert w.prefs.consent == {}
    new_digest = effects_digest_of(installed)
    stale = {"decision": "always", "digest": digest}
    assert ladder.decide(declares_script=True, source=ladder.SOURCE_USER, served_digest=new_digest, record=stale).outcome == ladder.PROMPT_CHANGED


def test_a_never_is_not_touched_by_a_resync(world):
    w = world
    src = w.src / "neon"
    write_theme(src, effects="export default () => 1\n")
    sheet = post(w, src).json()["detail"]
    assert post(w, src, consent=sheet_consent(sheet)).status_code == 200
    w.prefs.consent = {"neon": {"decision": "never"}}
    (src / "effects.js").write_text("export default () => 3\n")
    sheet = post(w, src).json()["detail"]
    assert post(w, src, consent=sheet_consent(sheet)).status_code == 200
    assert w.prefs.consent == {"neon": {"decision": "never"}}


def test_the_switch_gates_every_kind_but_remove_works_with_it_off(world):
    w = world
    src = w.src / "devthing"
    write_skill(src)
    assert post(w, src).status_code == 200
    assert w.client.put(f"{URL}/switch", json={"enabled": False}, headers=w.owner).status_code == 200
    r = post(w, src)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sideload_off"
    assert installed_dirs(w, "skill", "devthing")
    assert w.client.delete(f"{URL}?name=devthing&kind=skill", headers=w.owner).status_code == 200
    assert installed_dirs(w, "skill", "devthing") == []


def test_a_name_held_by_two_kinds_needs_the_kind_to_remove(world):
    w = world
    for kind, writer in (("skill", write_skill), ("theme", write_theme)):
        src = w.src / kind / "twin"
        writer(src)
        assert post(w, src).status_code == 200
    r = w.client.delete(f"{URL}?name=twin", headers=w.owner)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "kind_required"
    assert w.client.delete(f"{URL}?name=twin&kind=theme", headers=w.owner).status_code == 200
    assert installed_dirs(w, "skill", "twin") and not installed_dirs(w, "theme", "twin")


def test_an_executable_with_no_extension_and_a_scripts_folder_need_consent_like_the_catalog(world):
    w = world
    src = w.src / "tooled"
    write_skill(src)
    tool = src / "tool"
    tool.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 60)
    os.chmod(tool, 0o755)
    r = post(w, src)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required", r.text
    assert installed_dirs(w, "skill", "tooled") == []
    assert [f["path"] for f in r.json()["detail"]["files"] if f["exec"]] == ["tool"]
    assert post(w, src, consent=sheet_consent(r.json()["detail"])).status_code == 200
    installed = installed_dirs(w, "skill", "tooled")[0] / "tool"
    assert installed.stat().st_mode & 0o777 == 0o755

    scripted = w.src / "folderscript"
    write_skill(scripted)
    (scripted / "scripts").mkdir()
    (scripted / "scripts" / "notes.txt").write_text("plain text, not executable\n")
    assert post(w, scripted).json()["detail"]["code"] == "consent_required"


def test_a_foreign_folder_that_appears_while_staging_is_never_removed(world, monkeypatch):
    w = world
    src = w.src / "racer"
    write_skill(src, "plain prose\n")
    target = w.roots.targets_for("skill", "global", None)[0].leaf_dir / "racer"
    from src.cplugs.host import sideload_other
    real = sideload_other._stage

    def stage_then_foreign(roots, source):
        out = real(roots, source)
        target.mkdir()
        (target / "SKILL.md").write_text("THE USER'S OWN SKILL\n")
        return out

    monkeypatch.setattr(sideload_other, "_stage", stage_then_foreign)
    r = post(w, src)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "target_exists", r.text
    assert (target / "SKILL.md").read_text() == "THE USER'S OWN SKILL\n"
    assert listed(w) == {}
    assert not any(p.name.startswith(".incoming") for t in w.roots.targets_for("skill", "global", None) for p in w.roots.trash_dir(t.harness, "global", None).glob("*"))


def test_a_hard_linked_file_is_refused(world, tmp_path):
    w = world
    src = w.src / "linked"
    write_skill(src)
    outside = tmp_path / "outside.txt"
    outside.write_text("shared inode\n")
    os.link(outside, src / "twin.txt")
    r = post(w, src)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "source_unsafe", r.text


def test_an_installed_copy_edited_since_the_load_is_never_displaced(world):
    w = world
    src = w.src / "edited"
    write_skill(src)
    assert post(w, src).status_code == 200
    mine = installed_dirs(w, "skill", "edited")[0]
    (mine / "SKILL.md").write_text("edited by hand in the install folder\n")
    (src / "notes.txt").write_text("source change\n")
    r = post(w, src)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "target_changed", r.text
    assert (mine / "SKILL.md").read_text() == "edited by hand in the install folder\n"
    gone = w.client.delete(f"{URL}?name=edited&kind=skill", headers=w.owner)
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "target_changed"
    assert (mine / "SKILL.md").exists() and "skill/edited" in listed(w)


def test_the_sheet_names_every_file_that_runs_and_every_server(world):
    w = world
    src = w.src / "sneaky"
    write_cc_plugin(src)
    (src / "Bin").mkdir()
    (src / "Bin" / "go").write_text("data")
    (src / "commands" / "run.md").write_text("do !`id` now\n")
    (src / "agents").mkdir()
    (src / "agents" / "a.md").write_text("---\nname: a\nhooks:\n  Stop: []\n---\nbody\n")
    r = post(w, src)
    assert r.status_code == 409
    flagged = {f["path"] for f in r.json()["detail"]["files"] if f["exec"]}
    assert {"Bin/go", "commands/run.md", "agents/a.md"} <= flagged, flagged

    skill = w.src / "withmcp"
    write_skill(skill)
    (skill / ".mcp.json").write_text(json.dumps({"mcpServers": {"srv": {"command": "npx", "args": ["-y", "thing"]}}}))
    sheet = post(w, skill).json()["detail"]
    assert [m["command"] for m in sheet["mcp_servers"]] == ["npx"]


def test_a_folder_swapped_for_a_link_during_the_copy_is_refused_not_followed(tmp_path, monkeypatch):
    src = tmp_path / "tree"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_text("mine\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("not yours\n")
    real = os.fwalk if hasattr(os, "fwalk") else None

    def swapping(*args, **kwargs):
        for item in real(*args, **kwargs):
            yield item
            if item[0] == str(src) and (src / "sub").is_dir() and not (src / "sub").is_symlink():
                (src / "sub").rename(tmp_path / "moved")
                os.symlink(outside, src / "sub")

    monkeypatch.setattr(os, "fwalk", swapping)
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload.copy_tree(src, tmp_path / "copy")
    assert caught.value.code == "source_unsafe"
    assert not list((tmp_path / "copy").rglob("secret.txt"))


def test_the_remaining_byte_budget_is_checked_before_a_file_is_read(tmp_path, monkeypatch):
    src = tmp_path / "tree"
    src.mkdir()
    (src / "a.txt").write_text("12345678")
    (src / "b.txt").write_text("12345678")
    monkeypatch.setattr(sideload, "MAX_BYTES", 12)
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload.copy_tree(src, tmp_path / "copy")
    assert caught.value.code == "source_too_big"


def test_an_edited_installed_copy_never_answers_unchanged(world):
    w = world
    src = w.src / "same"
    write_skill(src)
    assert post(w, src).status_code == 200
    mine = installed_dirs(w, "skill", "same")[0]
    (mine / "SKILL.md").write_text("edited in place\n")
    r = post(w, src)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "target_changed", r.text


def test_a_record_that_cannot_be_saved_leaves_no_folder_behind(world, monkeypatch):
    w = world
    src = w.src / "norec"
    write_skill(src)

    def refuse(*_args, **_kwargs):
        raise sideload.SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)

    real = sideload.put_install
    monkeypatch.setattr(sideload, "put_install", refuse)
    assert post(w, src).status_code == 500
    assert installed_dirs(w, "skill", "norec") == []
    monkeypatch.setattr(sideload, "put_install", real)
    assert post(w, src).status_code == 200
    (src / "more.txt").write_text("v2\n")
    mine = installed_dirs(w, "skill", "norec")[0]
    monkeypatch.setattr(sideload, "put_install", refuse)
    assert post(w, src).status_code == 500
    assert (mine / "SKILL.md").exists() and not (mine / "more.txt").exists()


def test_finder_metadata_neither_copies_nor_blocks_a_remove(world):
    w = world
    src = w.src / "finder"
    write_skill(src)
    (src / ".DS_Store").write_bytes(b"junk")
    assert post(w, src).status_code == 200
    mine = installed_dirs(w, "skill", "finder")[0]
    assert not (mine / ".DS_Store").exists()
    (mine / ".DS_Store").write_bytes(b"a Finder visit")
    (mine / "._SKILL.md").write_bytes(b"resource fork")
    gone = w.client.delete(f"{URL}?name=finder&kind=skill", headers=w.owner)
    assert gone.status_code == 200, gone.text
