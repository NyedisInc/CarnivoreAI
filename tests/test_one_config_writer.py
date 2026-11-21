
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

ALLOWED = {"config_writer.py"}

WRITE_MARKERS = re.compile(
    r"os\.replace\(|\.suffix \+ \"\.bak\"|\.suffix \+ '\.bak'"
    r"|open\([^)]*,\s*[\"']w[b+]?[\"']"
    r"|\.write_text\(|json\.dump\(|atomic_write\("
)

CONFIG_TARGETS = re.compile(r"config_path|config\.json")


def _python_files(root: Path = SRC):
    return sorted(path for path in root.rglob("*.py") if path.name not in ALLOWED)


def _docstring_lines(source: str) -> set[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    covered: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            covered.update(range(node.lineno, node.end_lineno + 1))
    return covered


def find_config_writes(root: Path = SRC) -> list[str]:
    offenders = []
    for path in _python_files(root):
        text = path.read_text()
        lines = text.splitlines()
        prose = _docstring_lines(text)
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#") or number in prose or not WRITE_MARKERS.search(line):
                continue
            window = "\n".join(lines[max(0, number - 25) : number + 2])
            if CONFIG_TARGETS.search(window):
                offenders.append(f"{path.name}:{number}: {stripped}")
    return offenders


def test_guard_goes_red_on_a_plain_write_text_fixture(tmp_path):
    (tmp_path / "bad_a.py").write_text(
        "def f(config_path, data):\n    config_path.write_text(json.dumps(data))\n"
    )
    (tmp_path / "bad_b.py").write_text(
        "def f(config_path, data):\n    with open(config_path, 'w') as h:\n        json.dump(data, h)\n"
    )
    (tmp_path / "bad_c.py").write_text(
        "def f(config_path, doc):\n    atomic_write(config_path, doc)\n"
    )
    (tmp_path / "good.py").write_text("def f(path):\n    return path.read_text()\n")
    found = find_config_writes(tmp_path)
    assert any("bad_a.py" in x for x in found)
    assert any("bad_b.py" in x for x in found)
    assert any("bad_c.py" in x for x in found)
    assert not any("good.py" in x for x in found)


def test_only_config_writer_performs_a_config_json_write():
    offenders = find_config_writes()

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
