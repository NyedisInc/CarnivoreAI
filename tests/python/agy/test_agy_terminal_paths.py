import json
from pathlib import Path

from src.core.agy.path_names import resolve_bare
from src.core.terminal_paths.resolve import resolve


def _transcript(tmp_path: Path, paths: list) -> Path:
    rows = [{"tool_calls": [{"name": "read_file", "args": {"Path": json.dumps(p)}}]} for p in paths]
    out = tmp_path / "transcript.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return out


def test_bare_name_resolves_uniquely_and_ambiguity_does_not(tmp_path):
    (tmp_path / "a" / "deep").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    for rel in ("a/deep/only.py", "a/dup.py", "b/dup.py"):
        (tmp_path / rel).write_text("x")
    t = _transcript(tmp_path, [str(tmp_path / "a/deep/only.py"), str(tmp_path / "a/dup.py"),
                               str(tmp_path / "b/dup.py"), str(tmp_path / "gone.py")])
    got = resolve_bare("only.py:7", t)
    assert got and got.path == str(tmp_path / "a/deep/only.py") and got.line == 7
    assert resolve_bare("dup.py", t) is None
    assert resolve_bare("gone.py", t) is None
    assert resolve_bare("other.py", t) is None
    assert resolve_bare("a/dup.py", t) is None
    assert resolve_bare("only.py", None) is None
    assert resolve("only.py", str(tmp_path)) is None
