
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

ALLOWED = {"config_writer.py"}

WRITE_MARKERS = re.compile(r"os\.replace\(|\.suffix \+ \"\.bak\"|\.suffix \+ '\.bak'")

CONFIG_TARGETS = re.compile(r"config_path|config\.json")


def _python_files():
    return sorted(path for path in SRC.rglob("*.py") if path.name not in ALLOWED)


def test_only_config_writer_performs_a_config_json_write():
    offenders = []
    for path in _python_files():
        lines = path.read_text().splitlines()
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#") or not WRITE_MARKERS.search(line):
                continue
            window = "\n".join(lines[max(0, number - 25) : number + 2])
            if CONFIG_TARGETS.search(window):
                offenders.append(f"{path.relative_to(SRC.parent)}:{number}: {stripped}")

    assert not offenders, (
        "these lines write config.json outside src/core/config_writer.py:\n  "
        + "\n  ".join(offenders)
        + "\n\nEvery config.json writer goes through config_writer.commit(), or "
        "two of them arriving together lose one of the two updates."
    )


def test_the_boundary_itself_still_carries_the_write_pattern():
    source = (SRC / "core" / "config_writer.py").read_text()
    backup = source.index('.suffix + ".bak"')
    fsync = source.index("os.fsync(")
    replace = source.index("os.replace(")

    assert backup < fsync < replace, (
        "the write sequence must stay .bak of the pre-write bytes, then temp "
        "file, then fsync, then os.replace"
    )
