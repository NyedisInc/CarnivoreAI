
from __future__ import annotations

from src.core.bookmarks.errors import BookmarkError


class ContentsError(BookmarkError):

    code = "contents_error"


class RemoteSession(ContentsError):

    status = 409
    code = "remote_host"


class UnsupportedFamily(ContentsError):

    status = 409
    code = "unsupported_family"
