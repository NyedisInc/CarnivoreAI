
from __future__ import annotations


class SessionGroupError(Exception):
    pass


class GroupNotFound(SessionGroupError):
    pass


class GroupNameInvalid(SessionGroupError):
    pass


class GroupLimitReached(SessionGroupError):
    pass


class GroupsUnavailable(SessionGroupError):
    pass


class SessionNotStored(SessionGroupError):
    pass
