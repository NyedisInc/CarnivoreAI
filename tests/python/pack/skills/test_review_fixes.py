from __future__ import annotations

import os
import tarfile
import time
from pathlib import Path

from src.core.pack.skills import apply as ap, owner
import pytest

from src.core.pack.skills import bundle as bundle_mod
from src.core.pack.skills.bundle import build_bundle, read_bundle, BundleError
from src.core.pack.skills.receiver import ReceiverState
from src.core.pack.skills.scan import scan_root
from src.core.pack.skills.targets import receiver_roots
from src.core.pack.skills import secrets_gate


def _w(p: Path, text: str = "x\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _alpha_bundle(tmp: Path, name: str = "demo"):
    alpha = tmp / "alpha" / ".claude" / "skills"
    _w(alpha / name / "SKILL.md", "alpha copy\n")
    scan = scan_root(alpha, "claude")
    sk = scan.skills[name]
    out = tmp / "b.tgz"
    build_bundle(out, [("claude", name, alpha / name, sk.files)])
    bundle = read_bundle(out, tmp / "stage")
    doc = {"alpha": "A", "gen": 1, "skills": [["claude", name, sk.digest]], "removals": [], "unsynced": [], "choices": {}}
    return doc, bundle


def _home(tmp: Path) -> Path:
    home = tmp / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    (home / ".carnivore" / "accounts").mkdir(parents=True)
    return home


def test_symlinked_skill_folder_is_a_conflict_and_the_checkout_is_untouched(tmp_path: Path) -> None:
    home = _home(tmp_path)
    dev = tmp_path / "dev" / "demo"
    _w(dev / "SKILL.md", "my dev copy\n")
    _w(dev / ".git" / "HEAD", "ref: refs/heads/main\n")
    _w(dev / "node_modules" / "x" / "index.js")
    os.symlink(dev, home / ".claude" / "skills" / "demo")
    doc, bundle = _alpha_bundle(tmp_path)
    roots = receiver_roots(home, home / ".carnivore" / "accounts", [])
    rep = ap.apply_document(doc, bundle, roots, ReceiverState(tmp_path / "state.json"))
    assert (dev / ".git" / "HEAD").exists() and (dev / "node_modules" / "x" / "index.js").exists()
    assert (dev / "SKILL.md").read_text() == "my dev copy\n" and (home / ".claude" / "skills" / "demo").is_symlink()
    assert [r["reason"] for r in rep.rows] == ["skill folder is a link"]


def test_trash_placed_only_takes_what_alpha_placed_and_keeps_later_edits(tmp_path: Path) -> None:
    home = _home(tmp_path)
    skills = home / ".claude" / "skills"
    _w(skills / "demo" / "SKILL.md", "receiver's own, never replaced\n")
    doc, bundle = _alpha_bundle(tmp_path)
    roots = receiver_roots(home, home / ".carnivore" / "accounts", [])
    state = ReceiverState(tmp_path / "state.json")
    ap.apply_document(doc, None, roots, state)
    assert owner.trash_placed(state, "A", roots) == []
    assert (skills / "demo" / "SKILL.md").read_text().startswith("receiver's own")
    _w(skills / "demo" / "SKILL.md", "receiver's own, never replaced\n")
    import shutil
    shutil.rmtree(skills / "demo")
    ap.apply_document(doc, bundle, roots, state)
    assert (skills / "demo" / "SKILL.md").read_text() == "alpha copy\n"
    ap.apply_document({**doc, "gen": 2}, None, roots, state)
    _w(skills / "demo" / "SKILL.md", "edited here since\n")
    assert owner.trash_placed(state, "A", roots) == [] and (skills / "demo").exists()
    _w(skills / "demo" / "SKILL.md", "alpha copy\n")
    ap.apply_document({**doc, "gen": 3}, None, roots, state)
    assert owner.trash_placed(state, "A", roots) == [("claude", "demo")] and not (skills / "demo").exists()


def test_removal_keeps_the_receivers_own_skill_and_acts_once(tmp_path: Path) -> None:
    home = _home(tmp_path)
    roots = receiver_roots(home, home / ".carnivore" / "accounts", [])
    state = ReceiverState(tmp_path / "state.json")
    trash = home / ".claude" / ".carnivore-trash"
    entry = [["claude", "demo", 1700000000]]
    for gen in (1, 2, 3):
        _w(home / ".claude" / "skills" / "demo" / "SKILL.md", f"receiver's own skill v{gen}\n")
        ap.apply_document({"alpha": "A", "gen": gen, "skills": [], "removals": entry, "unsynced": [], "choices": {}}, None, roots, state)
    assert (home / ".claude" / "skills" / "demo" / "SKILL.md").read_text() == "receiver's own skill v3\n"
    assert not trash.exists() or not [p for p in trash.iterdir() if p.name.startswith("demo-")]
    doc, bundle = _alpha_bundle(tmp_path / "t2")
    shutil_state = ReceiverState(tmp_path / "state2.json")
    home2 = _home(tmp_path / "h2")
    roots2 = receiver_roots(home2, home2 / ".carnivore" / "accounts", [])
    ap.apply_document(doc, bundle, roots2, shutil_state)
    rm = {"alpha": "A", "gen": 2, "skills": [], "removals": [["claude", "demo", 5]], "unsynced": [], "choices": {}}
    ap.apply_document(rm, None, roots2, shutil_state)
    assert not (home2 / ".claude" / "skills" / "demo").exists()
    _w(home2 / ".claude" / "skills" / "demo" / "SKILL.md", "new local one\n")
    ap.apply_document({**rm, "gen": 3}, None, roots2, shutil_state)
    assert (home2 / ".claude" / "skills" / "demo").exists()


def test_new_alpha_holds_for_extra_chosen_skills(tmp_path: Path) -> None:
    from src.core.pack.skills import status
    from src.core.pack.skills.doc import Choices

    alpha = tmp_path / "skills"
    _w(alpha / "mine" / "SKILL.md")
    _w(alpha / "known" / "SKILL.md")
    scans = {"claude": scan_root(alpha, "claude")}
    accepted = {"skills": [["claude", "known", scans["claude"].skills["known"].digest]]}
    assert status.takeover_differences(accepted, scans) == 0
    assert status.takeover_differences(accepted, scans, Choices(mode="all")) == 1
    assert status.takeover_differences(accepted, scans, Choices(mode="off")) == 0


def test_tar_header_bomb_stops_at_the_member_cap(tmp_path: Path) -> None:
    out = tmp_path / "bomb.tgz"
    with tarfile.open(out, "w:gz") as tar:
        for i in range(bundle_mod.MAX_MEMBERS + 50):
            info = tarfile.TarInfo(f"claude/demo/d{i}")
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
    calls = []
    real = tarfile.TarFile.next
    def counting(self):
        calls.append(1)
        return real(self)
    tarfile.TarFile.next = counting
    try:
        with pytest.raises(BundleError) as err:
            read_bundle(out, tmp_path / "stage")
    finally:
        tarfile.TarFile.next = real
    assert err.value.code == "too_large" and len(calls) <= bundle_mod.MAX_MEMBERS + 5


@pytest.mark.parametrize("name", ["prod.env", ".git-credentials", "credentials", ".pgpass", "key.ppk", "store.jks", "a.keystore",
                                  "service-account.json", "client_secret_123.json", "token.json", ".htpasswd", ".s3cfg", ".boto", ".dockercfg"])
def test_credential_shaped_names_are_held(name: str) -> None:
    assert secrets_gate.name_problem(name) is not None


def test_settings_gate_is_case_insensitive_reads_toml_and_scans_big_files() -> None:
    assert secrets_gate.file_problem("Settings.json", b'{"env": {"A": "plainpassword"}}')
    assert secrets_gate.file_problem("config.toml", b'[mcp_servers.x.env]\nTOKEN = "abc"\n')
    assert secrets_gate.file_problem("notes.log", b"x" * (2 * 1024 * 1024) + b"\n" + ("ghp_" + "a1B2c3D4e5F6g7H8i9J0" * 2).encode() + b"\n")


def test_a_file_edited_after_the_scan_is_not_bundled(tmp_path: Path) -> None:
    alpha = tmp_path / "skills"
    _w(alpha / "demo" / "SKILL.md", "scanned\n")
    sk = scan_root(alpha, "claude").skills["demo"]
    _w(alpha / "demo" / "SKILL.md", "edited after the scan\n")
    with pytest.raises(BundleError) as err:
        build_bundle(tmp_path / "b.tgz", [("claude", "demo", alpha / "demo", sk.files)])
    assert err.value.code == "hash_mismatch"


def test_a_name_over_the_byte_cap_is_refused() -> None:
    from src.core.pack.skills import rules

    assert rules.skill_name_problem("a" * 200) == "name too long"
    assert rules.skill_name_problem("a" * 60) is None


def test_a_cut_short_inventory_is_partial_and_the_oversize_offer_is_refused() -> None:
    import asyncio

    from src.core.pack.skills.runtime import PeerView

    async def request(method: str, path: str):
        return 200, {"skills": [["claude", "a", "g", "d" * 64, False]], "truncated": True}

    class View:
        peer_id, label, up = "B", "b", True
        def has_cap(self) -> bool:
            return True

    got = asyncio.run(owner.fetch_inventories([View()], lambda _id: request))
    assert [i.state for i in got] == ["partial"]
