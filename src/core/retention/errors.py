
from __future__ import annotations


class RetentionError(Exception):
    pass


class DriveNotReadyError(RetentionError):
    pass


class ProtectedPathError(RetentionError):
    pass


class CopyVerifyError(RetentionError):
    pass


class SourceChangedError(RetentionError):
    pass


class InsufficientSpaceError(RetentionError):
    pass


class ArchiveError(RetentionError):
    pass


class ToolMissingError(RetentionError):
    pass
