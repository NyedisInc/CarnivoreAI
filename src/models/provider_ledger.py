
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ProviderKind = Literal["claude", "codex"]

CredentialState = Literal[
    "ok",
    "expired",
    "missing",
    "refused",
    "rate_limited",
    "error",
    "unknown",
]


PokeState = Literal["idle", "running", "failed", "unknown", "needs_login"]


class PokeStatus(BaseModel):
    """What the refresh poke last did to one account, for the screen.

    Description: THIS IS ABOUT THE ATTEMPT, NOT THE CREDENTIAL. The
      credential's own health is ``credential_state``; this says whether
      the app tried to have Claude Code renew it and how that went, so a
      row can explain itself instead of only reporting ``expired``.

      NO PART OF THE CHILD'S OUTPUT IS ON IT. ``error`` is one of a small
      set of constants from
      :mod:`src.core.provider_ledger.refresh_poke`, because a failing
      ``claude`` prints authentication error strings and this
      model is serialised to a browser.

    Fields:
        state: what the last attempt amounts to right now.
        last_at: when a poke was last STARTED. ``None`` when none ever
            has been, which is different from one that failed.
        error: why the last attempt did not refresh anything, as a
            constant. ``None`` when nothing has failed.
    """

    state: PokeState
    last_at: Optional[datetime] = None
    error: Optional[str] = None


class UsageWindow(BaseModel):
    """One rate-limit window of one account, as the provider reported it.

    Description: the unit the whole ledger is built from. Both providers
      answer with a percentage consumed and a moment it resets, over a
      window whose length is either stated (Codex) or implied by the
      window's name (Claude).

    Fields:
        kind: the provider's own name for the window, for example
            ``five_hour`` or ``primary``. Stable enough to key on.
        label: the human window the row prints, for example ``5h``.
        used_pct: percent of the window consumed, 0-100, provider native.
            This is USED, so the headroom is ``100 - used_pct``.
        window_seconds: how long the window is. ``None`` when the provider
            did not say and the kind does not imply it.
        resets_at: when the window resets, as an aware datetime. ``None``
            when the provider sent no readable stamp.
    """

    kind: str
    label: str
    used_pct: float
    window_seconds: Optional[int] = None
    resets_at: Optional[datetime] = None


class AccountUsage(BaseModel):
    """One configured account, as the ledger last measured it.

    Description: a row of ``GET /api/v1/provider-ledger``. It carries
      both the reading and the reading's provenance, so a screen can tell
      a fresh answer from a stale one without asking a second endpoint.

    Fields:
        id: this install's own id for the account. Not a provider id.
        name: what the user called it.
        provider: which provider it belongs to.
        plan: the plan the provider named, for example ``max`` or
            ``pro``. ``None`` when no poll has named one.
        identity: the account's own name for itself, usually an email.
            ``None`` when it is not known without spending a request.
        credential_state: what the last poll learned about the credential.
        fetched_at: when the reading in ``windows`` was taken. ``None``
            when the account has never been polled.
        next_poll_at: when the loop intends to poll it next. ``None``
            when nothing is scheduled.
        error: a short, credential-free reason the last poll did not read
            usage. ``None`` when the last poll succeeded.
        windows: every window the provider reported, in provider order.
            EMPTY IS A REAL ANSWER and means nothing was reported.
        color: the swatch the user chose for this account, lowercase six
            digit hex. ``None`` means NO COLOUR WAS CHOSEN, and a client
            paints nothing at all for it: a grey placeholder would read
            as a chosen colour.
        managed: whether this account's profile directory was created by
            this app under ``~/.carnivore/accounts``. Carried on the row
            so a screen can say where a login lives without fetching the
            accounts list a second time.
        login_expires_at: when the LOGIN ITSELF dies, aware, read from
            the credential's ``refreshTokenExpiresAt``. About thirty days
            from a login and NOT EXTENDED by a token refresh, so it is
            knowable weeks ahead and a screen can warn early instead of
            at the failure. ``None`` means the store recorded none, which
            is NOT a login that never expires and NOT one that has
            already gone.
        poke: what the app's last attempt to have Claude Code refresh
            this profile did, or ``None`` when no attempt has ever been
            made or considered. Claude only: nothing pokes codex.
        short_name: the configured account's own ``short_name``
            (:class:`src.config.provider_accounts.ProviderAccount`), an
            optional shorter form of ``name`` for a spot too narrow for
            the full one. ``None`` when nobody set one. Carried straight
            through, never derived here or by any reader: this field IS
            the structured short form, so nothing downstream should ever
            split or pattern-match ``name`` to invent one.
        setup_complete: claude only. True when the profile's own
            ``.claude.json`` says Claude Code's first-run setup is done,
            False when it is signed in but the setup is not done (a session
            launched on it would open on the sign-in screen, so the switch
            skips it; issue #671), ``None`` when not known (no login in the
            file, the file unreadable, or a codex row).
    """

    id: str
    name: str
    provider: ProviderKind
    plan: Optional[str] = None
    identity: Optional[str] = None
    credential_state: CredentialState
    fetched_at: Optional[datetime] = None
    next_poll_at: Optional[datetime] = None
    error: Optional[str] = None
    windows: List[UsageWindow] = Field(default_factory=list)
    color: Optional[str] = None
    managed: bool = False
    login_expires_at: Optional[datetime] = None
    poke: Optional[PokeStatus] = None
    short_name: Optional[str] = None
    setup_complete: Optional[bool] = None


