
from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_trm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_trm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.models import WSMessageType, WSTerminalReadyMessage  # noqa: E402

WEBSOCKET_SRC = (ROOT / "src" / "api" / "websocket.py").read_text()




def test_the_type_string_lives_in_the_one_message_enum() -> None:
    assert WSMessageType.TERMINAL_READY == "terminal.ready"


def test_the_message_serialises_to_the_wire_shape_the_client_reads() -> None:
    msg = WSTerminalReadyMessage(startup_command="none")
    assert msg.model_dump() == {
        "type": "terminal.ready",
        "startup_command": "none",
    }


def test_an_unstated_startup_outcome_defaults_to_unknown_not_none() -> None:
    assert WSTerminalReadyMessage().startup_command == "unknown"




def _handler_source() -> str:
    tree = ast.parse(WEBSOCKET_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and "websocket" in node.name:
            seg = ast.get_source_segment(WEBSOCKET_SRC, node)
            if seg and "REQUEST_DIMS" in seg:
                return seg
    raise AssertionError("no websocket endpoint carrying the dims handshake")


def test_ready_is_sent_AFTER_the_paint_and_AFTER_the_startup_command() -> None:
    body = _handler_source()
    ready = body.index("WSTerminalReadyMessage(")
    assert body.index("paint_on_attach(") < ready, (
        "readiness must not be claimed before the pane's screen is painted")
    assert body.index("flush_pending_login") < ready, (
        "readiness must not be claimed before the configured command is issued")


def test_ready_is_sent_exactly_once_per_socket() -> None:
    assert WEBSOCKET_SRC.count("WSTerminalReadyMessage(") == 1


def test_ready_is_sent_on_every_startup_outcome_including_the_failures() -> None:
    body = _handler_source()
    guards = [
        node for node in ast.walk(ast.parse(body))
        if isinstance(node, ast.If)
        and "flush_pending_login" in (
            ast.get_source_segment(body, node.test) or "")
    ]
    assert len(guards) == 1, "the startup-command guard moved or was duplicated"
    inside = ast.get_source_segment(body, guards[0]) or ""
    assert "WSTerminalReadyMessage(" not in inside, (
        "the readiness send is nested inside the startup-command guard, so a "
        "session with no configured command - the overwhelming majority - is "
        "never told it can take input")


def test_the_ADDITIVE_contract_holds_nothing_waits_on_the_client() -> None:
    body = _handler_source()
    after = body[body.index("WSTerminalReadyMessage("):]
    tail = after[:after.index("asyncio.create_task(")]
    assert "websocket.receive" not in tail, (
        "the server waits for something after announcing readiness, which "
        "would hang every client that does not know to answer")
    assert "wait_for" not in tail


def test_a_client_that_left_mid_paint_does_not_break_the_handler() -> None:
    body = _handler_source()
    after = body[body.index("WSTerminalReadyMessage("):]
    guard = after[:after.index("except WebSocketDisconnect") + 200]
    assert "except WebSocketDisconnect" in guard
    assert "except Exception" not in guard, (
        "a blanket catch around the readiness send would hide a broken message")
