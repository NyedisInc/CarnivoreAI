
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pytest

_TIMEOUT_SECONDS: int = 30

SKIP_REASON: str = "minisign binary not found: brew install minisign"


@dataclass(frozen=True)
class Keypair:

    pub_path: Path
    sec_path: Path
    public_key_text: str


def minisign_binary() -> Optional[str]:
    return shutil.which("minisign")


def require_minisign() -> str:
    found = minisign_binary()
    if found is None:
        pytest.skip(SKIP_REASON)
    return found


def _run(args: List[str]) -> str:
    result = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"minisign exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


def generate_keypair(tmp_path: Path) -> Keypair:
    binary = require_minisign()
    pub_path = tmp_path / "catalog.pub"
    sec_path = tmp_path / "catalog.key"
    _run([
        binary, "-G", "-W", "-f",
        "-p", str(pub_path),
        "-s", str(sec_path),
    ])
    return Keypair(
        pub_path=pub_path,
        sec_path=sec_path,
        public_key_text=pub_path.read_text(),
    )


def sign_file(
    keypair: Keypair, path: Path, trusted_comment: Optional[str] = None,
) -> str:
    binary = require_minisign()
    args = [binary, "-S", "-W", "-s", str(keypair.sec_path), "-m", str(path)]
    if trusted_comment is not None:
        args += ["-t", trusted_comment]
    _run(args)
    return Path(str(path) + ".minisig").read_text()