class LedgerTotalWindow(BaseModel):
    """One window kind, averaged across the accounts that reported it.

    Description: the total line answers "how much of this window have I
      burned across everything", which is why ``used_pct`` is a mean and
      not a sum: a sum of percentages is not a percentage.

    Fields:
        kind: the window kind being summarised.
        label: the human window, taken from the reporting accounts.
        used_pct: the arithmetic mean of ``used_pct`` over the accounts
            that reported this kind. Accounts that did not report it are
            not counted as zero.
        resets_at: the EARLIEST non-null reset among them, because that
            is the next moment anything changes. ``None`` when no
            reporting account carried a reset.
        accounts: how many accounts reported this kind. The denominator
            of the mean, stated so a reader can see it.
    """

    kind: str
    label: str
    used_pct: float
    resets_at: Optional[datetime] = None
    accounts: int


class LedgerTotal(BaseModel):
    """The total line under the account rows.

    Fields:
        accounts: how many accounts are configured, reporting or not.
            This is NOT the per-window denominator; that is on each
            window, because an account can be silent about one window and
            loud about another.
        windows: one entry per window kind any account reported.
    """

    accounts: int
    windows: List[LedgerTotalWindow] = Field(default_factory=list)


class LoopStatus(BaseModel):
    """Whether the poller is running, told apart from whether data is fresh.

    Description: a live loop with old readings and a dead loop with the
      same old readings look identical from the rows alone, and they need
      different actions. So liveness is published separately.

    Fields:
        alive: whether the polling task is running right now.
        last_pass_at: when a pass last finished, successfully or not.
            ``None`` when no pass has finished since this process began.
    """

    alive: bool
    last_pass_at: Optional[datetime] = None


class LedgerSnapshot(BaseModel):
    """`GET /api/v1/provider-ledger`: the rows, the total and the loop.

    Fields:
        accounts: one row per configured account, ordered by provider
            then by name. A STABLE ORDER AND NOT THE CONFIGURED ONE,
            because the rows are assembled from a live poll: an order
            that depended on a reading would move a row under the
            user's cursor every time an unrelated number changed.
        total: the averaged line under them.
        loop: whether the poller behind all of it is alive.
    """

    accounts: List[AccountUsage]
    total: LedgerTotal
    loop: LoopStatus


class FetchOutcome(BaseModel):
    """What one poll of one provider learned. NOT a wire shape.

    Description: the fetchers answer with this instead of raising, so a
      failed poll updates one account's state and never takes the loop
      down with it.

    Fields:
        state: the credential state this poll measured.
        windows: what it read. Empty on every state but ``ok``.
        plan: the plan the payload named, when it named one.
        retry_after_seconds: how long the provider asked to be left
            alone. ``None`` when it asked for nothing readable, INCLUDING
            when it answered ``Retry-After: 0``, which is a saturated
            window rather than permission to retry immediately.
        error: a short, credential-free reason. ``None`` when ``state``
            is ``ok``.
    """

    state: CredentialState
    windows: List[UsageWindow] = Field(default_factory=list)
    plan: Optional[str] = None
    retry_after_seconds: Optional[float] = None
    error: Optional[str] = None


