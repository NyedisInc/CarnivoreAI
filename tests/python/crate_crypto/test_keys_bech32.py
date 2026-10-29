
from __future__ import annotations

import pytest

from src.core.crate_crypto import bech32
from src.core.crate_crypto.errors import KeyFormatError
from src.core.crate_crypto.keys import encode_identity, encode_recipient, generate, parse_identity, parse_recipient, recipient_of

BIP173_VALID = [
    "A12UEL5L",
    "a12uel5l",
    "an83characterlonghumanreadablepartthatcontainsthenumber1andtheexcludedcharactersbio1tt5tgs",
    "abcdef1qpzry9x8gf2tvdw0s3jn54khce6mua7lmqqqxw",
    "11qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqc8247j",
    "split1checkupstagehandshakeupstreamerranterredcaperred2y9e3w",
    "?1ezyfcl",
]
BIP173_INVALID = [
    "\x201nwldj5",
    "\x7f1axkwrx",
    "pzry9x0s0muk",
    "1pzry9x0s0muk",
    "x1b4n0q5v",
    "li1dgmt3",
    "de1lg7wt\xff",
    "A1G7SGD8",
    "10a06t8",
    "1qzzfhee",
    "aBcDeF1qpzry9x8gf2tvdw0s3jn54khce6mua7lmqqqxw",
]


@pytest.mark.parametrize("text", BIP173_VALID)
def test_bip173_valid_strings_decode_and_re_encode(text):
    hrp, data = bech32.decode(text)
    assert hrp == text.lower()[: text.lower().rfind("1")]
    assert bech32.decode(bech32.encode(hrp, data)) == (hrp, data)


def test_no_length_cap():
    long = bech32.encode("age1pq", bytes(range(256)) * 4)
    assert len(long) > 1000
    assert bech32.decode(long) == ("age1pq", bytes(range(256)) * 4)


def test_bip173_data_round_trips_exactly():
    for size in (0, 1, 2, 5, 31, 32, 33, 64):
        data = bytes(range(size))
        assert bech32.decode(bech32.encode("test", data)) == ("test", data)


@pytest.mark.parametrize("text", BIP173_INVALID)
def test_bip173_invalid_strings_are_refused(text):
    with pytest.raises(ValueError):
        bech32.decode(text)


def test_a_flipped_character_breaks_the_checksum():
    good = bech32.encode("age", bytes(32))
    for i in range(len("age1"), len(good)):
        swapped = good[:i] + ("q" if good[i] != "q" else "p") + good[i + 1:]
        with pytest.raises(ValueError):
            bech32.decode(swapped)


def test_generated_keys_parse_and_match():
    identity, recipient = generate()
    assert identity.startswith("AGE-SECRET-KEY-1") and identity == identity.upper()
    assert recipient.startswith("age1") and recipient == recipient.lower()
    assert len(parse_identity(identity)) == 32 and len(parse_recipient(recipient)) == 32
    assert recipient_of(identity) == recipient
    assert encode_identity(parse_identity(identity)) == identity
    assert encode_recipient(parse_recipient(recipient)) == recipient


def test_an_identity_file_with_comments_parses():
    identity, recipient = generate()
    text = f"# created: 2026-10-17T00:00:00Z\n# public key: {recipient}\n\n{identity}\n"
    assert parse_identity(text) == parse_identity(identity)


@pytest.mark.parametrize("make", [
    lambda i, r: i.lower(),
    lambda i, r: r,
    lambda i, r: i + "\n" + i,
    lambda i, r: "# only a comment\n",
    lambda i, r: i[:-1] + ("Q" if i[-1] != "Q" else "P"),
])
def test_bad_identities_are_refused_without_quoting_them(make):
    identity, recipient = generate()
    text = make(identity, recipient)
    with pytest.raises(KeyFormatError) as caught:
        parse_identity(text)
    assert identity[16:] not in str(caught.value) and identity.lower()[16:] not in str(caught.value)


@pytest.mark.parametrize("make", [
    lambda i, r: r.upper(),
    lambda i, r: i,
    lambda i, r: bech32.encode("age", bytes(31)),
    lambda i, r: bech32.encode("agf", bytes(32)),
])
def test_bad_recipients_are_refused(make):
    identity, recipient = generate()
    with pytest.raises(KeyFormatError):
        parse_recipient(make(identity, recipient))
