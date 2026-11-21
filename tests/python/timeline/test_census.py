
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Set

import pytest

from src.core.timeline import mapping
from src.core.timeline.extract import HANDLERS
from src.core.timeline.model import Kind
from tests.python.timeline.conftest import FIXTURES, UNKNOWN_FIXTURE, run_fixture

PACKAGE = Path(__file__).resolve().parents[3] / "src" / "core" / "timeline"
REPO = PACKAGE.parents[2]


def _keys(entry: Dict[str, Any]) -> Set[str]:
    return {mapping.census_key(record) for record, _events in run_fixture(entry)}


def _unplaced(manifest: Dict[str, Dict[str, Any]]) -> Set[str]:
    keys: Set[str] = set()
    for name, entry in manifest.items():
        if name != UNKNOWN_FIXTURE:
            keys |= _keys(entry)
    return {key for key in keys if mapping.classify(key) == mapping.UNKNOWN_CLASS}


def test_every_fixture_key_is_mapped_or_ignored(manifest: Dict[str, Dict[str, Any]]) -> None:
    assert _unplaced(manifest) == set()


def test_the_manifest_census_keys_are_honest(manifest: Dict[str, Dict[str, Any]]) -> None:
    for name, entry in manifest.items():
        assert _keys(entry) == set(entry["census_keys"]), name


def test_a_deleted_row_turns_the_census_red(manifest: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    assert _unplaced(manifest) == set()
    monkeypatch.delitem(mapping.MAPPED, "system|turn_duration|")  # type: ignore[attr-defined]
    assert _unplaced(manifest) == {"system|turn_duration|"}


def test_unnamed_kinds_become_one_unknown_event_each(manifest: Dict[str, Dict[str, Any]]) -> None:
    rows = run_fixture(manifest[UNKNOWN_FIXTURE])
    assert [mapping.classify(mapping.census_key(record)) for record, _ in rows] == [mapping.UNKNOWN_CLASS] * 3
    events = [event for _record, produced in rows for event in produced]
    assert [event.kind for event in events] == [Kind.UNKNOWN] * 3
    assert {event.level for event in events} == {4}


def test_every_mapped_key_has_a_rule_and_only_emits_its_declared_kinds(manifest: Dict[str, Dict[str, Any]]) -> None:
    assert set(HANDLERS) == set(mapping.MAPPED)
    for name, entry in manifest.items():
        if name == UNKNOWN_FIXTURE:
            continue
        for record, events in run_fixture(entry):
            key = mapping.census_key(record)
            if mapping.classify(key) == mapping.IGNORED_CLASS:
                assert events == [], key
            else:
                assert {event.kind for event in events} <= set(mapping.mapped_kinds(key)), (name, key)


def test_the_ignored_keys_are_not_also_mapped() -> None:
    assert not set(mapping.IGNORED) & set(mapping.MAPPED)
    assert not mapping.IGNORED_ATTACHMENT_KINDS & {k.split("||")[1] for k in mapping.MAPPED if k.startswith("attachment||")}


def _imports(path: Path) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{alias.name}" for alias in node.names}
    return names


def test_no_module_under_timeline_imports_tmux() -> None:
    for path in sorted(PACKAGE.glob("*.py")):
        assert not [name for name in _imports(path) if "tmux" in name.lower()], path.name
    code = (
        "import sys, pkgutil, importlib, src.core.timeline as p\n"
        "[importlib.import_module('src.core.timeline.' + m.name) for m in pkgutil.iter_modules(p.__path__)]\n"
        "print(json.dumps([m for m in sys.modules if 'tmux' in m.lower()]))"
    )
    done = subprocess.run([sys.executable, "-c", "import json\n" + code], cwd=REPO, capture_output=True, text=True,
                          timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1]) == []


def test_no_event_carries_conversation_text(manifest: Dict[str, Dict[str, Any]]) -> None:
    texts: Set[str] = set()
    dumped = []
    for entry in manifest.values():
        for record, events in run_fixture(entry):
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            content = message.get("content")
            parts = [content] if isinstance(content, str) else [b for b in (content or []) if isinstance(b, dict)]
            for part in parts:
                values = [part] if isinstance(part, str) else [part.get("text"), part.get("thinking")]
                texts |= {v for v in values if isinstance(v, str) and len(v) >= 8}
            attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
            results = [b.get("content") for b in (content if isinstance(content, list) else [])
                       if isinstance(b, dict) and b.get("type") == "tool_result"]
            results += [x.get("text") for r in results if isinstance(r, list) for x in r if isinstance(x, dict)]
            candidates = [record.get("content"), record.get("prompt"), attachment.get("prompt"), *results]
            texts |= {v for v in candidates if isinstance(v, str) and len(v) >= 8}
            dumped += [event.model_dump_json() for event in events]
    assert texts, "the fixtures hold no text to look for"
    blob = "\n".join(dumped)
    assert not [text for text in texts if _leaks(text, blob)]
    assert FIXTURES.is_dir()


LEAK_WINDOW = 24


def _leaks(text: str, blob: str) -> bool:
    if len(text) <= LEAK_WINDOW:
        return text in blob
    return any(text[i:i + LEAK_WINDOW] in blob for i in range(len(text) - LEAK_WINDOW + 1))


def test_the_leak_check_catches_a_truncated_copy() -> None:
    text = "a long conversation text that is cut short by some field"
    assert _leaks(text, '{"name":"a long conversation text that is c"}')
    assert not _leaks(text, '{"name":"unrelated"}')
