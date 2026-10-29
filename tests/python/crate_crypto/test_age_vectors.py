
from __future__ import annotations

import hashlib
import io
import zlib
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from src.core.crate_crypto.age import CHUNK_BYTES, AgeReader
from src.core.crate_crypto.age_header import header_ok
from src.core.crate_crypto.errors import Corrupt, HeaderMacMismatch, Malformed, WrongKey
from src.core.crate_crypto.keys import parse_identity

KIT = Path(__file__).resolve().parents[2] / "fixtures" / "crate_crypto" / "age-testkit"
NOT_VECTORS = {"LICENSE", "SOURCE.md"}
EXPECTED_VECTORS = 67
EXPECTED_ERROR = {"header failure": Malformed, "no match": WrongKey, "HMAC failure": HeaderMacMismatch, "payload failure": Corrupt}


def load_vector(path: Path) -> Tuple[Dict[str, List[str]], bytes]:
    raw = path.read_bytes()
    head, _, body = raw.partition(b"\n\n")
    keys: Dict[str, List[str]] = {}
    for line in head.decode("utf-8").splitlines():
        key, _, value = line.partition(": ")
        keys.setdefault(key, []).append(value)
    if keys.get("compressed") == ["zlib"]:
        body = zlib.decompress(body)
    return keys, body


def vector_names() -> List[str]:
    return sorted(p.name for p in KIT.iterdir() if p.is_file() and p.name not in NOT_VECTORS)


def decrypt_released(body: bytes, identities: List[bytes]) -> Tuple[bytes, BaseException | None]:
    released = bytearray()
    try:
        reader = AgeReader(io.BytesIO(body), identities)
        while True:
            piece = reader.read(CHUNK_BYTES)
            if not piece:
                return bytes(released), None
            released += piece
    except (Malformed, WrongKey, Corrupt) as exc:
        return bytes(released), exc


def test_the_vendored_kit_is_all_there():
    assert KIT.is_dir()
    assert len(vector_names()) == EXPECTED_VECTORS
    assert (KIT / "LICENSE").is_file() and (KIT / "SOURCE.md").is_file()


@pytest.mark.parametrize("name", vector_names())
def test_vector(name):
    keys, body = load_vector(KIT / name)
    assert not set(keys) & {"passphrase", "armored"}, "an out-of-scope vector was vendored"
    expect = keys["expect"][0]
    identities = [parse_identity(text) for text in keys.get("identity", [])]
    released, error = decrypt_released(body, identities)
    if expect == "success":
        assert error is None, f"{name}: {type(error).__name__}: {error}"
        assert hashlib.sha256(released).hexdigest() == keys["payload"][0]
        return
    assert type(error) is EXPECTED_ERROR[expect], f"{name}: expected {expect}, got {type(error).__name__}: {error}"
    if expect == "payload failure":
        assert hashlib.sha256(released).hexdigest() == keys["payload"][0], f"{name}: wrong bytes released before the error"


@pytest.mark.parametrize("name", vector_names())
def test_header_ok_agrees_with_the_header_grammar(name):
    keys, body = load_vector(KIT / name)
    expect = keys["expect"][0]
    ok = header_ok(io.BytesIO(body))
    needs_more = {"x25519_identity", "x25519_low_order", "stream_no_nonce", "stream_short_nonce"}
    if expect == "header failure" and name not in needs_more:
        assert not ok, name
    else:
        assert ok, name
