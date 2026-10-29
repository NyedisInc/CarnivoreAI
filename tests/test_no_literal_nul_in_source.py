
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_TEXT_EXTENSIONS = {
    ".ts", ".js", ".mjs", ".svelte", ".py", ".css", ".md",
    ".json", ".sh", ".yml", ".yaml",
}

_EXCLUDED_PREFIXES = (
    "client/dist/",
    "client/vendor/",
    "node_modules/",
    "web/node_modules/",
    "venv/",
    "venv.nosync/",
)


def _tracked_text_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [
        f for f in listed
        if Path(f).suffix in _TEXT_EXTENSIONS
        and not any(f.startswith(p) for p in _EXCLUDED_PREFIXES)
    ]


def test_no_tracked_source_file_contains_a_literal_nul_byte() -> None:
    offenders: list[str] = []
    for rel_path in _tracked_text_files():
        path = REPO_ROOT / rel_path
        try:
            data = path.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            continue
        if b"\x00" in data:
            offenders.append(f"{rel_path} (offset {data.index(b'\x00')})")

    assert offenders == [], (
        "literal NUL byte(s) found in tracked source - escape as \\0 or "
        "\\x00 instead, so the runtime value is unchanged and the file "
        "stays classified as text: " + ", ".join(offenders)
    )


def test_the_detector_can_actually_fail(tmp_path: Path) -> None:
    planted = tmp_path / "planted.ts"
    planted.write_bytes(b"const key = `${a}\x00${b}`;\n")
    assert b"\x00" in planted.read_bytes()

    clean = tmp_path / "clean.ts"
    clean.write_bytes(b"const key = `${a}\\0${b}`;\n")
    assert b"\x00" not in clean.read_bytes()


@pytest.mark.parametrize(
    "rel_path",
    [
        "web/src/lib/plugins/registry.ts",
        "client/js/markdown-lite.js",
    ],
)
def test_the_previously_offending_files_are_clean(rel_path: str) -> None:
    data = (REPO_ROOT / rel_path).read_bytes()
    assert b"\x00" not in data, f"{rel_path} contains a literal NUL byte again"
