
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from src.cplugs.crate import constants as K

MAX_RECIPIENTS = 20
MAX_BACKUP_UNITS = 50


class PlanBody(BaseModel):
    """``POST /plan``: scope (session | project), target, variant (own | share), encrypt (null: the default), recipients
    (null: the settings' recipients), label, include_project_files, include_backups and backup_units (the plugin folder families whose backup points to carry) (own only; default false)."""

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(..., max_length=16)
    target: str = Field(..., min_length=1, max_length=1024)
    variant: str = Field("own", max_length=16)
    encrypt: Optional[bool] = None
    recipients: Optional[List[str]] = Field(None, max_length=MAX_RECIPIENTS)
    label: Optional[str] = Field(None, max_length=K.LABEL_MAX)
    include_project_files: bool = False
    include_backups: bool = False
    backup_units: List[str] = Field(default_factory=list, max_length=MAX_BACKUP_UNITS)


class FamiliesBody(BaseModel):
    """``POST /backup-families``: the scope (session | project) and its target, as in ``PlanBody``."""

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(..., max_length=16)
    target: str = Field(..., min_length=1, max_length=1024)


class ExportBody(PlanBody):

    fingerprint: str = Field(..., min_length=64, max_length=64)


class IdentityBody(BaseModel):
    """A body that may carry an age identity (``AGE-SECRET-KEY-1...``) for an encrypted crate."""

    model_config = ConfigDict(extra="forbid")

    identity: Optional[SecretStr] = None

    def identity_text(self) -> Optional[str]:
        return self.identity.get_secret_value() if self.identity is not None else None


class VerifyBody(IdentityBody):

    level: str = Field("full", max_length=8)
    location: Optional[int] = Field(None, ge=0, le=64)


class CopyBody(IdentityBody):

    folder: str = Field(K.FOLDER_SECOND, pattern=f"^{K.FOLDER_SECOND}$")


class ExtractBody(IdentityBody):

    conversation_id: str = Field(..., min_length=8, max_length=64)


class ImportSource(BaseModel):
    """The crate an import names: a recorded ``bundle_id``, or a ``folder`` (primary | second) and a crate ``name``. Never a path."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: Optional[str] = Field(None, max_length=80)
    folder: Optional[str] = Field(None, pattern="^(primary|second)$")
    name: Optional[str] = Field(None, max_length=128)


class ImportPlanBody(IdentityBody):

    source: ImportSource
    mode: str = Field("same_paths", max_length=16)
    new_root: Optional[str] = Field(None, max_length=1024)
    target_project_id: Optional[int] = Field(None, ge=1)
    skip_conflicts: bool = False
    exclude_conversations: List[str] = Field(default_factory=list, max_length=500)
    include_project_files: bool = False
    work_in_restored_copy: bool = False
    include_instructions: bool = False
    include_plugin_data: bool = False
    made_here: bool = False
    keep_conversations: bool = False
    file_backups: bool = False
    file_backup_units: List[str] = Field(default_factory=list, max_length=MAX_BACKUP_UNITS)
    rules: List[List[str]] = Field(default_factory=list, max_length=50)


class ImportBody(ImportPlanBody):

    fingerprint: str = Field(..., min_length=64, max_length=64)


class RemoveBody(BaseModel):
    """``POST /crates/remove``: name a crate by ``bundle_id`` or by ``folder`` (primary | second) plus ``name``.

    ``folder`` with a ``bundle_id`` picks which copy goes (none: its copy in the primary folder, else the second). ``also_second`` (default false) also removes the
    same-named copy in the second folder; without it only the copy in the named folder goes."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: Optional[str] = Field(None, max_length=80)
    folder: Optional[str] = Field(None, pattern="^(primary|second)$")
    name: Optional[str] = Field(None, max_length=128)
    also_second: bool = False
