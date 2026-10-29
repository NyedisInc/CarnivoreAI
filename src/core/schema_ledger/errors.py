
from __future__ import annotations


class SchemaLedgerError(Exception):
    pass


class LedgerFormatError(SchemaLedgerError):
    pass


class LedgerMismatch(SchemaLedgerError):
    pass


class FreezeViolation(SchemaLedgerError):
    pass
