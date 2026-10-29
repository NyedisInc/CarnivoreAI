
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.row_looks import look_checked

MAX_PATH_LENGTH = 4096
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class OpenFileRequest(BaseModel):
    """``POST /files/open``: the file to open as a row, named by root and RELATIVE path, from one session.

    The client never sends a folder: ``workdir`` means the session's own working directory, looked up on the server.
    """

    model_config = ConfigDict(extra="forbid")
    root: Literal["user", "workdir"] = Field(..., description="'user' (~/.claude) or 'workdir' (the session's folder).")
    path: str = Field(..., min_length=1, max_length=MAX_PATH_LENGTH,
                      description="Relative to the root, as a tree listing or the git-status listing names it.")
    session_uuid: str = Field(..., min_length=1, max_length=64,
                              description="sessions.session_uuid of the session it is opened from; the row stays with it.")
    kind: Literal["file", "diff"] = Field("file", description="'file' opens an editor; 'diff' its read-only changed-file diff.")
    color: Optional[str] = Field(None, description="OPTIONAL named theme color for the row (docs/row-looks.md); absent keeps the row as it is.")
    icon: Optional[str] = Field(None, description="OPTIONAL named icon for the row (docs/row-looks.md); absent keeps the row as it is.")

    @model_validator(mode="after")
    def _known_look(self) -> "OpenFileRequest":
        look_checked(self.color, self.icon)
        return self

    @field_validator("path")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("path must not contain a NUL byte")
        return value


class OpenFileInfo(BaseModel):
    """One open file row as every window receives it."""

    id: str = Field(..., description="16 lowercase hex characters, minted by the server.")
    kind: Literal["file", "diff"]
    root: Literal["user", "workdir"]
    path: str
    session_uuid: str
    title: str = Field(..., description="The file's own name, the row label; the path is its tooltip.")
    opened_at: float
    seq: int = Field(..., description="Open order: higher is more recently opened or reused.")


class OpenFileList(BaseModel):
    """``GET /files/open``: every open file row, oldest first."""

    files: List[OpenFileInfo]


class OpenFileResponse(BaseModel):
    """``POST /files/open``: the stored row (an existing row of the same file from the same session is reused)."""

    file: OpenFileInfo
    reused: bool


class OpenFileContent(BaseModel):
    """``GET /files/open/{id}/content``: the file, or why it cannot be shown (``viewable: false``)."""

    id: str
    viewable: bool
    reason: Optional[Literal["too_large", "not_text", "gone", "unavailable"]] = None
    detail: Optional[str] = None
    content: Optional[str] = None
    sha256: Optional[str] = Field(None, description="The revision of the bytes read: the base a save names.")
    mtime_ns: Optional[int] = None
    size: Optional[int] = None
    is_executable: Optional[bool] = None
    is_sensitive: Optional[bool] = None
    read_only: Optional[bool] = None


class SaveOpenFileRequest(BaseModel):
    """``PUT /files/open/{id}/content``: the whole new content and the revision it was based on."""

    model_config = ConfigDict(extra="forbid")
    content: str
    expected_sha256: Optional[str] = Field(None, pattern=SHA256_PATTERN,
                                           description="The read's sha256. Required unless overwrite is true.")
    overwrite: bool = Field(False, description="The owner chose 'overwrite' in the stale-save prompt: skip the check.")
    acknowledge_executable: bool = False
    acknowledge_sensitive: bool = False

    @model_validator(mode="after")
    def _names_a_base(self) -> "SaveOpenFileRequest":
        if self.expected_sha256 is None and not self.overwrite:
            raise ValueError("send expected_sha256 (the read's sha256), or overwrite: true")
        return self


class SaveOpenFileResponse(BaseModel):
    """The save landed: the file's new revision, the base for the next save."""

    id: str
    backed_up: bool
    is_executable: bool
    is_sensitive: bool
    sha256: Optional[str] = None
    mtime_ns: Optional[int] = None
