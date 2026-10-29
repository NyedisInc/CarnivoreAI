
from __future__ import annotations

from typing import List, Sequence, Tuple

CHARSET: str = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_CHECKSUM_CONST: int = 1
_GENERATOR: Tuple[int, ...] = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
_CHECKSUM_LEN: int = 6


def _polymod(values: Sequence[int]) -> int:
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for i, gen in enumerate(_GENERATOR):
            if (top >> i) & 1:
                chk ^= gen
    return chk


def _hrp_expand(hrp: str) -> List[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert_bits(data: Sequence[int], from_bits: int, to_bits: int, pad: bool) -> List[int]:
    acc = bits = 0
    out: List[int] = []
    maxv = (1 << to_bits) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            raise ValueError("bech32 value out of range")
        acc = (acc << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        raise ValueError("bech32 data has invalid padding")
    return out


def encode(hrp: str, data: bytes) -> str:
    if not hrp or any(not 33 <= ord(c) <= 126 for c in hrp):
        raise ValueError("bech32 prefix must be printable ASCII")
    hrp = hrp.lower()
    values = _convert_bits(data, 8, 5, True)
    polymod = _polymod(_hrp_expand(hrp) + values + [0] * _CHECKSUM_LEN) ^ _CHECKSUM_CONST
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(_CHECKSUM_LEN)]
    return hrp + "1" + "".join(CHARSET[v] for v in values + checksum)


def decode(text: str) -> Tuple[str, bytes]:
    if any(not 33 <= ord(c) <= 126 for c in text):
        raise ValueError("bech32 string has a character outside printable ASCII")
    if text.lower() != text and text.upper() != text:
        raise ValueError("bech32 string mixes upper and lower case")
    text = text.lower()
    sep = text.rfind("1")
    if sep < 1 or sep + _CHECKSUM_LEN + 1 > len(text):
        raise ValueError("bech32 string has no prefix or no room for a checksum")
    hrp, tail = text[:sep], text[sep + 1:]
    try:
        values = [CHARSET.index(c) for c in tail]
    except ValueError:
        raise ValueError("bech32 string has a character outside the data alphabet") from None
    if _polymod(_hrp_expand(hrp) + values) != _CHECKSUM_CONST:
        raise ValueError("bech32 checksum does not match")
    return hrp, bytes(_convert_bits(values[:-_CHECKSUM_LEN], 5, 8, False))
