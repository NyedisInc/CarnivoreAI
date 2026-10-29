
from __future__ import annotations

import base64
import dataclasses
import hashlib
from pathlib import Path

import pytest
import structlog.testing

from src.core.catalog.minisign import (
    ALG_PREHASHED,
    MinisignFormatError,
    PublicKey,
    Signature,
    format_key_id,
    parse_public_key,
    parse_signature,
    verify,
)
from tests.helpers import minisign_keys
from tests.helpers.minisign_keys import (
    SKIP_REASON,
    Keypair,
    generate_keypair,
    require_minisign,
    sign_file,
)

MESSAGE = b"carnivore-release-v1\nskill\nadam\nwork\n"

TRUSTED_COMMENT = "serial:7 generated_at:2026-09-15T00:00:00Z"


@pytest.fixture()
def keypair(tmp_path: Path) -> Keypair:
    return generate_keypair(tmp_path)


@pytest.fixture()
def signed(tmp_path: Path, keypair: Keypair) -> str:
    target = tmp_path / "index.json"
    target.write_bytes(MESSAGE)
    return sign_file(keypair, target, TRUSTED_COMMENT)


def test_a_signature_from_the_real_binary_verifies(keypair, signed):
    assert verify(
        MESSAGE, parse_signature(signed), parse_public_key(
            keypair.public_key_text
        ), expect_prehashed=True,
    ) is True


def test_the_algorithm_minisign_emits_is_the_prehashed_one(signed):
    signature = parse_signature(signed)
    assert signature.prehashed is True
    assert base64.b64decode(signed.splitlines()[1])[:2] == ALG_PREHASHED


def test_a_downgraded_algorithm_marker_cannot_forge_a_verdict(keypair, signed):
    public_key = parse_public_key(keypair.public_key_text)
    digest = hashlib.blake2b(MESSAGE, digest_size=64).digest()
    downgraded = dataclasses.replace(parse_signature(signed), prehashed=False)

    assert verify(
        digest, downgraded, public_key, expect_prehashed=True,
    ) is False
    assert verify(
        digest, downgraded, public_key, expect_prehashed=False,
    ) is True, (
        "control: those 64 digest bytes ARE validly signed under the raw "
        "construction, so the refusal above is the algorithm binding and "
        "nothing else"
    )


def test_the_expected_algorithm_is_checked_in_both_directions(keypair, signed):
    assert verify(
        MESSAGE, parse_signature(signed), parse_public_key(
            keypair.public_key_text
        ), expect_prehashed=False,
    ) is False


def test_the_algorithm_mismatch_says_so_in_the_log(keypair, signed):
    with structlog.testing.capture_logs() as captured:
        assert verify(
            MESSAGE, parse_signature(signed), parse_public_key(
                keypair.public_key_text
            ), expect_prehashed=False,
        ) is False
    line = next(
        entry for entry in captured
        if entry["event"] == "minisign_algorithm_mismatch"
    )
    assert line["expected_algorithm"] != line["actual_algorithm"]


def test_expect_prehashed_is_required_and_has_no_default(keypair, signed):
    with pytest.raises(TypeError):
        verify(
            MESSAGE, parse_signature(signed), parse_public_key(
                keypair.public_key_text
            ),
        )


def test_one_flipped_message_byte_fails(keypair, signed):
    tampered = bytearray(MESSAGE)
    tampered[0] ^= 0x01
    assert verify(
        bytes(tampered), parse_signature(signed), parse_public_key(
            keypair.public_key_text
        ), expect_prehashed=True,
    ) is False


def test_a_vector_whose_only_mutation_is_the_trusted_comment_fails(
    keypair, signed,
):
    original = parse_signature(signed)
    mutated = dataclasses.replace(
        original, trusted_comment="serial:99999 generated_at:2099-01-01T00:00:00Z"
    )
    public_key = parse_public_key(keypair.public_key_text)

    assert verify(MESSAGE, original, public_key, expect_prehashed=True) is True
    assert verify(MESSAGE, mutated, public_key, expect_prehashed=True) is False
    assert mutated.sig == original.sig, (
        "control: the message signature bytes must be unchanged, or this "
        "test proves something other than the global signature check"
    )


def test_a_different_key_fails_and_does_not_raise(tmp_path, keypair, signed):
    other = generate_keypair(tmp_path / "other")
    assert other.public_key_text != keypair.public_key_text, (
        "control: two generated keypairs must actually differ"
    )
    assert verify(
        MESSAGE, parse_signature(signed), parse_public_key(
            other.public_key_text
        ), expect_prehashed=True,
    ) is False


