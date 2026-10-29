
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ValidationError

from .catalog_doc import _Doc
from .catalog_grade import GradeBlock, GradeRule  # noqa: F401
from .catalog_media import CardMedia  # noqa: F401
from .catalog_names import (  # noqa: F401
    RESERVED_NAMES_FOR,
    RESERVED_SKILL_NAMES,
    BUNDLED_THEME_NAMES,
    FIRST_PARTY_THEME_NAMES,
    FIRST_PARTY_THEME_PUBLISHER,
    RESERVED_THEME_NAMES,
    RETIRED_THEME_NAMES,
    is_reserved_name,
)
from .catalog_review import (  # noqa: F401
    ReviewBlock,
    ReviewOverride,
    ReviewVerdict,
    ReviewWarning,
    WarningKind,
    review_instructions_details,
    review_writes_instructions,
)

SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")

VERSION_RE = re.compile(
    r"^[0-9]{1,9}(?:\.[0-9]{1,9}){0,3}"
    r"(?:-[0-9a-z](?:[0-9a-z.-]{0,28}[0-9a-z])?)?$"
)

PUBLISHER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _match_or_raise(value: str, pattern: re.Pattern, what: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"{what} does not match {pattern.pattern}")
    return value


class PublisherKey(_Doc):

    key_id: str = Field(..., min_length=1)
    alg: str = Field(..., min_length=1)
    pub: str = Field(..., min_length=1, description="base64 public key line")
    added: str = Field(..., min_length=1, description="timestamp as signed")
    status: str = Field(..., min_length=1)


class PublisherEntry(_Doc):

    github_login: str = Field(..., min_length=1)
    keys: List[PublisherKey] = Field(default_factory=list)
    delegations: List[Any] = Field(default_factory=list)


class RevokedKey(_Doc):

    key_id: str = Field(..., min_length=1)
    since: str = Field(..., min_length=1, description="timestamp as signed")
    statement: str = Field(..., min_length=1)
    sig: str = Field(..., min_length=1)


class RevokedVersion(_Doc):

    item: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    since: str = Field(..., min_length=1, description="timestamp as signed")
    statement: str = Field(..., min_length=1)
    sig: str = Field(..., min_length=1)

    @field_validator("version")
    @classmethod
    def _version_shape(cls, value: str) -> str:
        return _match_or_raise(value, VERSION_RE, "version")


class Revocations(_Doc):

    keys: List[RevokedKey] = Field(default_factory=list)
    versions: List[RevokedVersion] = Field(default_factory=list)


class SourceRef(_Doc):

    repo: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    commit: str = Field(..., min_length=40, max_length=40)

    @field_validator("commit")
    @classmethod
    def _commit_shape(cls, value: str) -> str:
        return _match_or_raise(value, COMMIT_RE, "commit")


class SignatureBlock(_Doc):

    key_id: str = Field(..., min_length=1)
    sig: str = Field(..., min_length=1)
    tc: str = Field(..., description="trusted comment, may be empty")
    gsig: str = Field(..., min_length=1)


class ItemVersion(_Doc):

    v: str = Field(..., min_length=1)
    src: SourceRef
    digest: str = Field(..., min_length=64, max_length=64)
    size: int = Field(..., ge=0, description="unpacked bytes")
    files: int = Field(..., ge=0, description="regular file count")
    scripts: int = Field(..., ge=0)
    published_at: str = Field(
        ..., min_length=1, description="timestamp as signed"
    )
    sig: SignatureBlock
    review: Optional[ReviewBlock] = None
    grade: Optional[GradeBlock] = None

    @field_validator("digest")
    @classmethod
    def _digest_shape(cls, value: str) -> str:
        return _match_or_raise(value, DIGEST_RE, "digest")

    @field_validator("v")
    @classmethod
    def _version_shape(cls, value: str) -> str:
        return _match_or_raise(value, VERSION_RE, "version")


class ItemCard(_Doc):

    title: str = Field(..., min_length=1)
    brief: str = Field(..., min_length=1)
    icon: Optional[str] = None
    tags: Optional[List[str]] = None
    media: Optional[CardMedia] = None

    @field_validator("media", mode="before")
    @classmethod
    def _media_or_nothing(cls, value: object) -> object:
        if value is None or isinstance(value, CardMedia):
            return value
        try:
            return CardMedia.model_validate(value)
        except ValidationError:
            return None


class ItemFrontMatter(_Doc):

    description: str = Field(..., min_length=1)
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    author: Optional[str] = None
    author_url: Optional[str] = None
    homepage: Optional[str] = None
    repository: Optional[str] = None


class ItemCost(_Doc):

    desc_tokens: Optional[int] = Field(default=None, ge=0)
    body_tokens: Optional[int] = Field(default=None, ge=0)
    estimator: Optional[str] = None


class ItemDeprecation(_Doc):

    superseded_by: Optional[str] = None


class CatalogItem(_Doc):

    id: str = Field(..., min_length=1)
    kind: Literal["skill", "theme", "plugin", "loadout", "mod", "cplug"]
    name: str = Field(..., min_length=1, max_length=64)
    publisher: str = Field(..., min_length=1, max_length=39)
    latest: str = Field(..., min_length=1)
    card: ItemCard
    fm: ItemFrontMatter
    versions: List[ItemVersion] = Field(..., min_length=1)
    cost: Optional[ItemCost] = None
    fm_keys: Optional[List[str]] = None
    related: Optional[List[str]] = None
    deprecated: Optional[ItemDeprecation] = None

    @field_validator("name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        return _match_or_raise(value, SKILL_NAME_RE, "name")

    @field_validator("publisher")
    @classmethod
    def _publisher_shape(cls, value: str) -> str:
        return _match_or_raise(value, PUBLISHER_RE, "publisher")

    @model_validator(mode="after")
    def _latest_is_present(self) -> "CatalogItem":
        if self.latest not in {version.v for version in self.versions}:
            raise ValueError(
                f"latest {self.latest!r} is not among this item's versions"
            )
        return self


class IndexDocument(_Doc):

    model_config = {
        "extra": "ignore", "populate_by_name": True, "frozen": True,
    }

    schema_version: Literal["carnivore.catalog.index/1"] = Field(
        ..., alias="schema"
    )
    serial: int = Field(..., ge=0)
    generated_at: str = Field(
        ..., min_length=1, description="timestamp as signed"
    )
    publishers: Dict[str, PublisherEntry] = Field(default_factory=dict)
    revocations: Revocations = Field(default_factory=Revocations)
    items: List[CatalogItem] = Field(default_factory=list)
    featured: List[str] = Field(
        default_factory=list,
        description="item ids in featured order, signed with the index",
    )

    @field_validator("publishers")
    @classmethod
    def _handles_are_publishers(
        cls, value: Dict[str, PublisherEntry],
    ) -> Dict[str, PublisherEntry]:
        for handle in value:
            _match_or_raise(handle, PUBLISHER_RE, "publisher handle")
        return value
