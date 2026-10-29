
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

FileKind = Literal["text", "binary", "large"]
ChangeStatus = Literal["added", "removed", "changed"]


class ContentsFile(BaseModel):
    """One file in a version's folder: path, size and whether its text is viewable."""

    path: str
    size: int
    kind: FileKind


class ContentsResponse(BaseModel):
    """``GET /catalog/contents/{id}``: the file list and the manifest text.

    Fields: item_id, version, digest (the verified folder digest), files,
    total_bytes, body (the SKILL.md text, capped), body_truncated.
    """

    item_id: str
    version: str
    digest: str
    files: List[ContentsFile] = Field(default_factory=list)
    total_bytes: int = 0
    body: str
    body_truncated: bool = False


class FileChange(BaseModel):
    """One file that differs between the installed and the new version.

    ``diff`` is a unified text diff, present only when both sides are small
    text files (or the file was added or removed as text); ``diff_reason``
    says why it is absent (``binary`` or ``large``). ``diff_truncated`` is
    true when the diff was cut at the line cap.
    """

    path: str
    status: ChangeStatus
    old_size: Optional[int] = None
    new_size: Optional[int] = None
    diff: Optional[str] = None
    diff_reason: Optional[str] = None
    diff_truncated: bool = False


class UpdateDiff(BaseModel):
    """What an update changes, computed from two digest-verified versions."""

    from_version: str
    to_version: str
    changes: List[FileChange] = Field(default_factory=list)
    unchanged: int = 0


class LocalSkillMd(BaseModel):
    """``GET /skills/locations/{location_id}/skill-md``: a local SKILL.md, capped."""

    location_id: str
    name: str
    body: str
    body_truncated: bool = False
    size: int
    sha256: Optional[str] = None
