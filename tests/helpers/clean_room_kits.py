
from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pytest

from src.api import catalog_mod_gates, themes_routes
from src.core.live_install_roots import LiveInstallRoots
from scripts.warez_gates.clean_room_host import CatalogHost, residue, snapshot  # noqa: F401
from scripts.warez_gates.item import load_item
from scripts.warez_gates.policy import load_policy
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_fixture import skill_item
from tests.helpers.catalog_surface import (
    FIXTURE_REPO, build_loadout, build_plugin, build_skill, build_theme, fixture_trust_root, item_for, keypairs, loadout_item_for,
    member_ref, plugin_item_for, plugin_manifest, publish_index, serve_archive, theme_item_for,
)
from tests.mods.test_mod_install_gates import OK_VERSION, WORKING_ON, fake_claude

PUBLISHER = "gate"
COMMITS = {"skill": "a" * 40, "theme": "b" * 40, "plugin": "c" * 40, "loadout": "d" * 40, "mod": "e" * 40}
@dataclass
class Kit:

    trust: Any
    item_id: str
    landed: Callable[[Any], List[Path]]
    roots: List[Path] = field(default_factory=list)
    patch: Callable[[pytest.MonkeyPatch, Path], None] = lambda mp, tmp: None
    consent: Callable[[Any, str], Optional[Dict[str, Any]]] = lambda app, item_id: None
    roots_factory: Optional[Callable[[Any], Any]] = None
    allowed: Tuple[str, ...] = ()
    still_names_item: Callable[[], bool] = lambda: False
    folder: Optional[Path] = None



def _skill(tmp_path: Path, served: Path, keys) -> Kit:
    index_kp, publisher_kp, _ = keys
    package = build_skill(tmp_path, publisher=PUBLISHER, name="probe-skill", commit=COMMITS["skill"], label="s")
    serve_archive(served, package.tar_bytes, commit=COMMITS["skill"])
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp,
                  items=[item_for(package, publisher=PUBLISHER, name="probe-skill", commit=COMMITS["skill"])])
    return Kit(fixture_trust_root(index_kp, publisher_kp), f"{PUBLISHER}/probe-skill", lambda app: [app.roots.home / ".claude" / "skills" / "probe-skill" / "SKILL.md"], folder=package.folder)


def _theme(tmp_path: Path, served: Path, keys, files: Optional[Dict[str, bytes]] = None) -> Kit:
    index_kp, publisher_kp, _ = keys
    package = build_theme(tmp_path, publisher=PUBLISHER, name="probe_theme", commit=COMMITS["theme"], label="t", files=files)
    serve_archive(served, package.tar_bytes, commit=COMMITS["theme"])
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp,
                  items=[theme_item_for(package, publisher=PUBLISHER, name="probe_theme", commit=COMMITS["theme"])])
    return Kit(fixture_trust_root(index_kp, publisher_kp), f"{PUBLISHER}/probe_theme", lambda app: [app.roots.themes_dir() / "probe_theme" / "theme.json"], folder=package.folder)


def _plugin(tmp_path: Path, served: Path, keys) -> Kit:
    index_kp, publisher_kp, _ = keys
    package = build_plugin(tmp_path, publisher=PUBLISHER, name="probe-plugin", commit=COMMITS["plugin"], label="p")
    serve_archive(served, package.tar_bytes, commit=COMMITS["plugin"])
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp,
                  items=[plugin_item_for(package, publisher=PUBLISHER, name="probe-plugin", commit=COMMITS["plugin"])])
    return Kit(fixture_trust_root(index_kp, publisher_kp), f"{PUBLISHER}/probe-plugin",
               lambda app: [app.roots.home / ".claude" / "skills" / "probe-plugin" / ".claude-plugin" / "plugin.json"], folder=package.folder)