class ProviderAccountWrite(BaseModel):
    """The body of `PUT /api/v1/provider-ledger/accounts/{id}`.

    Description: THE PATH CARRIES THE ID, so the field here is optional
      and, when present, must equal the path. Two ids in one request is
      an ambiguity rather than a preference: picking one silently would
      let a client believe it edited a row it never touched.

      ``extra="forbid"`` IS THE MECHANISM, NOT A TIDINESS RULE. An
      account is a POINTER to a credential store and never a copy of a
      credential, so a key called ``token`` has to be structurally
      impossible rather than merely undocumented. Ignoring it would let
      a credential sit in the request, and then in the file, unread but
      present.

      THE TWO POINTERS DEFAULT TO ``None`` RATHER THAN TO A PATH, and
      that is an import rule rather than a preference: ``src/config``
      already imports ``src/models``, so naming the config package's
      defaults here would close a cycle at interpreter start. ``None``
      means "not stated", and the route omits the key so
      :class:`src.config.provider_accounts.ProviderAccount` applies its
      own default, which stays the one place either default is written.

    Fields:
        id: optional, and equal to the path segment when given.
        name: what the user calls the account on screen.
        provider: which provider it belongs to.
        claude_config_dir: the Claude config dir, as the user typed it.
        codex_home: the Codex home, as the user typed it.
        managed: whether this app owns the account's profile directory.
            A managed row states NO pointer: the server derives one
            absolute path from the id, creates that directory and writes
            it into the row, which is what makes the string the config
            holds, the string the login exports and the string the
            keychain lookup hashes the same bytes.

            REQUIRED, ALONE AMONG THE OPTIONAL FIELDS, because THE WRITE
            IS A WHOLE-ROW REPLACE and this flag's own default is the
            dangerous direction. A body that omitted it demoted a managed
            row to unmanaged, dropped the derived pointer with it and
            left the row on the default ``~/.claude``, so the row then
            reported the PRIMARY login's identity and the next login
            started from it ran against the primary profile. An omitted
            flag is now a 422 rather than a silent demotion; the shipped
            client has always sent it.
        color: the swatch, lowercase six digit hex. ``None`` is "not
            stated", and the route omits the key so the config model's
            own default applies; ``absent is not a default`` holds on
            both sides, because that default is itself ``None``.
        short_name: the shorter form of ``name`` for a narrow spot.
            ABSENT KEEPS THE STORED VALUE, because the write replaces
            the whole row and an edit that never touched this field
            must not wipe it; an empty or blank string CLEARS it to
            ``None``. Trimmed, at most 32 characters.
    """

    model_config = {"extra": "forbid"}

    id: Optional[str] = None
    name: str
    provider: ProviderKind
    claude_config_dir: Optional[str] = None
    codex_home: Optional[str] = None
    managed: bool
    color: Optional[str] = None
    short_name: Optional[str] = None


class ProviderLoginStarted(BaseModel):
    """`POST /provider-ledger/accounts/{id}/login`: the pane that opened.

    Description: the two facts the client needs to take the user to the
      login it just started. A SESSION ID IS NOT A TMUX NAME, so both
      are published rather than one being derived from the other.

      NOTHING ELSE IS ON IT, and that is the point: the route creates a
      directory, sets one environment variable and starts a shell. No
      credential, no token and no login URL crosses this boundary,
      because none of them is ever handled by this app.

    Fields:
        session_id: the app's own id for the session that was created.
        tmux_session: the name of the pane on the ``cloude`` socket.
            ``None`` only on a backend that does not name one.
        device_auth: True when the pane runs the device-code login
            (codex, requested from a browser not on this computer), so
            the client can say where device-code login is switched on.
    """

    session_id: str
    tmux_session: Optional[str] = None
    device_auth: bool = False


class ProviderSetupResult(BaseModel):
    """`POST /provider-ledger/accounts/{id}/setup`: the next step, decided.

    Description: issue #1010. What clicking "needs one-time setup" did.
      ``done``: the profile's first-run setup is marked done now (or
      already was). ``pending``: the login reads ``ok`` but the write had
      to wait for a quiet moment; the next ledger pass finishes it.
      ``login``: the login itself is not ``ok``, so the caller opens the
      ordinary login pane (``POST .../login``), after which a ledger pass
      finishes the setup on its own. No credential crosses this boundary.

    Fields:
        outcome: one of ``done``, ``pending``, ``login``.
    """

    outcome: Literal["done", "pending", "login"]
