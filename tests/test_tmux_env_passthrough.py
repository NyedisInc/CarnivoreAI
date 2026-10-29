
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import ast


def _start_source() -> str:
    tree = ast.parse((ROOT / "src/core/tmux_backend.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "start":
            return ast.get_source_segment(
                (ROOT / "src/core/tmux_backend.py").read_text(), node
            ) or ""
    raise AssertionError("TmuxBackend.start not found")


def test_the_env_overlay_is_emitted_as_dash_e_pairs():
    src = _start_source()
    assert 'args.extend(["-e", f"{key}={text}"])' in src, (
        "the caller's env overlay is no longer emitted as -e pairs; without "
        "that, every session after the first inherits the SERVER's stale copy"
    )


def test_only_the_callers_keys_travel_not_the_whole_environment():
    src = _start_source()
    assert "for key, value in sorted((env or {}).items()):" in src
    assert "for key, value in sorted(tmux_env.items())" not in src


def test_the_stale_premise_comment_is_gone():
    src = _start_source()
    if "tmux captures the environment of the" in src:
        assert "true only when this" in src or "THE COMMENT THAT USED TO BE HERE" in src, (
            "the wrong premise is stated without its correction"
        )


def test_a_value_with_a_newline_is_skipped_not_truncated():
    src = _start_source()
    assert 'if "\\n" in text or "\\r" in text' in src
    assert "tmux_env_pair_skipped" in src


def test_the_locale_still_travels_as_dash_e():
    src = _start_source()
    assert 'args.extend(["-e", f"LANG={pane_lang}"])' in src
