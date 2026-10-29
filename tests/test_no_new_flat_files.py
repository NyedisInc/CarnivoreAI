
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "ratchet_flat_files.json"

GUARDED_DIRS: dict[str, str] = {
    "src/core": "src/core",
    "scripts": "scripts",
    "tests": "tests_root",
}


def _load_baseline() -> dict[str, list[str]]:
    with BASELINE_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data


def flat_files_on_disk(directory: Path, repo_root: Path) -> frozenset[str]:
    if not directory.is_dir():
        return frozenset()
    found = set()
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        found.add(entry.relative_to(repo_root).as_posix())
    return frozenset(found)


def check_ratchet(
    on_disk_by_dir: dict[str, frozenset[str]],
    baseline_by_dir: dict[str, list[str]],
) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    for label, on_disk in on_disk_by_dir.items():
        allowed = frozenset(baseline_by_dir.get(label, []))
        extra = sorted(on_disk - allowed)
        if extra:
            offenders[label] = extra
    return offenders


def test_baseline_file_exists_and_is_not_empty():
    assert BASELINE_PATH.is_file(), f"{BASELINE_PATH} is missing"
    baseline = _load_baseline()
    for label in GUARDED_DIRS.values():
        assert baseline.get(label), (
            f"baseline list {label!r} in {BASELINE_PATH} is empty; "
            "that cannot be right for a live directory"
        )


def test_no_new_flat_files():
    baseline = _load_baseline()
    on_disk = {
        label: flat_files_on_disk(REPO_ROOT / rel, REPO_ROOT)
        for rel, label in GUARDED_DIRS.items()
    }
    offenders = check_ratchet(on_disk, baseline)
    assert not offenders, (
        "new flat file(s) landed outside the ratchet baseline; move each "
        "one into its domain subfolder (see docs/repo-hygiene-and-structure.md) "
        f"rather than adding it to {BASELINE_PATH.name}:\n"
        + "\n".join(
            f"  {label}: {paths}" for label, paths in sorted(offenders.items())
        )
    )


def test_ratchet_can_go_red():
    offenders = check_ratchet(
        on_disk_by_dir={
            "src/core": frozenset(
                {"src/core/session_manager.py", "src/core/a_brand_new_module.py"}
            ),
        },
        baseline_by_dir={
            "src/core": ["src/core/session_manager.py"],
        },
    )
    assert offenders == {"src/core": ["src/core/a_brand_new_module.py"]}


def test_ratchet_allows_shrinking():
    offenders = check_ratchet(
        on_disk_by_dir={
            "scripts": frozenset({"scripts/kept.py"}),
        },
        baseline_by_dir={
            "scripts": ["scripts/kept.py", "scripts/already_deleted.py"],
        },
    )
    assert offenders == {}
