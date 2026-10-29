
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.models.catalog_submit import SubmissionFileView, SubmissionRefusalView


class PublishablePreviewRequest(BaseModel):
    """`POST /catalog/publish/preview`: one of your skills, and its version."""

    location: str = Field(min_length=1, max_length=600)
    version: str = Field(default="1.0.0", max_length=64)


class PublishSendRequest(PublishablePreviewRequest):

    digest: str = Field(min_length=64, max_length=64)


class PublishHeroRequest(BaseModel):
    """`POST /catalog/submissions/media`: an author's hero image for an item of theirs.

    The hosted route owns every check (publisher, magic, size, shape); this model
    only bounds what is read off the socket (512 KiB of image as base64).
    """

    kind: str = Field(default="skill", max_length=16)
    name: str = Field(min_length=1, max_length=64)
    image_base64: str = Field(min_length=1, max_length=700_000)
    source: Literal["made", "yours"] = "yours"


class PublishableSkill(BaseModel):
    """One skill on this Mac that is yours to publish (not catalog managed)."""

    location: str
    kind: str = "skill"
    name: str
    harness: str
    description: str
    is_symlink: bool = False
    version: str = ""


class PublishableListResponse(BaseModel):
    """`GET /catalog/publish/mine`."""

    skills: List[PublishableSkill] = Field(default_factory=list)


class PublishPreviewResponse(BaseModel):
    """What a publish would send, what lints, and the digest to echo back.

    ``lint`` is the catalog grader's own block (advisory, never a gate);
    ``cost`` is the estimated tokens the skill's listing costs an agent;
    ``compat`` names the harness it was found under and any front matter
    ``compatibility`` text. ``can_send`` is False whenever a refusal is listed.
    """

    location: str
    kind: str = "skill"
    name: str
    version: str
    file_count: int
    total_bytes: int
    files: List[SubmissionFileView] = Field(default_factory=list)
    refusals: List[SubmissionRefusalView] = Field(default_factory=list)
    lint: Dict[str, Any] = Field(default_factory=dict)
    cost: Dict[str, Any] = Field(default_factory=dict)
    compat: Dict[str, Any] = Field(default_factory=dict)
    digest: str
    can_send: bool


class PublishAccountResponse(BaseModel):
    """`GET /catalog/handle`: who the catalog says you are, for publishing.

    ``handle`` is empty until registered; ``handle_status`` is ``pending`` until
    Alex approves that person's first submission. ``can_claim`` is true for any
    account with no handle (every provider picks one; a GitHub account is offered
    its login). ``registered`` is true once the account has a handle, the current
    terms and the age attestation; ``terms_version`` and ``terms_url`` are the
    terms in force, for the register dialog; ``terms_accepted`` is the version this
    account accepted (recorded at sign in), so the dialog can skip the checkboxes
    when it equals ``terms_version``.
    """

    provider: Optional[str] = None
    login: Optional[str] = None
    handle: str = ""
    handle_status: str = ""
    can_claim: bool = False
    registered: bool = False
    terms_version: str = ""
    terms_url: str = ""
    terms_accepted: str = ""
    news_opt_in: Optional[bool] = None
    notify_replies: Optional[bool] = None


class ItemFactsFile(BaseModel):
    """One member of a folder: its relative path and size in bytes."""

    path: str
    size: int


class ItemFactsSend(BaseModel):
    """One send the app made from a folder (the local record, D10)."""

    submission_id: str
    version: str
    sent_at: str
    hero: str = ""
    media_submission_id: str = ""
    hero_sha: str = ""


class ItemFactsFinding(BaseModel):
    """One refusal of a stored check that names a file: its code and the relative path (never a matched value)."""

    code: str
    path: str


class ItemFactsCheck(BaseModel):
    """One local check of a folder; ``summary`` is ``clean`` or the refusal codes.

    ``digest`` is the folder digest the check handed out ("" on a record made before it was kept) and ``findings``
    the refusals that name a file ([] on such a record).
    """

    version: str
    ok: bool
    at: str
    summary: str
    grade: str = ""
    files: Optional[int] = None
    bytes: Optional[int] = None
    digest: str = ""
    findings: List[ItemFactsFinding] = Field(default_factory=list)


class ItemFactsResponse(BaseModel):
    """`GET /catalog/publish/items/{location}`: what only this computer knows about a folder.

    NO FIELD IS A FILESYSTEM PATH (``files`` carry relative paths). ``declared_version`` and ``license`` are
    empty when the manifest declares none (or an id off the policy list); ``changed_files`` counts the files
    that differ from the newest send, ``changed_at`` is the newest mtime among them (empty when none);
    ``made_at`` is the oldest file mtime; ``sends`` and ``checks`` are newest first.
    """

    location: str
    kind: str
    name: str
    harness: str = ""
    declared_version: str = ""
    file_count: int
    total_bytes: int
    files: List[ItemFactsFile] = Field(default_factory=list)
    license_file: bool = False
    license: str = ""
    grade: str = ""
    cost: Dict[str, Any] = Field(default_factory=dict)
    made_at: str = ""
    changed_files: int = 0
    changed_at: str = ""
    sends: List[ItemFactsSend] = Field(default_factory=list)
    checks: List[ItemFactsCheck] = Field(default_factory=list)
