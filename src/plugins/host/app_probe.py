
from __future__ import annotations

import socket

PROBE_TIMEOUT_S = 0.5


def app_answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False