def test_a_forged_key_id_still_fails_on_the_mathematics(
    tmp_path, keypair, signed,
):
    other = generate_keypair(tmp_path / "other")
    signature = parse_signature(signed)
    impostor = dataclasses.replace(
        parse_public_key(other.public_key_text), key_id=signature.key_id,
    )
    assert verify(MESSAGE, signature, impostor, expect_prehashed=True) is False


def test_a_key_id_mismatch_is_refused_before_the_mathematics(keypair, signed):
    public_key = parse_public_key(keypair.public_key_text)
    signature = dataclasses.replace(
        parse_signature(signed), key_id="0" * 16,
    )
    assert verify(
        MESSAGE, signature, public_key, expect_prehashed=True,
    ) is False


def test_the_public_key_id_is_the_hex_minisign_printed(keypair):
    comment = keypair.public_key_text.splitlines()[0]
    printed = comment.rsplit(" ", 1)[1].strip()
    assert len(printed) == 16
    assert parse_public_key(keypair.public_key_text).key_id == printed


def test_a_bare_base64_line_parses_as_a_public_key(keypair):
    text = keypair.public_key_text
    bare = text.splitlines()[1]
    assert parse_public_key(bare) == parse_public_key(text)


def test_from_index_fields_round_trips_from_a_minisig(keypair, signed):
    lines = signed.splitlines()
    from_file = parse_signature(signed)
    from_index = Signature.from_index_fields(
        key_id=from_file.key_id,
        sig_b64=lines[1],
        trusted_comment=TRUSTED_COMMENT,
        global_sig_b64=lines[3],
    )
    assert from_index == from_file
    assert verify(
        MESSAGE, from_index, parse_public_key(keypair.public_key_text),
        expect_prehashed=True,
    ) is True


def test_from_index_fields_refuses_a_key_id_that_disagrees(signed):
    lines = signed.splitlines()
    with pytest.raises(MinisignFormatError):
        Signature.from_index_fields(
            key_id="0" * 16,
            sig_b64=lines[1],
            trusted_comment=TRUSTED_COMMENT,
            global_sig_b64=lines[3],
        )


@pytest.mark.parametrize(
    "text",
    [
        "untrusted comment: x\nnot base64 at all!!\n",
        "untrusted comment: x\n",
        "",
    ],
    ids=["bad-base64", "comment-only", "empty"],
)
def test_a_malformed_public_key_raises_rather_than_returning_false(text):
    with pytest.raises(MinisignFormatError):
        parse_public_key(text)


def test_a_public_key_of_the_wrong_length_is_refused():
    with pytest.raises(MinisignFormatError):
        parse_public_key(base64.b64encode(b"Ed" + b"\x00" * 20).decode())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda lines: lines[:3],
        lambda lines: [lines[0], "!!!not base64!!!", lines[2], lines[3]],
        lambda lines: [lines[0], lines[1], "comment: wrong", lines[3]],
        lambda lines: [lines[0], lines[1], lines[2], "!!!"],
    ],
    ids=["three-lines", "bad-signature-base64", "no-trusted-comment",
         "bad-global-base64"],
)
def test_a_malformed_signature_file_raises(signed, mutate):
    with pytest.raises(MinisignFormatError):
        parse_signature("\n".join(mutate(signed.splitlines())) + "\n")


def test_an_unknown_algorithm_is_refused_not_assumed_raw(signed):
    lines = signed.splitlines()
    blob = bytearray(base64.b64decode(lines[1]))
    blob[0:2] = b"Zz"
    lines[1] = base64.b64encode(bytes(blob)).decode()
    with pytest.raises(MinisignFormatError):
        parse_signature("\n".join(lines) + "\n")


def test_format_key_id_refuses_a_wrong_length():
    with pytest.raises(MinisignFormatError):
        format_key_id(b"\x00" * 7)


def test_verify_refuses_a_public_key_that_is_not_ed25519_sized(signed):
    signature = parse_signature(signed)
    stunted = PublicKey(key_id=signature.key_id, raw=b"\x00" * 31)
    with pytest.raises(MinisignFormatError):
        verify(MESSAGE, signature, stunted, expect_prehashed=True)


def test_the_absent_binary_path_skips_with_the_install_command(monkeypatch):
    monkeypatch.setattr(minisign_keys, "minisign_binary", lambda: None)
    with pytest.raises(pytest.skip.Exception) as caught:
        require_minisign()
    assert "brew install minisign" in str(caught.value)
    assert str(caught.value) == SKIP_REASON