def _loadout(tmp_path: Path, served: Path, keys) -> Kit:
    index_kp, publisher_kp, _ = keys
    skill = build_skill(tmp_path, publisher=PUBLISHER, name="probe-skill", commit=COMMITS["skill"], label="s")
    theme = build_theme(tmp_path, publisher=PUBLISHER, name="probe_theme", commit=COMMITS["theme"], label="t")
    loadout = build_loadout(tmp_path, publisher=PUBLISHER, name="probe-loadout", commit=COMMITS["loadout"], label="l",
                            members=[member_ref(skill, publisher=PUBLISHER, name="probe-skill"), member_ref(theme, publisher=PUBLISHER, name="probe_theme")])
    for package, key in ((skill, "skill"), (theme, "theme"), (loadout, "loadout")):
        serve_archive(served, package.tar_bytes, commit=COMMITS[key])
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[
        item_for(skill, publisher=PUBLISHER, name="probe-skill", commit=COMMITS["skill"]),
        theme_item_for(theme, publisher=PUBLISHER, name="probe_theme", commit=COMMITS["theme"]),
        loadout_item_for(loadout, publisher=PUBLISHER, name="probe-loadout", commit=COMMITS["loadout"])])
    return Kit(fixture_trust_root(index_kp, publisher_kp), f"{PUBLISHER}/probe-loadout",
               lambda app: [app.roots.home / ".claude" / "skills" / "probe-skill" / "SKILL.md", app.roots.themes_dir() / "probe_theme" / "theme.json"])


