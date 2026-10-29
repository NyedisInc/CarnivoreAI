
from __future__ import annotations


def pane_row(name: str, dead: str = "0", command: str = "claude", pid: int = 111, created: int = 1755000000,
             pane_id: str = "%1", folder: str = "/tmp", stamp: str = "1755000001|80|24|1|1") -> str:
    return (f"{dead}|{pid}|{created}|{pane_id}|{stamp}|{len(name.encode())}|{len(command.encode())}"
            f"|{name}|{command}|{folder}\n")
