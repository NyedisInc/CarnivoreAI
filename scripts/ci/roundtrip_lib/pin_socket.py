#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

PRODUCTION_SOCKET = "cloude"


def pin_socket(config_path: Path, socket: str) -> None:
    if socket == PRODUCTION_SOCKET:
        raise SystemExit("refusing: throwaway socket name resolved to the production socket")
    try:
        data = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("could not read config.json to pin the tmux socket: %s" % exc)
    session = data.setdefault("session", {})
    if session.get("tmux_socket_name") != socket:
        session["tmux_socket_name"] = socket
        config_path.write_text(json.dumps(data, indent=2) + "\n")
    if json.loads(config_path.read_text())["session"]["tmux_socket_name"] != socket:
        raise SystemExit("config.json still does not name the throwaway socket")


def main(argv: list[str]) -> int:
    pin_socket(Path(argv[1]), argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
