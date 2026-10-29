
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.core.session_label import APP_TMUX_PREFIX, LABEL_MAX_CHARS

_RESOLVER = Path(__file__).resolve().parents[1] / "client" / "js" / "session-label.js"


def _js_source() -> str:
    return _RESOLVER.read_text(encoding="utf-8")


def _js_var(name: str) -> str:
    hits = re.findall(
        r"^\s*var\s+" + re.escape(name) + r"\s*=\s*([^;]+);",
        _js_source(),
        re.MULTILINE,
    )
    assert hits, f"no `var {name} = ...;` declaration in {_RESOLVER.name}"
    assert len(hits) == 1, f"{name} declared {len(hits)} times in {_RESOLVER.name}"
    return hits[0].strip()


def test_label_max_chars_matches_server() -> None:
    assert int(_js_var("LABEL_MAX_CHARS")) == LABEL_MAX_CHARS


def test_app_tmux_prefix_matches_server() -> None:
    assert _js_var("APP_TMUX_PREFIX").strip("'\"") == APP_TMUX_PREFIX


def test_extractor_rejects_a_name_it_cannot_find() -> None:
    with pytest.raises(AssertionError):
        _js_var("NO_SUCH_CONSTANT_DECLARED_ANYWHERE")
