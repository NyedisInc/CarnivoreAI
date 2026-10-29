"""#2426: every package in the two hash locks has a wheel usable on each CPU architecture the release ships.

cryptography 49 and later publish macOS wheels for arm64 only, so a lock pinning them for an Intel Mac cannot install.
The locks record only sha256 digests, so the filename (and with it the wheel tags) of each digest comes from the
committed snapshot lock_wheel_filenames.json (digest -> wheel filename; any other file is recorded as "sdist", because a digest beside an sdist name
containing "api" trips the generic-api-key rule of the commit scanner), and this test never touches
the network. After any re-lock, refresh the snapshot (network, run from the repo root):
    python3 tests/python/release/test_lock_wheel_arches.py --refresh
The architectures are read from macOS/release-arch.json (single_arch_name_tokens); a pin whose marker is false for an
architecture and interpreter is not checked there. The interpreters are the proven range, Python 3.12 to 3.14.
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

from packaging.markers import Marker
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[3]
LOCKS = [ROOT / "requirements.lock", ROOT / "macOS" / "payload" / "runtime.lock"]
SNAPSHOT = Path(__file__).with_name("lock_wheel_filenames.json")
MACHINE = {"arm64": "arm64", "x64": "x86_64"}
PLATFORM_SUFFIXES = {
    "arm64": ("_arm64", "_universal2"),
    "x86_64": ("_x86_64", "_universal2", "_intel", "_fat64", "_fat32"),
}
PYTHONS = [(3, 12, 15), (3, 13, 0), (3, 14, 0)]

sys.path.insert(0, str(ROOT / "scripts" / "release"))
import requirements_lock  # noqa: E402

sys.path.pop(0)


def release_machines() -> list[str]:
    tokens = json.loads((ROOT / "macOS" / "release-arch.json").read_text())["single_arch_name_tokens"]
    return [MACHINE[token] for token in tokens]


def wheel_usable(filename: str, machine: str, minor: int) -> bool:
    if not filename.endswith(".whl"):
        return False
    _, _, _, tags = parse_wheel_filename(filename)
    for tag in tags:
        interp = tag.interpreter
        if interp.startswith("cp3"):
            version = int(interp[3:])
            if not (version == minor and tag.abi in (interp, "abi3", "none")) and not (
                tag.abi == "abi3" and version <= minor
            ):
                continue
        elif not interp.startswith("py3") and interp != "py2.py3":
            continue
        if tag.platform == "any":
            return True
        if tag.platform.startswith("macosx_") and tag.platform.endswith(PLATFORM_SUFFIXES[machine]):
            return True
    return False


def unusable(lock: Path, snapshot: dict[str, str], machines: list[str]) -> list[str]:
    problems = []
    for entry in requirements_lock.parse_lock(lock.read_text()):
        unknown = [h for h in entry.hashes if h not in snapshot]
        if unknown:
            problems.append(f"{entry.name}=={entry.version}: {len(unknown)} digests not in the snapshot (refresh it)")
            continue
        files = [snapshot[h] for h in entry.hashes]
        for machine in machines:
            for major, minor, micro in PYTHONS:
                env = {
                    "platform_machine": machine, "sys_platform": "darwin", "platform_system": "Darwin",
                    "os_name": "posix", "implementation_name": "cpython", "platform_python_implementation": "CPython",
                    "python_version": f"{major}.{minor}", "python_full_version": f"{major}.{minor}.{micro}",
                }
                if entry.marker and not Marker(entry.marker).evaluate(env):
                    continue
                if not any(wheel_usable(name, machine, minor) for name in files):
                    problems.append(f"{lock.name}: {entry.name}=={entry.version} has no wheel for macOS {machine} on 3.{minor}")
    return problems


def test_the_release_architectures_are_both_read_from_the_file():
    assert set(release_machines()) == {"arm64", "x86_64"}


def test_every_locked_package_has_a_wheel_for_every_release_architecture():
    snapshot = json.loads(SNAPSHOT.read_text())
    for lock in LOCKS:
        assert unusable(lock, snapshot, release_machines()) == []


def test_the_check_goes_red_on_an_arm64_only_pin():
    snapshot = json.loads(SNAPSHOT.read_text())
    fifty = next(e for e in requirements_lock.parse_lock(LOCKS[1].read_text()) if e.version == "50.0.0")
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "runtime.lock"
        broken.write_text("cryptography==50.0.0 \\\n" + " \\\n".join(f"    --hash=sha256:{h}" for h in fifty.hashes) + "\n")
        problems = unusable(broken, snapshot, ["arm64", "x86_64"])
    assert any("cryptography==50.0.0 has no wheel for macOS x86_64" in p for p in problems)
    assert not any("arm64" in p and "has no wheel" in p for p in problems)


def test_the_snapshot_covers_every_locked_digest():
    snapshot = json.loads(SNAPSHOT.read_text())
    for lock in LOCKS:
        for entry in requirements_lock.parse_lock(lock.read_text()):
            assert all(h in snapshot for h in entry.hashes), f"{entry.name}=={entry.version}: refresh the snapshot"


def refresh() -> None:
    pins = {(e.name, e.version) for lock in LOCKS for e in requirements_lock.parse_lock(lock.read_text())}
    snapshot: dict[str, str] = {}
    for name, version in sorted(pins):
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
            for upload in json.load(response)["urls"]:
                name = upload["filename"]
                snapshot[upload["digests"]["sha256"]] = name if name.endswith(".whl") else "sdist"
    ordered = dict(sorted(snapshot.items(), key=lambda item: (item[1], item[0])))
    SNAPSHOT.write_text(json.dumps(ordered, indent=0) + "\n")
    print(f"wrote {len(ordered)} digests for {len(pins)} pins")


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    else:
        print(__doc__)
