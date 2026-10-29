"""Exceptions of the phase backup tool. Every one means exit code 2 (could not determine / could not finish), never a pass."""

from __future__ import annotations


class PhaseBackupError(Exception):
    pass


class SourceMissing(PhaseBackupError):
    pass


class CopyFailed(PhaseBackupError):
    """A database copy could not be made or failed its integrity check; nothing was published."""


class NotEnoughSpace(PhaseBackupError):
    pass


class SetUnreadable(PhaseBackupError):
    pass


class BadPhaseId(PhaseBackupError):
    pass
