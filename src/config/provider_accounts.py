
from __future__ import annotations

import os
import re
import unicodedata
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

PROVIDER_ACCOUNTS_KEY = "provider_accounts"

# CLAUDE_CONFIG_DIR
DEFAULT_CLAUDE_CONFIG_DIR = "~/.claude"

DEFAULT_CODEX_HOME = "~/.codex"

MANAGED_ROOT = "~/.carnivore/accounts"

SHORT_NAME_MAX = 32
_COLOR_SHAPE = re.compile(r"^#[0-9a-f]{6}$")

ProviderKind = Literal["claude", "codex"]

_ID_SHAPE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProviderAccount(BaseModel):
    """One configured provider account, and where to read its credential.

    Description: a POINTER. Nothing on this model is a credential, and
      ``extra="forbid"`` is what keeps it that way; see the module
      docstring for why forbidding beats ignoring here.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    provider: ProviderKind
    short_name: Optional[str] = None
    claude_config_dir: str = DEFAULT_CLAUDE_CONFIG_DIR
    codex_home: str = DEFAULT_CODEX_HOME
    managed: bool = False
    color: Optional[str] = None

    @field_validator("color")
    @classmethod
    def _color_is_lowercase_hex(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _COLOR_SHAPE.fullmatch(value):
            raise ValueError(
                "color must be lowercase six digit hex, for example #8b5cf6"
            )
        return value

    @field_validator("short_name")
    @classmethod
    def _short_name_is_trimmed(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if len(trimmed) > SHORT_NAME_MAX:
            raise ValueError(f"short_name must be at most {SHORT_NAME_MAX} characters")
        return trimmed

    @field_validator("id")
    @classmethod
    def _id_is_a_slug(cls, value: str) -> str:
        if not _ID_SHAPE.fullmatch(value):
            raise ValueError(
                "id must be a lowercase slug of letters, digits and dashes"
            )
        return value

    @field_validator("name")
    @classmethod
    def _name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value

    @model_validator(mode="after")
    def _the_pointer_this_provider_reads_is_present(self) -> "ProviderAccount":
        if self.provider == "claude" and not self.claude_config_dir.strip():
            raise ValueError("claude_config_dir is required for a claude account")
        if self.provider == "codex" and not self.codex_home.strip():
            raise ValueError("codex_home is required for a codex account")
        return self


def managed_dir_for(account_id: str) -> str:
    if not _ID_SHAPE.fullmatch(account_id):
        raise ValueError(
            "a managed profile id must be a lowercase slug of letters, "
            "digits and dashes"
        )
    root = os.path.abspath(os.path.expanduser(MANAGED_ROOT))
    return unicodedata.normalize("NFC", os.path.join(root, account_id))


def pointer_field_for(provider: Optional[str]) -> str:
    return "claude_config_dir" if provider == "claude" else "codex_home"


def profile_dir_for(account: ProviderAccount) -> str:
    if account.managed:
        return managed_dir_for(account.id)
    if account.provider == "claude":
        return account.claude_config_dir
    return account.codex_home


class ProviderAccountsConfig(BaseModel):
    """Every account this install polls, in the order the user arranged.

    Description: an empty list is the default and the honest state of an
      install that has configured nothing. It is NOT a stand-in for "we
      could not read the block": a block that will not parse is logged
      by ``auth_loader.parse_block`` before it becomes this.

    Fields:
        accounts: the configured accounts. Ids are unique across the
          list, because the id is what an upsert and a remove address;
          two rows sharing one would make a write land on whichever the
          reader happened to see first.
    """

    model_config = ConfigDict(extra="forbid")

    accounts: List[ProviderAccount] = []

    @field_validator("accounts")
    @classmethod
    def _ids_are_unique(cls, value: List[ProviderAccount]) -> List[ProviderAccount]:
        seen = set()
        for account in value:
            if account.id in seen:
                raise ValueError(f"duplicate provider account id: {account.id}")
            seen.add(account.id)
        return value
