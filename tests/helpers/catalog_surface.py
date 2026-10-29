
from __future__ import annotations

import io
import json
import os
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.catalog.minisign import parse_public_key
from src.core.catalog.trust_root import TrustRoot
from src.core.skills import kinds
from src.core.skills.digest import digest_directory
from tests.helpers.catalog_fixture import build_signed_index, skill_item
from tests.helpers.minisign_keys import Keypair, generate_keypair

INDEX_PATH = "v1/index.json"

FIXTURE_REPO = "carnivore-ai/skills"
FIXTURE_COMMIT = "b" * 40

ARCHIVE_FOLDER_SKILL = kinds.archive_folder(kinds.KIND_SKILL)
ARCHIVE_FOLDER_THEME = kinds.archive_folder(kinds.KIND_THEME)
ARCHIVE_FOLDER_PLUGIN = kinds.archive_folder(kinds.KIND_PLUGIN)
ARCHIVE_FOLDER_LOADOUT = kinds.archive_folder(kinds.KIND_LOADOUT)

GENERATED_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


class FrozenClock:

    def __init__(self, at: float = NOW.timestamp(), mono: float = 1000.0) -> None:
        self._at = at
        self._mono = mono

    def now(self) -> float:
        return self._at

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._at += seconds
        self._mono += seconds


@dataclass(frozen=True)
class Published:

    digest: str
    tar_bytes: bytes
    folder: Path


def build_skill(
    tmp_path: Path,
    *,
    publisher: str,
    name: str,
    files: Optional[Dict[str, bytes]] = None,
    repo: str = FIXTURE_REPO,
    commit: str = FIXTURE_COMMIT,
    label: str = "pkg",
    folder: str = ARCHIVE_FOLDER_SKILL,
    exec_paths: Tuple[str, ...] = (),
) -> Published:
    members = files or {
        "SKILL.md": f"---\nname: {name}\n---\n# {name}\n\nthe {name} skill\n".encode()
    }
    folder_path = tmp_path / "packages" / label / name
    for relpath, body in members.items():
        target = folder_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        os.chmod(target, 0o755 if relpath in exec_paths else 0o644)

    digest, _entries = digest_directory(folder_path)
    prefix = f"{repo.split('/')[1]}-{commit}/{folder}/{publisher}/{name}/"

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for relpath, body in sorted(members.items()):
            info = tarfile.TarInfo(f"{prefix}{relpath}")
            info.mode = 0o755 if relpath in exec_paths else 0o644
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return Published(digest=digest, tar_bytes=buffer.getvalue(), folder=folder_path)


def theme_manifest(name: str, *, effects: Optional[str] = None) -> bytes:
    manifest: Dict[str, Any] = {
        "id": name,
        "name": name.replace("_", " ").title(),
        "description": f"the {name} theme",
        "author": "carnivore",
        "version": "1.0.0",
        "cssVars": {
            "--color-bg": "#101014",
            "--color-fg": "#e8e8f0",
            "--color-accent": "#7f5af0",
            "--color-border": "#2a2a35",
        },
        "xterm": {"background": "#101014", "foreground": "#e8e8f0"},
    }
    if effects is not None:
        manifest["effects"] = effects
    return json.dumps(manifest, indent=2).encode("utf-8")


def build_theme(
    tmp_path: Path,
    *,
    publisher: str,
    name: str,
    effects: Optional[bytes] = None,
    files: Optional[Dict[str, bytes]] = None,
    repo: str = FIXTURE_REPO,
    commit: str = FIXTURE_COMMIT,
    label: str = "pkg",
) -> Published:
    members: Dict[str, bytes] = {
        "theme.json": theme_manifest(name, effects="effects.js" if effects else None)
    }
    if effects is not None:
        members["effects.js"] = effects
    if files:
        members.update(files)
    return build_skill(
        tmp_path,
        publisher=publisher,
        name=name,
        files=members,
        repo=repo,
        commit=commit,
        label=label,
        folder=ARCHIVE_FOLDER_THEME,
    )


def plugin_manifest(
    name: str,
    *,
    version: str = "1.0.0",
    description: Optional[str] = None,
) -> bytes:
    manifest: Dict[str, Any] = {
        "name": name,
        "description": description or f"the {name} plugin",
        "version": version,
        "author": {"name": "carnivore"},
    }
    return json.dumps(manifest, indent=2).encode("utf-8")


def build_plugin(
    tmp_path: Path,
    *,
    publisher: str,
    name: str,
    files: Optional[Dict[str, bytes]] = None,
    repo: str = FIXTURE_REPO,
    commit: str = FIXTURE_COMMIT,
    label: str = "pkg",
    exec_paths: Tuple[str, ...] = (),
) -> Published:
    members: Dict[str, bytes] = {
        ".claude-plugin/plugin.json": plugin_manifest(name)
    }
    if files:
        members.update(files)
    return build_skill(
        tmp_path,
        publisher=publisher,
        name=name,
        files=members,
        repo=repo,
        commit=commit,
        label=label,
        folder=ARCHIVE_FOLDER_PLUGIN,
        exec_paths=exec_paths,
    )


