
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from src.core.codex_helpers import constants as K

UNAPPROVED = "0381;6afe2b09;;71394CAA-954A-47EF-9BB1-D0FA4C0A57C5"
APPROVED = "03c1;6afe2b09;;71394CAA-954A-47EF-9BB1-D0FA4C0A57C5"

needs_xattr = pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists(K.XATTR_PATH),
                                 reason="quarantine attributes are a macOS feature")

_ANSWERS = '''
import json, os, struct, sys
open(sys.argv[0] + ".pid", "w").write(str(os.getpid()))
head = sys.stdin.buffer.read(4)
size = struct.unpack("<I", head)[0]
hello = json.loads(sys.stdin.buffer.read(size))
assert hello["type"] == "connection/hello"
body = json.dumps({"type": "connection/ready", "version": 1}).encode()
sys.stdout.buffer.write(struct.pack("<I", len(body)) + body)
sys.stdout.buffer.flush()
sys.stdin.buffer.read()
'''

_HANGS = '''
import os, sys, time
open(sys.argv[0] + ".pid", "w").write(str(os.getpid()))
time.sleep(600)
'''


def _script(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


def make_install(root: Path, host: Optional[str] = "answers") -> Path:
    folder = root / "codex" / "0.170.0" / "bin"
    folder.mkdir(parents=True)
    codex = _script(folder / "codex", "print('codex-cli 0.170.0')\n")
    _script(folder / "codex-exec-server", "import time\ntime.sleep(600)\n")
    if host is not None:
        set_host(codex, host)
    return codex


def set_host(codex: Path, behavior: str) -> Path:
    return _script(codex.parent / K.HOST_NAME, _ANSWERS if behavior == "answers" else _HANGS)


def quarantine(path: Path, flag: str) -> None:
    subprocess.run([K.XATTR_PATH, "-w", K.QUARANTINE_ATTR, flag, str(path)], check=True)


def host_pid(codex: Path) -> int:
    return int((codex.parent / (K.HOST_NAME + ".pid")).read_text())


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