def _mod(tmp_path: Path, served: Path, keys) -> Kit:
    index_kp, publisher_kp, _ = keys
    members = {
        ".claude-plugin/plugin.json": plugin_manifest("probe-mod"),
        "hooks/hooks.json": json.dumps({"modules": ["./register.ts"]}).encode(),
        "register.ts": b"export default function register() {}\n",
    }
    package = build_skill(tmp_path, publisher=PUBLISHER, name="probe-mod", files=members, commit=COMMITS["mod"], label="m", folder="mods")
    serve_archive(served, package.tar_bytes, commit=COMMITS["mod"])
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[
        skill_item("probe-mod", PUBLISHER, package.digest, kind="mod", repo=FIXTURE_REPO, commit=COMMITS["mod"], path=f"mods/{PUBLISHER}/probe-mod", scripts=1)])
    fake_home = tmp_path / "mod-home"

    def patch(mp: pytest.MonkeyPatch, tmp: Path) -> None:
        (fake_home / ".claude" / "mods").mkdir(parents=True, exist_ok=True)
        (tmp / "bin").mkdir(exist_ok=True)
        cli = fake_claude(tmp / "bin", WORKING_ON)
        mp.setenv("HOME", str(fake_home))
        mp.setattr(catalog_mod_gates, "collect_claude_cli", lambda: {"path": cli, "version": OK_VERSION})
        mp.setattr(catalog_mod_gates, "account_settings_files", lambda: ([], "ok"))

    def consent(app: Any, item_id: str) -> Dict[str, Any]:
        preview = app.client.post("/catalog/install/preview", json={"item_id": item_id, "scope": "global"})
        assert preview.status_code == 200, preview.text[:400]
        sheet = preview.json()
        return {"digest": package.digest, "body_sha": sheet["body_sha"], "scripts": True, "mod_trust": True,
                "mod_flagged_ack": True, "mod_report_sha": sheet["mod_report_sha"], "plan_token": sheet["plan_token"]}

    return Kit(fixture_trust_root(index_kp, publisher_kp), f"{PUBLISHER}/probe-mod",
               lambda app: [fake_home / ".claude" / "mods" / "probe-mod" / "register.ts"], roots=[fake_home], patch=patch, consent=consent,
               roots_factory=lambda settings: LiveInstallRoots(settings_reader=settings),
               allowed=("/.claude/settings.json", "/.claude/settings.json.bak"),
               still_names_item=lambda: "probe-mod" in (fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"), folder=package.folder)


KINDS: Dict[str, Callable] = {"skill": _skill, "theme": _theme, "plugin": _plugin, "loadout": _loadout, "mod": _mod}


@pytest.fixture
def served(tmp_path: Path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path: Path):
    return keypairs(tmp_path / "keys")


def run_kind(kind: str, tmp_path: Path, served: Path, keys, monkeypatch: pytest.MonkeyPatch, plant: bool = False) -> Dict[str, Any]:
    kit = KINDS[kind](tmp_path, served, keys)
    kit.patch(monkeypatch, tmp_path)
    with catalog_app(tmp_path, served, trust_root=kit.trust, roots_factory=kit.roots_factory) as app:
        roots = (*(r for r in (getattr(app.roots, "home", None),) if r), app.state, *kit.roots)
        before = snapshot(*roots)
        body: Dict[str, Any] = {"item_id": kit.item_id, "scope": "global"}
        consent = kit.consent(app, kit.item_id)
        if consent is not None:
            body["plan_token"] = consent.pop("plan_token", None)
            body["consent"] = consent
        installed = app.client.post("/catalog/install", json=body)
        facts: Dict[str, Any] = {"install_status": installed.status_code, "install_text": installed.text[:400]}
        if installed.status_code != 200:
            return facts
        facts["landed"] = [p.is_file() and not p.is_symlink() for p in kit.landed(app)]
        facts["landed_at"] = [str(p) for p in kit.landed(app)]
        with app.services.catalog.ledger() as ledger:
            facts["where"] = [t.path for r in ledger_rows(app) for t in ledger.targets(r.install_id)]
        listed = app.client.get("/catalog/installed").json()["items"]
        facts["listed"] = kit.item_id in {row["item_id"] for row in listed}
        rows = {row.item_id: row for row in ledger_rows(app)}
        displaced: List[str] = []
        removal = app.client.delete(f"/catalog/installed/{rows[kit.item_id].install_id}")
        facts["remove_status"] = removal.status_code
        facts["remove_text"] = removal.text[:300]
        displaced += [str(t) for t in removal.json().get("trashed", [])]
        for member in removal.json().get("removable_members", []):
            member_row = {row.item_id: row for row in ledger_rows(app)}[member]
            member_removal = app.client.delete(f"/catalog/installed/{member_row.install_id}")
            facts.setdefault("member_remove", []).append(member_removal.status_code)
            displaced += [str(t) for t in member_removal.json().get("trashed", [])]
        if plant:
            stray = kit.landed(app)[0]
            stray.parent.mkdir(parents=True, exist_ok=True)
            stray.write_text("left behind", encoding="utf-8")
        facts["displaced_exist"] = all(Path(p).exists() for p in displaced) and bool(displaced)
        facts["ledger_left"] = [row.item_id for row in ledger_rows(app)]
        facts["staging_left"] = app.staging_entries()
        facts["residue"] = [p for p in residue(before, snapshot(*roots), displaced) if not p.endswith(kit.allowed)]
        if kit.allowed and kit.still_names_item():
            facts["residue"].append("a settings file still names the removed item")
        facts["still_landed"] = [p.exists() for p in kit.landed(app)]
    return facts


GATE_KINDS = ("skill", "theme", "plugin", "mod")


@contextlib.contextmanager
def gate_world(kind: str, tmp_path: Path, served: Path, keys, monkeypatch: pytest.MonkeyPatch, *, plant: bool = False,
               theme_files: Optional[Dict[str, bytes]] = None) -> Iterator[Tuple[Any, CatalogHost, str, Callable[[], List[str]]]]:
    kit = KINDS[kind](tmp_path, served, keys, **({"files": theme_files} if theme_files is not None else {}))
    kit.patch(monkeypatch, tmp_path)
    with catalog_app(tmp_path, served, trust_root=kit.trust, roots_factory=kit.roots_factory) as app:
        roots = (*(r for r in (getattr(app.roots, "home", None),) if r), app.state, *kit.roots)
        (tmp_path / "bundled").mkdir(exist_ok=True)
        monkeypatch.setattr(themes_routes, "_bundled_themes_root", lambda: tmp_path / "bundled")
        monkeypatch.setattr(themes_routes, "_user_themes_root", lambda: app.roots.themes_dir())
        before = snapshot(*roots)
        host = CatalogHost(app, after_delete=lambda: _plant(kit.landed(app)[0]) if plant else None)

        def residue() -> List[str]:
            left = [p for p in globals()["residue"](before, snapshot(*roots), host.displaced) if not p.endswith(kit.allowed)]
            return left + (["a settings file still names the removed item"] if kit.allowed and kit.still_names_item() else [])

        facts = {"kind": kind, "handle": PUBLISHER, "name": kit.item_id.split("/", 1)[1], "version": "1.0.0"}
        yield load_item(kit.folder, facts, load_policy()), host, kit.item_id, residue


def _plant(stray: Path) -> None:
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("left behind", encoding="utf-8")
