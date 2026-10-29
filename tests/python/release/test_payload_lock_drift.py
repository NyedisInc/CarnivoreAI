
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = ROOT / "requirements.txt"
PAYLOAD = ROOT / "macOS" / "payload"
LOCK = PAYLOAD / "runtime.lock"
BUILD = PAYLOAD / "build-payload.sh"
DROPPED = {"pytest", "pytest-asyncio", "playwright"}
MUST_BE_LOCKED = {"fastapi", "starlette", "uvicorn", "backports-zstd"}
PAYLOAD_PYTHON = {"python_version": "3.12", "python_full_version": "3.12.15", "sys_platform": "darwin"}


def runtime_requirements(path: Path = REQUIREMENTS) -> list[Requirement]:
    reqs = []
    for line in path.read_text().splitlines():
        line = line.split(" #")[0].strip()
        if line and not line.startswith("#"):
            req = Requirement(line)
            if canonicalize_name(req.name) not in DROPPED:
                reqs.append(req)
    return reqs


def locked_versions(path: Path = LOCK) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)", path.read_text(), re.M):
        out[canonicalize_name(m.group(1))] = m.group(2)
    return out


def drift(requirements: list[Requirement], locked: dict[str, str]) -> list[str]:
    bad = []
    for req in requirements:
        if req.marker is not None and not req.marker.evaluate(PAYLOAD_PYTHON):
            continue
        name = canonicalize_name(req.name)
        if name not in locked:
            bad.append(f"{name}: missing from runtime.lock")
        elif not req.specifier.contains(locked[name], prereleases=True):
            bad.append(f"{name}: locked {locked[name]} outside {req.specifier}")
    return bad


def test_every_runtime_requirement_is_locked():
    reqs = runtime_requirements()
    assert {canonicalize_name(r.name) for r in reqs} >= MUST_BE_LOCKED
    assert drift(reqs, locked_versions()) == []
    assert MUST_BE_LOCKED <= set(locked_versions())


def test_removing_backports_zstd_from_a_lock_copy_goes_red(tmp_path):
    text = LOCK.read_text()
    stripped = re.sub(r"^backports-zstd==.*?(?=^\S)", "", text, flags=re.M | re.S)
    assert stripped != text
    copy = tmp_path / "runtime.lock"
    copy.write_text(stripped)
    assert "backports-zstd: missing from runtime.lock" in drift(runtime_requirements(), locked_versions(copy))


def test_every_lock_pin_is_hashed():
    blocks = re.split(r"^(?=[A-Za-z0-9_.\-]+==)", LOCK.read_text(), flags=re.M)[1:]
    assert blocks and all(re.search(r"--hash=sha256:[0-9a-f]{64}\b", b) for b in blocks)


def test_build_script_pins_are_sha256():
    text = BUILD.read_text()
    pin_lines = [ln for ln in text.splitlines() if re.match(r"\s+(arm64|x86_64)\|", ln)]
    assert len(pin_lines) == 2
    digests = [h for ln in pin_lines for h in re.findall(r"\s([0-9a-f]{64})\s", ln)]
    assert len(digests) == 4 and len(set(digests)) == 4
    assert "shasum -a 256" in text and "sha256 mismatch" in text


def test_empty_entitlements_plist_stays_empty():
    text = (PAYLOAD / "entitlements.payload.plist").read_text()
    assert re.search(r"<dict>\s*</dict>", text) and "<key>" not in text
