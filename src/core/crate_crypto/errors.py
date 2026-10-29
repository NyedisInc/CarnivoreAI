
from __future__ import annotations


class CrateCryptoError(Exception):
    pass


class KeyFormatError(CrateCryptoError, ValueError):
    pass


class Malformed(CrateCryptoError):
    pass


class WrongKey(CrateCryptoError):
    pass


class Corrupt(CrateCryptoError):
    pass


class HeaderMacMismatch(Corrupt):
    pass
