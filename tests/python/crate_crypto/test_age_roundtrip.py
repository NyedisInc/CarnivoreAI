
from __future__ import annotations

import ast
import hashlib
import io
import random
import tarfile
from pathlib import Path
from typing import List, Tuple

import pytest

from src.core.crate_crypto.age import CHUNK_BYTES, SEALED_CHUNK_BYTES, AgeReader, AgeWriter
from src.core.crate_crypto.age_header import b64encode, parse_header
from src.core.crate_crypto.errors import Corrupt, HeaderMacMismatch, KeyFormatError, Malformed, WrongKey
from src.core.crate_crypto.keys import generate, parse_identity, parse_recipient

SRC = Path(__file__).resolve().parents[3] / "src"
MiB = 1024 * 1024


def keypairs(n: int) -> List[Tuple[bytes, bytes]]:
    pairs = []
    for _ in range(n):
        identity, recipient = generate()
        pairs.append((parse_identity(identity), parse_recipient(recipient)))
    return pairs


def plaintext(size: int) -> bytes:
    out, i = bytearray(), 0
    while len(out) < size:
        out += hashlib.sha256(b"pt:%d" % i).digest()
        i += 1
    return bytes(out[:size])


def encrypt(data: bytes, recipients: List[bytes], pieces: int = 7) -> bytes:
    out = io.BytesIO()
    writer = AgeWriter(out, recipients)
    step = max(1, len(data) // pieces + 1)
    for start in range(0, len(data), step):
        writer.write(data[start:start + step])
    writer.close()
    return out.getvalue()


def read_all(blob: bytes, identity: bytes) -> bytes:
    return AgeReader(io.BytesIO(blob), [identity]).read()


@pytest.fixture(scope="module")
def three() -> List[Tuple[bytes, bytes]]:
    return keypairs(3)


@pytest.mark.parametrize("size", [0, 1, 65535, 65536, 65537, 5 * MiB])
def test_round_trip_every_identity_opens(size, three):
    data = plaintext(size)
    blob = encrypt(data, [r for _, r in three])
    for identity, _ in three:
        reader = AgeReader(io.BytesIO(blob), [identity])
        assert reader.size == size
        assert reader.read() == data


def test_seek_reads_at_random_offsets(three):
    data = plaintext(5 * MiB + 123)
    reader = AgeReader(io.BytesIO(encrypt(data, [three[0][1]])), [three[0][0]])
    rng = random.Random(1912)
    for _ in range(50):
        start = rng.randrange(0, len(data))
        length = rng.randrange(1, 3 * CHUNK_BYTES)
        reader.seek(start)
        assert reader.read(length) == data[start:start + length]
    reader.seek(-10, io.SEEK_END)
    assert reader.read(10) == data[-10:]


def test_truncation_at_a_chunk_boundary_is_corrupt(three):
    identity, recipient = three[0]
    data = plaintext(3 * CHUNK_BYTES + 100)
    blob = encrypt(data, [recipient])
    header_len = parse_header(blob[:65536]).length
    cut = blob[:header_len + 16 + 2 * SEALED_CHUNK_BYTES]
    reader = AgeReader(io.BytesIO(cut), [identity])
    assert reader.read(2 * CHUNK_BYTES) == data[:2 * CHUNK_BYTES]
    with pytest.raises(Corrupt):
        reader.read(1)
    with pytest.raises(Corrupt):
        read_all(blob[:-1], identity)


def test_a_flipped_payload_byte_is_corrupt(three):
    identity, recipient = three[0]
    blob = bytearray(encrypt(plaintext(200_000), [recipient]))
    blob[-70_000] ^= 0x01
    with pytest.raises(Corrupt):
        read_all(bytes(blob), identity)


def test_a_flipped_header_byte_is_refused(three):
    identity, recipient = three[0]
    blob = encrypt(b"header test", [recipient])
    header_len = parse_header(blob).length
    for position in range(header_len):
        changed = bytearray(blob)
        changed[position] ^= 0x01
        with pytest.raises((WrongKey, Malformed, HeaderMacMismatch)):
            read_all(bytes(changed), identity)


def test_21_stanzas_are_malformed(three):
    pairs = keypairs(20)
    blob = encrypt(b"x", [r for _, r in pairs])
    lines = blob.split(b"\n")
    first_stanza = b"\n".join(lines[1:3]) + b"\n"
    head_end = blob.index(b"\n") + 1
    padded = blob[:head_end] + first_stanza + blob[head_end:]
    with pytest.raises(Malformed):
        read_all(padded, pairs[0][0])
    with pytest.raises(KeyFormatError):
        encrypt(b"x", [r for _, r in pairs] + [three[0][1]])


def test_an_all_zero_share_is_malformed(three):
    identity, recipient = three[0]
    blob = encrypt(b"zero", [recipient])
    share = blob.split(b"\n")[1].split(b" ")[2]
    with pytest.raises(Malformed):
        read_all(blob.replace(share, b64encode(bytes(32)), 1), identity)


def test_another_identity_is_wrong_key(three):
    blob = encrypt(b"secret", [three[0][1]])
    with pytest.raises(WrongKey):
        AgeReader(io.BytesIO(blob), [three[1][0]])
    with pytest.raises(WrongKey):
        AgeReader(io.BytesIO(blob), [])


def test_tarfile_random_access_over_the_reader(three):
    identity, recipient = three[0]
    members = {"CRATE": b"carnivore-crate 1\n", "blobs/big.bin": plaintext(300_000), "z.txt": b"last"}
    plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    blob = encrypt(plain.getvalue(), [recipient])
    with tarfile.open(fileobj=AgeReader(io.BytesIO(blob), [identity]), mode="r:") as tar:
        assert tar.getnames() == list(members)
        assert tar.extractfile("z.txt").read() == b"last"
        assert tar.extractfile("blobs/big.bin").read() == members["blobs/big.bin"]


def test_an_exception_in_the_writer_aborts_instead_of_sealing(three):
    identity, recipient = three[0]
    out = io.BytesIO()
    with pytest.raises(RuntimeError):
        with AgeWriter(out, [recipient]) as writer:
            writer.write(plaintext(100_000))
            raise RuntimeError("export failed")
    with pytest.raises(Corrupt):
        read_all(out.getvalue(), identity)


def test_a_fixed_rng_gives_identical_bytes(three):
    counter = {"n": 0}

    def rng(n: int) -> bytes:
        counter["n"] += 1
        return hashlib.sha256(b"rng:%d" % counter["n"]).digest()[:n]

    def build() -> bytes:
        counter["n"] = 0
        out = io.BytesIO()
        writer = AgeWriter(out, [three[0][1]], _rng=rng)
        writer.write(b"same")
        writer.close()
        return out.getvalue()

    assert build() == build()
    assert read_all(build(), three[0][0]) == b"same"


def test_no_production_module_passes_the_private_rng():
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and any(k.arg == "_rng" for k in node.keywords):
                offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno}")
    assert offenders == []


def test_the_rng_scan_can_go_red():
    tree = ast.parse("AgeWriter(out, keys, _rng=lambda n: bytes(n))")
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and any(k.arg == "_rng" for k in n.keywords)]
    assert len(calls) == 1
