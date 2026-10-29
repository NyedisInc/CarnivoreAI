
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TERMINAL_JS = REPO_ROOT / "client" / "js" / "terminal.js"
WEBSOCKET_PY = REPO_ROOT / "src" / "api" / "websocket.py"


def _terminal_src() -> str:
    return TERMINAL_JS.read_text(encoding="utf-8")


def _method_body(src: str, signature: str) -> str:
    marker = "\n    " + signature + " {"
    assert marker in src, f"no method definition for {signature!r}"
    start = src.index(marker)
    open_brace = src.index("{", start)
    depth = 0
    for i in range(open_brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_brace: i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def test_connect_banner_is_not_written_into_the_buffer() -> None:
    src = _terminal_src()
    assert "[Connected to PTY terminal]" not in src
    assert "[Disconnected from terminal]" not in src


def test_server_welcome_frame_is_not_a_terminal_banner() -> None:
    src = WEBSOCKET_PY.read_text(encoding="utf-8")
    assert "[SYSTEM]" not in src
    assert "websocket connected, pty terminal ready" not in src
    assert '"type": "log"' not in src
    assert "failed_to_send_welcome" not in src


def test_ws_message_handler_never_writes_to_the_terminal() -> None:
    body = _method_body(_terminal_src(), "handleWebSocketMessage(message)")
    assert "term.writeln" not in body
    assert "_showStatusPill" in body


def test_socket_lifecycle_reports_through_the_status_ui() -> None:
    body = _method_body(_terminal_src(), "setupWebSocketHandlers()")
    code = "\n".join(
        line for line in body.splitlines()
        if not line.strip().startswith(("//", "*", "/*"))
    )
    assert "term.writeln" not in code
    assert "this.updateStatus('Connected', 'connected')" in body
    assert "this.updateStatus('Disconnected', 'error')" in body
    assert "this._showStatusPill('disconnected', 'error')" in body


def test_reconnect_narration_does_not_interleave_with_pane_content() -> None:
    src = _terminal_src()
    for method in (
        "attemptReconnect()",
        "reconnectByName(",
        "waitForServerAndReconnect(",
    ):
        if method.rstrip("(") + "(" not in src and method not in src:
            continue
        body = _method_body(src, method)
        assert "term.writeln" not in body, f"{method} still writes to the buffer"


def test_remaining_writelns_are_only_empty_buffer_placeholders() -> None:
    allowed = {
        "Carnivore Terminal",
        "Keyboard shortcuts:",
        "= Newline (Enter)",
        "= Tab",
        "= Shift+Tab",
        "Waiting for session...",
        "[Session created - connecting to WebSocket...]",
        "Session destroyed",
        "Session detached",
        "''",
        "'')",
    }
    stray = []
    for line in _terminal_src().splitlines():
        stripped = line.strip()
        if "term.writeln" not in line:
            continue
        if stripped.startswith(("//", "*", "/*")):
            continue
        if not any(token in line for token in allowed):
            stray.append(line.strip())
    assert not stray, "client status written into the pane buffer: " + repr(stray)


def test_notice_copy_is_lowercase() -> None:
    src = _terminal_src()
    for call in re.findall(r"_showStatusPill\(\s*'([^']+)'", src):
        first = call.lstrip("`$ ")[:1]
        assert not first.isupper(), f"notice copy is capitalised: {call!r}"
