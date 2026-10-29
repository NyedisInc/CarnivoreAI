
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class CommentAuthor(BaseModel):
    """The public face of a comment's author: a handle and a badge, never an id."""

    handle: Optional[str] = None
    publisher: Optional[bool] = None


class CommentView(BaseModel):
    """One comment, or a ``placeholder`` (``removed`` or ``deleted``) that keeps a thread whole.

    ``item_id``, ``status`` and ``reason_class`` appear only on the caller's
    own comments (``GET /catalog/me/comments`` and the write answers).
    """

    comment_id: Optional[str] = None
    parent_id: Optional[str] = None
    placeholder: Optional[str] = None
    author: Optional[CommentAuthor] = None
    body: Optional[str] = None
    created_at: Optional[int] = None
    edited: Optional[bool] = None
    edited_at: Optional[int] = None
    item_id: Optional[str] = None
    status: Optional[str] = None
    reason_class: Optional[str] = None


class CommentPageResponse(BaseModel):
    """A page of comments; ``cursor`` is null on the last page."""

    item_id: Optional[str] = None
    comments: Optional[List[CommentView]] = None
    cursor: Optional[str] = None


class CommentWriteResponse(BaseModel):
    """The stored comment after a post or an edit."""

    comment: Optional[CommentView] = None


class CommentDeleteResponse(BaseModel):
    """The answer to deleting your own comment."""

    comment_id: Optional[str] = None
    deleted: Optional[bool] = None


class ProfileResponse(BaseModel):
    """A public profile. ``joined`` is ``YYYY-MM-DD``; no id and no email."""

    handle: Optional[str] = None
    joined: Optional[str] = None
    bio: Optional[str] = None
    links: Optional[List[str]] = None
    items: Optional[List[str]] = None
    publisher: Optional[bool] = None
    github_login: Optional[str] = None


class ReportResponse(BaseModel):
    """The answer to a report; a repeat report answers the same."""

    reported: Optional[bool] = None


class MailPreferenceResponse(BaseModel):
    """Whether reply notices are mailed to this account."""

    notify_replies: Optional[bool] = None


class CommentPostRequest(BaseModel):
    """A new comment, or a reply when ``parent_id`` names a root comment."""

    model_config = ConfigDict(extra="forbid")

    body: str
    parent_id: Optional[str] = None


class CommentEditRequest(BaseModel):
    """The new text of your own comment."""

    model_config = ConfigDict(extra="forbid")

    body: str


class ReportRequest(BaseModel):
    """A report of a comment, review or item; the hosted api validates the reason."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    item_id: str
    comment_id: Optional[str] = None
    reviewer: Optional[str] = None
    reason: str
    note: Optional[str] = None


class ProfileEditRequest(BaseModel):
    """The fields of your own profile to change; only those sent are changed."""

    model_config = ConfigDict(extra="forbid")

    bio: Optional[str] = None
    links: Optional[List[str]] = None


class MailPreferenceRequest(BaseModel):
    """Opt in or out of reply notices."""

    model_config = ConfigDict(extra="forbid")

    notify_replies: bool
