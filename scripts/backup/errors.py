
from __future__ import annotations


class PhaseBackupError(Exception):
    pass


class SourceMissing(PhaseBackupError):
    pass


class CopyFailed(PhaseBackupError):
    pass


class NotEnoughSpace(PhaseBackupError):
    pass


class SetUnreadable(PhaseBackupError):
    pass


class BadPhaseId(PhaseBackupError):
    pass
