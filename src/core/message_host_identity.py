
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

SCHEME_PLATFORM_UUID: str = "platform_uuid"
SCHEME_DECLARED: str = "declared"

ATTR_VERIFIED: str = "manifest_verified"
ATTR_DECLARED: str = "declared"
ATTR_CANNOT_DETERMINE: str = "cannot_determine"

_UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)

_CHUNK = 1 << 20


@dataclass(frozen=True)
class HostIdentity:

    machine_id: str
    machine_id_scheme: str
    display_name: str
    hostname: str
    platform: str


def _ioreg_platform_uuid() -> Optional[str]:
    if platform.system() != "Darwin":
        return None
    try:
        out = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    if match is None:
        return None
    value = match.group(1).strip()
    return value if _UUID_RE.match(value) else None


def _scutil(key: str) -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        return subprocess.run(
            ["/usr/sbin/scutil", "--get", key],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def capture_identity(declared_id: Optional[str] = None) -> HostIdentity:
    uuid = _ioreg_platform_uuid()
    if uuid is not None:
        machine_id, scheme = uuid, SCHEME_PLATFORM_UUID
    elif declared_id:
        machine_id, scheme = declared_id, SCHEME_DECLARED
    else:
        raise ValueError(
            "no IOPlatformUUID could be read and no declared_id was given - "
            "there is no host identity to record, and inventing one is the "
            "silent wrong attribution this module exists to prevent"
        )
    name = computer_display_name()
    return HostIdentity(
        machine_id=machine_id, machine_id_scheme=scheme,
        display_name=name or machine_id, hostname=platform.node(),
        platform=f"{platform.system()} {platform.release()}",
    )


def computer_display_name() -> str:
    return _scutil("ComputerName") or platform.node()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def walk_jsonl(root: str) -> List[str]:
    found: List[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".jsonl"):
                full = os.path.join(dirpath, name)
                found.append(os.path.relpath(full, root))
    found.sort()
    return found


def build_manifest(
    root: str, identity: HostIdentity, corpus_key: str,
) -> Dict[str, object]:
    entries: Dict[str, object] = {}
    errors = 0
    for rel in walk_jsonl(root):
        full = os.path.join(root, rel)
        try:
            entries[rel] = {"size": os.path.getsize(full),
                            "sha256": sha256_file(full)}
        except OSError as exc:
            errors += 1
            entries[rel] = {"size": None, "sha256": None,
                            "error": f"{type(exc).__name__}: {exc}"}
    return {
        "machine_id": identity.machine_id,
        "machine_id_scheme": identity.machine_id_scheme,
        "display_name": identity.display_name,
        "hostname": identity.hostname,
        "platform": identity.platform,
        "corpus_key": corpus_key,
        "root_path": root,
        "file_count": len(entries),
        "unreadable_count": errors,
        "files": entries,
    }


def manifest_sha(manifest: Dict[str, object]) -> str:
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def classify_attribution(
    manifest: Optional[Dict[str, object]], source_path: str,
    observed_sha256: str, observed_bytes: int,
) -> Tuple[str, str]:
    if manifest is None:
        return ATTR_DECLARED, "no collection manifest for this corpus"
    files = manifest.get("files")
    if not isinstance(files, dict):
        return ATTR_CANNOT_DETERMINE, "manifest has no files table"
    entry = files.get(source_path)
    if entry is None:
        return ATTR_CANNOT_DETERMINE, (
            "not present in the source machine's manifest, so nothing on "
            "that machine attests to this path"
        )
    if not isinstance(entry, dict) or entry.get("sha256") is None:
        return ATTR_CANNOT_DETERMINE, (
            f"the source machine could not hash this file: "
            f"{entry.get('error') if isinstance(entry, dict) else entry!r}"
        )
    if entry["sha256"] == observed_sha256:
        return ATTR_VERIFIED, ""
    size = entry.get("size")
    if isinstance(size, int) and observed_bytes > size:
        return ATTR_CANNOT_DETERMINE, (
            f"bytes read ({observed_bytes}) exceed the manifest size "
            f"({size}) - the file grew after collection, so the manifest "
            "cannot attest to what was read"
        )
    return ATTR_CANNOT_DETERMINE, (
        f"sha256 disagrees with the source machine's manifest "
        f"(read {observed_sha256[:16]}..., manifest "
        f"{str(entry['sha256'])[:16]}...)"
    )


def iter_manifest_paths(manifest: Dict[str, object]) -> Iterator[str]:
    files = manifest.get("files")
    if not isinstance(files, dict):
        return iter(())
    return iter(sorted(files))


def _main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: <root> <corpus_key> [declared_id]", flush=True)
        return 2
    root = os.path.expanduser(argv[0])
    identity = capture_identity(argv[2] if len(argv) > 2 else None)
    manifest = build_manifest(root, identity, argv[1])
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(_main(_sys.argv[1:]))
