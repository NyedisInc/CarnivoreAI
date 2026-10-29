
from __future__ import annotations

import socket
from typing import Dict

CLIENT_NAME = "carnivore-app"


def device_fields() -> Dict[str, str]:
    try:
        label = socket.gethostname()
    except OSError:
        label = ""
    return {"client": CLIENT_NAME, "label": label}
