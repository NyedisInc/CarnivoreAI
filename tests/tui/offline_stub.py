
from __future__ import annotations

import json
import os
import shlex
import socket
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.socket_guard import TEST_SOCKET_NAME

STUB_SOURCE = '''import json, os, sys
argv = sys.argv
with open(os.environ["OFFLINE_STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\\n")
table = json.load(open(os.environ["OFFLINE_STUB_TABLE"], encoding="utf-8"))
i = 1
while i < len(argv) and argv[i] in ("-S", "-L", "-f"):
    i += 2
word = argv[i] if i < len(argv) else ""
out, err, rc = table.get(word, ["", "unknown command: " + word, 1])
sys.stdout.write(out)
sys.stderr.write(err)
sys.exit(rc)
'''


@dataclass
class Stub:

    binary: str
    socket_path: str
    uid_dir: Path
    root: Path
    table_path: Path
    log_path: Path

    def answer(self, table: dict[str, Any]) -> None:
        self.table_path.write_text(json.dumps(table), encoding="utf-8")

    def calls(self) -> list[list[str]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]


def make_stub(monkeypatch: Any) -> Stub:
    short = tempfile.mkdtemp(prefix="off")
    root = Path(os.path.realpath(short))
    bindir = root / "bin"
    bindir.mkdir()
    program = bindir / "stub_tmux.py"
    program.write_text(STUB_SOURCE, encoding="utf-8")
    binary = bindir / "tmux"
    binary.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(program))} "$@"\n', encoding="utf-8")
    binary.chmod(stat.S_IRWXU)
    uid_dir = root / f"tmux-{os.getuid()}"
    uid_dir.mkdir(mode=0o700)
    uid_dir.chmod(0o700)
    sock_path = uid_dir / TEST_SOCKET_NAME
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(os.path.join(short, uid_dir.name, TEST_SOCKET_NAME))
    server.close()
    stub = Stub(str(binary), str(sock_path), uid_dir, root, root / "table.json", root / "log.jsonl")
    stub.answer({})
    monkeypatch.setenv("OFFLINE_STUB_TABLE", str(stub.table_path))
    monkeypatch.setenv("OFFLINE_STUB_LOG", str(stub.log_path))
    monkeypatch.delenv("TMUX_TMPDIR", raising=False)
    return stub

