
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel


def provider_of_login(login: Optional[str]) -> Optional[str]:
    if not isinstance(login, str) or not login:
        return None
    return "email" if "@" in login else "github"


class DeviceStartResponse(BaseModel):
    """`POST /catalog/auth/device/start`: what a person has to read.

    Fields:
        flow_id: an opaque handle for this half-finished sign in. It is
            what the poll is called with, and it means nothing to GitHub
            or to the catalog host. THIS IS NOT THE DEVICE CODE, which
            never leaves this server.
        user_code: the short code the person types on github.com. Meant
            to be read, and the only reason this response exists.
        verification_uri: where they type it.
        interval: seconds GitHub asked the poller to wait between
            attempts. Relayed rather than chosen here.
        expires_in: seconds until the code stops working, so the screen
            can say so instead of polling a dead flow forever.
    """

    flow_id: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


class DevicePollRequest(BaseModel):
    """`POST /catalog/auth/device/poll`: the handle, and nothing else.

    Fields:
        flow_id: what ``device/start`` handed back. The server looks the
            device code up itself, which is what keeps the credential off
            the page.
    """

    flow_id: str


class CatalogSessionResponse(BaseModel):
    """Whether anybody is signed in, and who. Never how.

    Description: the SAME shape is answered by the poll, the session read
      and the sign out, so a screen has one thing to read after any of
      them rather than three shapes that could disagree.

    Fields:
        signed_in: whether a live access token is held on this server. It
            is false for an EXPIRED one too, because a sign in that can
            no longer be used is not a sign in, and reporting it as one
            would leave a screen offering writes that all refuse.
        login: the GitHub login or the email address, or null. NULL IS
            NOT AN EMPTY STRING and is never a guess: signed out means
            nobody is named.
        provider: which identity this sign in came through, ``github``
            or ``email``, or null when nobody is signed in. DERIVED FROM
            THE LOGIN, never stored: an email login carries an "@" and a
            GitHub handle cannot. NULL IS NOT A DEFAULT OF "github" -
            signed out means no provider either.
    """

    signed_in: bool
    login: Optional[str] = None
    provider: Optional[str] = None
    email: Optional[str] = None

    @classmethod
    def held(cls, login: str, provider: Optional[str] = None) -> "CatalogSessionResponse":
        return cls(
            signed_in=True,
            login=login,
            provider=provider or provider_of_login(login),
            email=login if "@" in login else None,
        )


class EmailStartRequest(BaseModel):
    """`POST /catalog/auth/email/start`: where to send the code.

    Fields:
        email: the address a person typed. Lowercased and bounded by the
            route before anything is sent upstream, so what reaches the
            hosted api is the same string the verify is keyed on.
    """

    email: str


class EmailStartResponse(BaseModel):
    """`POST /catalog/auth/email/start`: what a person has to read.

    THE FIELD THAT IS NOT HERE IS THE POINT OF THE SHAPE. Cognito answers
    a SESSION, the opaque string the challenge must be answered with, and
    it is absent here on purpose: a page holding it plus a code could
    finish somebody else's sign in. It is held in this server's memory
    against ``flow_id`` instead, and
    ``tests/test_catalog_email_signin_routes.py`` searches every response
    body for its bytes as the second stop.

    Fields:
        flow_id: an opaque handle for this half-finished sign in. What
            the verify is called with, and meaningless to cognito and to
            the catalog host.
        destination: the masked address the code went to, so the screen
            can say where to look. MASKED UPSTREAM from the address that
            was typed, never echoed back from a challenge parameter.
        expires_in: seconds until the code stops working, so the screen
            can say so rather than waiting on a dead challenge.
    """

    flow_id: str
    destination: str
    expires_in: int


class GoogleProofResponse(BaseModel):
    """`POST /catalog/auth/google/poll`: Google approved, but the mailbox is not proven yet.

    Description: answered instead of a session when the address Google verified
      is not one Google is authoritative for. The hosted api has already mailed a
      code; ``mailbox_proof`` is the same shape an email start answers, so the
      email code screen renders it unchanged, and its ``flow_id`` is verified at
      ``/catalog/auth/google/mailbox/verify``. Nothing is signed in.

    Fields:
        signed_in: always false.
        mailbox_proof: the flow to answer with the emailed code.
    """

    signed_in: bool = False
    mailbox_proof: EmailStartResponse


class EmailVerifyRequest(BaseModel):
    """`POST /catalog/auth/email/verify`: the handle and the code.

    AND NOTHING ELSE, WHICH IS THE WHOLE DESIGN. The address and the
    cognito session are read out of this server's own memory. A body that
    carried the address would let a caller point a session it holds at a
    different account's username, and a body that carried the session
    would mean the session had been on a page.

    Fields:
        flow_id: what ``email/start`` handed back.
        code: the digits from the email. Treated as an opaque digit
            string: the measured length is eight, and no route here
            assumes it.
    """

    flow_id: str
    code: str
    consent: Optional[Dict[str, Any]] = None
    src: Optional[str] = None


class WebConsent(BaseModel):
    """The terms and age line a person ticked before a sign in; the hosted api validates it."""

    terms_version: str
    age_16_plus: bool
    news: bool = False


class WebStartRequest(BaseModel):
    """`POST /catalog/auth/web/start`: the provider, where the funnel began, and the consent.

    NO VERIFIER HERE OR ANYWHERE IN A RESPONSE: the verifier is made and kept by this server.
    """

    provider: Literal["google", "github"]
    src: Optional[str] = None
    consent: WebConsent


class WebStartResponse(BaseModel):
    """What the page gets: the hosted flow id, the link to open, and the poll timing."""

    flow_id: str
    url: str
    expires_in: int
    interval: int


class WebPollPending(BaseModel):
    """`POST /catalog/auth/web/poll` while the person has not finished in the browser."""

    status: Literal["pending"] = "pending"
    interval: int