def loadout_manifest(
    name: str,
    *,
    members: List[Dict[str, str]],
    description: Optional[str] = None,
    schema: str = "carnivore.catalog.loadout/1",
) -> bytes:
    manifest: Dict[str, Any] = {
        "schema": schema,
        "name": name,
        "description": description or f"the {name} loadout",
        "members": members,
    }
    return json.dumps(manifest, indent=2).encode("utf-8")


def member_ref(
    published: Published, *, publisher: str, name: str, version: str = "1.0.0"
) -> Dict[str, str]:
    return {
        "id": f"{publisher}/{name}",
        "version": version,
        "digest": published.digest,
    }


def build_loadout(
    tmp_path: Path,
    *,
    publisher: str,
    name: str,
    members: List[Dict[str, str]],
    description: Optional[str] = None,
    schema: str = "carnivore.catalog.loadout/1",
    files: Optional[Dict[str, bytes]] = None,
    repo: str = FIXTURE_REPO,
    commit: str = FIXTURE_COMMIT,
    label: str = "pkg",
) -> Published:
    body: Dict[str, bytes] = {
        "loadout.json": loadout_manifest(
            name, members=members, description=description, schema=schema
        )
    }
    if files:
        body.update(files)
    return build_skill(
        tmp_path,
        publisher=publisher,
        name=name,
        files=body,
        repo=repo,
        commit=commit,
        label=label,
        folder=ARCHIVE_FOLDER_LOADOUT,
    )


def serve_archive(
    root: Path, tar_bytes: bytes, *, repo: str = FIXTURE_REPO, commit: str = FIXTURE_COMMIT
) -> str:
    target = root / repo / "tar.gz" / commit
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(tar_bytes)
    return f"/{repo}/tar.gz/{commit}"


def publish_index(
    tmp_path: Path,
    root: Path,
    *,
    index_keypair: Keypair,
    publisher_keypair: Keypair,
    items: List[Dict[str, Any]],
    serial: int = 1,
    generated_at: datetime = GENERATED_AT,
    publisher_handle: str = "alex",
    revocations: Optional[Dict[str, Any]] = None,
) -> bytes:
    signed = build_signed_index(
        tmp_path,
        index_keypair=index_keypair,
        publisher_keypair=publisher_keypair,
        items=items,
        serial=serial,
        generated_at=generated_at,
        publisher_handle=publisher_handle,
        revocations=revocations,
    )
    index_file = root / INDEX_PATH
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_bytes(signed.index_bytes)
    (index_file.parent / f"{index_file.name}.minisig").write_text(signed.minisig_text)
    return signed.index_bytes


def fixture_trust_root(
    index_keypair: Keypair,
    publisher_keypair: Keypair,
    *,
    min_index_serial: int = 0,
    max_serial_jump: int = 1000,
    staleness_days: int = 30,
) -> TrustRoot:
    return TrustRoot(
        index_key=parse_public_key(index_keypair.public_key_text),
        publisher_key=parse_public_key(publisher_keypair.public_key_text),
        min_index_serial=min_index_serial,
        max_serial_jump=max_serial_jump,
        staleness_days=staleness_days,
    )


def keypairs(tmp_path: Path) -> Tuple[Keypair, Keypair, Keypair]:
    made = []
    for label in ("k-index", "k-publisher", "k-stranger"):
        directory = tmp_path / label
        directory.mkdir(parents=True, exist_ok=True)
        made.append(generate_keypair(directory))
    return (made[0], made[1], made[2])


def item_for(published: Published, *, publisher: str, name: str, **overrides) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "repo": FIXTURE_REPO,
        "commit": FIXTURE_COMMIT,
        "path": f"{ARCHIVE_FOLDER_SKILL}/{publisher}/{name}",
    }
    arguments.update(overrides)
    return skill_item(name, publisher, published.digest, **arguments)


def theme_item_for(
    published: Published, *, publisher: str, name: str, **overrides
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "kind": kinds.KIND_THEME,
        "repo": FIXTURE_REPO,
        "commit": FIXTURE_COMMIT,
        "path": f"{ARCHIVE_FOLDER_THEME}/{publisher}/{name}",
    }
    arguments.update(overrides)
    return skill_item(name, publisher, published.digest, **arguments)


def plugin_item_for(
    published: Published, *, publisher: str, name: str, **overrides
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "kind": kinds.KIND_PLUGIN,
        "repo": FIXTURE_REPO,
        "commit": FIXTURE_COMMIT,
        "path": f"{ARCHIVE_FOLDER_PLUGIN}/{publisher}/{name}",
    }
    arguments.update(overrides)
    return skill_item(name, publisher, published.digest, **arguments)


def loadout_item_for(
    published: Published, *, publisher: str, name: str, **overrides
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "kind": kinds.KIND_LOADOUT,
        "repo": FIXTURE_REPO,
        "commit": FIXTURE_COMMIT,
        "path": f"{ARCHIVE_FOLDER_LOADOUT}/{publisher}/{name}",
    }
    arguments.update(overrides)
    return skill_item(name, publisher, published.digest, **arguments)


def open_and_list(app):
    app.client.post("/catalog/refresh")
    return app.client.get("/catalog/items")
