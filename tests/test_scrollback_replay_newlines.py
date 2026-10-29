from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sbn_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sbn_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.scrollback_replay import (  # noqa: E402
    normalize_replay_newlines,
    with_cursor_restore,
)
from src.core import tmux_backend as tmux_backend_mod  # noqa: E402



def test_bare_lf_becomes_crlf():
    assert normalize_replay_newlines(b"AAA\nBBB\nCCC") == b"AAA\r\nBBB\r\nCCC"


def test_existing_crlf_is_untouched():
    assert normalize_replay_newlines(b"AAA\r\nBBB\r\n") == b"AAA\r\nBBB\r\n"


def test_normalization_is_idempotent():
    once = normalize_replay_newlines(b"AAA\nBBB\r\nCCC\n")
    assert normalize_replay_newlines(once) == once


def test_mixed_endings_all_land_on_crlf():
    assert (
        normalize_replay_newlines(b"one\ntwo\r\nthree\nfour")
        == b"one\r\ntwo\r\nthree\r\nfour"
    )


def test_lone_carriage_return_is_preserved():
    assert normalize_replay_newlines(b"50%\r100%") == b"50%\r100%"


def test_ansi_escapes_survive():
    src = b"\x1b[1;32mgreen\x1b[0m\nplain\n"
    assert normalize_replay_newlines(src) == b"\x1b[1;32mgreen\x1b[0m\r\nplain\r\n"


def test_empty_input_returns_empty():
    assert normalize_replay_newlines(b"") == b""


def test_no_newlines_is_unchanged():
    assert normalize_replay_newlines(b"single line") == b"single line"



class _StubBackend:

    scrollback_lines = 3000
    tmux_session = "cloude_probe"
    replay_in_progress = False

    def __init__(self, payload: bytes, rc: int = 0):
        self._payload = payload
        self._rc = rc
        self.args: tuple = ()

    def _run_tmux_sync(self, *args, **kwargs):
        self.args = args
        return self._rc, self._payload, b""


def test_capture_scrollback_normalizes_its_output():
    stub = _StubBackend(b"drwxr-xr-x  jsugamele\ntotal 12\n")
    out = tmux_backend_mod.TmuxBackend.capture_scrollback(stub, lines=10)
    assert out == b"drwxr-xr-x  jsugamele\r\ntotal 12\r\n"
    assert b"\n" not in out.replace(b"\r\n", b"")


def test_capture_scrollback_failure_still_returns_empty():
    stub = _StubBackend(b"whatever\n", rc=1)
    assert tmux_backend_mod.TmuxBackend.capture_scrollback(stub, lines=10) == b""


@pytest.mark.parametrize("flag", ["-p", "-e", "-J"])
def test_capture_scrollback_keeps_its_tmux_flags(flag):
    stub = _StubBackend(b"x\n")
    tmux_backend_mod.TmuxBackend.capture_scrollback(stub, lines=10)
    assert flag in stub.args




def test_a_cursor_becomes_a_one_based_absolute_position():
    assert with_cursor_restore(b"body", (5, 2)) == b"body\x1b[3;6H"


def test_the_origin_cell_is_row_one_column_one():
    assert with_cursor_restore(b"body", (0, 0)) == b"body\x1b[1;1H"


def test_no_cursor_appends_nothing_at_all():
    assert with_cursor_restore(b"body", None) == b"body"


def test_an_empty_capture_stays_empty():
    assert with_cursor_restore(b"", (5, 2)) == b""
    assert with_cursor_restore(b"", None) == b""


def test_the_suffix_is_ascii_and_leaves_the_body_untouched():
    body = "héllo\r\n".encode("utf-8")
    out = with_cursor_restore(body, (1, 1))
    assert out.startswith(body)
    assert out[len(body):] == b"\x1b[2;2H"
