
from __future__ import annotations

import hashlib
import io
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.crate_crypto.age import AgeReader, AgeWriter
from src.core.crate_crypto.keys import generate, parse_identity, parse_recipient, recipient_of

logger = logging.getLogger(__name__)
AGE = shutil.which("age")
AGE_KEYGEN = shutil.which("age-keygen")
TIMEOUT_S = 60


@pytest.fixture(autouse=True)
def _need_age():
    if AGE is None or AGE_KEYGEN is None:
        reason = "age CLI not installed (brew install age): interop NOT checked, this is not a pass"
        logger.warning(reason)
        pytest.skip(reason)


def plaintext(size: int) -> bytes:
    out, i = bytearray(), 0
    while len(out) < size:
        out += hashlib.sha256(b"cli:%d" % i).digest()
        i += 1
    return bytes(out[:size])


def key_file(tmp_path: Path, identity: str, name: str = "key.txt") -> Path:
    path = tmp_path / name
    path.touch(mode=0o600)
    path.write_text(identity + "\n", encoding="ascii")
    return path


@pytest.mark.parametrize("size", [0, 65536, 200_000])
def test_age_decrypts_what_we_write(tmp_path, size):
    identity, recipient = generate()
    other_identity, other_recipient = generate()
    data = plaintext(size)
    sealed = tmp_path / "out.age"
    with open(sealed, "wb") as out:
        writer = AgeWriter(out, [parse_recipient(other_recipient), parse_recipient(recipient)])
        writer.write(data)
        writer.close()
    for ident in (identity, other_identity):
        done = subprocess.run([AGE, "-d", "-i", str(key_file(tmp_path, ident)), str(sealed)], capture_output=True,
                              timeout=TIMEOUT_S, check=False)
        assert done.returncode == 0, done.stderr.decode(errors="replace")
        assert done.stdout == data


@pytest.mark.parametrize("size", [0, 1, 65537, 300_000])
def test_we_decrypt_what_age_writes(tmp_path, size):
    identity, recipient = generate()
    data = plaintext(size)
    sealed = tmp_path / "in.age"
    done = subprocess.run([AGE, "-r", recipient, "-o", str(sealed)], input=data, capture_output=True,
                          timeout=TIMEOUT_S, check=False)
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    with open(sealed, "rb") as handle:
        assert AgeReader(handle, [parse_identity(identity)]).read() == data


def test_recipient_of_matches_age_keygen(tmp_path):
    generated = tmp_path / "gen.txt"
    done = subprocess.run([AGE_KEYGEN, "-o", str(generated)], capture_output=True, timeout=TIMEOUT_S, check=False)
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    derived = subprocess.run([AGE_KEYGEN, "-y", str(generated)], capture_output=True, timeout=TIMEOUT_S, check=False)
    assert derived.returncode == 0
    assert recipient_of(generated.read_text(encoding="ascii")) == derived.stdout.decode().strip()
    sealed = io.BytesIO()
    writer = AgeWriter(sealed, [parse_recipient(derived.stdout.decode())])
    writer.write(b"keygen file")
    writer.close()
    identity = parse_identity(generated.read_text(encoding="ascii"))
    assert AgeReader(io.BytesIO(sealed.getvalue()), [identity]).read() == b"keygen file"
