
from typing import List, Optional

from pydantic import BaseModel, Field


class ExportLocation(BaseModel):
    """One place a copy of a bundle lives."""

    where: str = Field(description="Where the copy is (a folder, a drive or a remote name); text, never opened by Carnivore")
    verified_at: Optional[str] = Field(None, description="ISO 8601 UTC time the copy was last read back there, or null")


class ExportBundle(BaseModel):
    """One export bundle's record. The bundle file itself lives outside Carnivore."""

    bundle_id: str
    sha256: str = Field(description="sha256 of the bundle file, 64 lowercase hex characters")
    scope: str = Field(description="session or project")
    project_uid: Optional[str] = None
    session_uuid: Optional[str] = None
    label: Optional[str] = None
    created_at: str = Field(description="ISO 8601 UTC")
    locations: List[ExportLocation]
    verified_at: Optional[str] = Field(None, description="ISO 8601 UTC time of the last full verify, or null")
    local_removed: bool = Field(description="The local data this bundle covers has been removed")
    conversations: int = Field(description="Conversations whose export pointer names this bundle")


class ExportBundleList(BaseModel):
    """Every export bundle, newest first."""

    bundles: List[ExportBundle]
    count: int


class ExportedConversation(BaseModel):
    """Where one exported conversation lives."""

    conversation_id: str
    family: str = Field(description="claude or codex")
    title: Optional[str] = None
    exported_at: str = Field(description="ISO 8601 UTC")
    bundle: ExportBundle
