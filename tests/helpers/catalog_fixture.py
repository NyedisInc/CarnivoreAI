
from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.catalog.minisign import parse_public_key, parse_signature
from src.core.catalog.revocation import revoke_statement
from src.models.catalog_statement import release_statement
from tests.helpers.minisign_keys import Keypair, require_minisign, sign_file

SCHEMA = "carnivore.catalog.index/1"

DEFAULT_REPO = "carnivore-ai/catalog"
DEFAULT_COMMIT = "b5a9f4e3" * 5

DEFAULT_GENERATED_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)

_counter = 0


@dataclass(frozen=True)
class SignedIndex:

    index_bytes: bytes
    minisig_text: str
    document: Dict[str, Any]


def _payload_path(tmp_path: Path, label: str) -> Path:
    global _counter
    _counter += 1
    directory = tmp_path / "signing"
    directory.mkdir(exist_ok=True)
    return directory / f"{label}-{_counter}.bin"


def sign_bytes(
    tmp_path: Path, keypair: Keypair, payload: bytes, label: str = "payload",
) -> str:
    path = _payload_path(tmp_path, label)
    path.write_bytes(payload)
    return sign_file(keypair, path)


def sign_bytes_legacy(
    tmp_path: Path, keypair: Keypair, payload: bytes, label: str = "payload",
) -> str:
    binary = require_minisign()
    path = _payload_path(tmp_path, label)
    path.write_bytes(payload)
    result = subprocess.run(
        [binary, "-S", "-W", "-l", "-s", str(keypair.sec_path), "-m", str(path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"minisign exited {result.returncode}: {result.stderr}")
    text = Path(str(path) + ".minisig").read_text()
    assert not parse_signature(text).prehashed, "minisign -l did not go legacy"
    return text


def signature_block(
    tmp_path: Path, keypair: Keypair, payload: bytes, label: str = "release",
) -> Dict[str, str]:
    lines = sign_bytes(tmp_path, keypair, payload, label).splitlines()
    return {
        "key_id": parse_public_key(keypair.public_key_text).key_id,
        "sig": lines[1],
        "tc": lines[2][len("trusted comment: "):],
        "gsig": lines[3],
    }


def public_key_line(keypair: Keypair) -> str:
    return keypair.public_key_text.splitlines()[1]


def impersonating_public_key(real: Keypair, other: Keypair) -> str:
    real_blob = base64.b64decode(public_key_line(real), validate=True)
    other_blob = base64.b64decode(public_key_line(other), validate=True)
    return base64.b64encode(real_blob[:10] + other_blob[10:]).decode("ascii")


def skill_item(
    name: str,
    publisher: str,
    digest: str,
    *,
    version: str = "1.0.0",
    scripts: int = 0,
    item_id: Optional[str] = None,
    kind: str = "skill",
    repo: str = DEFAULT_REPO,
    path: Optional[str] = None,
    commit: str = DEFAULT_COMMIT,
    grade: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    version_entry: Dict[str, Any] = {
        "v": version,
        "src": {
            "repo": repo,
            "path": path or f"skills/{publisher}/{name}",
            "commit": commit,
        },
        "digest": digest,
        "size": 1024,
        "files": 1,
        "scripts": scripts,
        "published_at": "2026-09-01T12:00:00+00:00",
    }
    if grade is not None:
        version_entry["grade"] = grade
    return {
        "id": item_id or f"{publisher}/{name}",
        "kind": kind,
        "name": name,
        "publisher": publisher,
        "latest": version,
        "card": {"title": name, "brief": f"the {name} skill"},
        "fm": {"description": f"the {name} skill"},
        "versions": [version_entry],
        **(extra or {}),
    }


def sign_item_versions(
    tmp_path: Path, item: Dict[str, Any], keypair: Keypair,
) -> Dict[str, Any]:
    for version in item["versions"]:
        if "sig" in version:
            continue
        statement = release_statement(
            kind=item["kind"],
            publisher=item["publisher"],
            name=item["name"],
            version=version["v"],
            repo=version["src"]["repo"],
            path=version["src"]["path"],
            commit=version["src"]["commit"],
            digest=version["digest"],
        )
        version["sig"] = signature_block(tmp_path, keypair, statement, "release")
    return item


def revocation_entry(
    tmp_path: Path,
    *,
    kind: str,
    subject: str,
    since: str,
    keypair: Keypair,
) -> Dict[str, str]:
    statement = revoke_statement(kind=kind, subject=subject, since=since)
    signed = sign_bytes(tmp_path, keypair, statement, "revoke")
    common = {"since": since, "statement": statement.decode("utf-8"), "sig": signed}
    if kind == "key":
        return {"key_id": subject, **common}
    item, _, version = subject.partition("@")
    return {"item": item, "version": version, **common}


def seal(
    tmp_path: Path, document: Dict[str, Any], index_keypair: Keypair,
) -> SignedIndex:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"))
    index_bytes = body.encode("utf-8")
    return SignedIndex(
        index_bytes=index_bytes,
        minisig_text=sign_bytes(tmp_path, index_keypair, index_bytes, "index"),
        document=document,
    )


def build_signed_index(
    tmp_path: Path,
    *,
    index_keypair: Keypair,
    publisher_keypair: Keypair,
    items: List[Dict[str, Any]],
    serial: int = 1,
    generated_at: datetime = DEFAULT_GENERATED_AT,
    revocations: Optional[Dict[str, Any]] = None,
    publisher_handle: str = "acme",
) -> SignedIndex:
    document: Dict[str, Any] = {
        "schema": SCHEMA,
        "serial": serial,
        "generated_at": generated_at.isoformat(),
        "publishers": {
            publisher_handle: {
                "github_login": publisher_handle,
                "keys": [
                    {
                        "key_id": parse_public_key(
                            publisher_keypair.public_key_text
                        ).key_id,
                        "alg": "ed25519",
                        "pub": public_key_line(publisher_keypair),
                        "added": "2026-09-01T00:00:00+00:00",
                        "status": "active",
                    }
                ],
            }
        },
        "revocations": revocations or {"keys": [], "versions": []},
        "items": [
            sign_item_versions(tmp_path, item, publisher_keypair)
            for item in items
        ],
    }
    return seal(tmp_path, document, index_keypair)
