
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CatalogDeviceSession(BaseModel):
    """One signed in device of the catalog account.

    Fields:
        sid: the session id, what a revoke names. Not a credential.
        client: the app that signed in, "" when it did not say.
        label: the device's own name, "" when it did not say.
        created_at: unix seconds the device signed in.
        last_refresh_at: unix seconds of its last token refresh.
        current: True for the session making this request.
    """

    sid: str
    client: str = ""
    label: str = ""
    created_at: int = 0
    last_refresh_at: int = 0
    current: bool = False


class CatalogSessionsResponse(BaseModel):
    """`GET /catalog/account/sessions`: every device signed in to the account."""

    sessions: List[CatalogDeviceSession]


class CatalogRevokeResponse(BaseModel):
    """A revoke answer: how many sessions were ended."""

    revoked: int


class CatalogRegisterRequest(BaseModel):
    """`POST /catalog/account/register`: accept the terms, attest age, pick a handle.

    ``handle`` is needed only by an account that holds none (a GitHub account
    suggests its login; an older client that omits it gets the login); an
    existing handle is kept. The terms and age are optional: an account that accepted
    them at sign in sends the handle alone, and the host decides whether that is enough.
    """

    terms_version: Optional[str] = Field(default=None, min_length=1, max_length=40)
    age_16_plus: Optional[bool] = None
    handle: Optional[str] = Field(default=None, max_length=64)


class CatalogHandleRequest(BaseModel):
    """`POST /catalog/account/handle`: the new handle for the signed in account."""

    handle: str = Field(min_length=1, max_length=64)


class CatalogDeleteRequest(BaseModel):
    """`POST /catalog/account/delete`: the account's handle typed exactly, as confirmation."""

    confirm: str = Field(min_length=1, max_length=64)


class CatalogNewsRequest(BaseModel):
    """`POST /catalog/account/news`: turn the carnivore news email on or off for this account."""

    news: bool
