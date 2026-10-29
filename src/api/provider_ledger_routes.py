"""The usage ledger: one read of the poller, and the writes to config.json.

THE READ NEVER FETCHES. ``GET /provider-ledger`` answers from the
background poller's memory and opens no connection at all. A route that
polled on demand would let one browser refresh spend the user's whole
rate-limit budget, and the Claude usage endpoint admits only about
thirty requests an hour per identity. An install whose loop has not
started answers an EMPTY ledger with ``alive`` false, which is the
honest reading; it does not build a poller, because starting a network
loop from a GET is the one thing a read must never do.

EVERY WRITE DOES TWO THINGS AFTERWARDS. It clears
``settings._auth_config_cache``, because that cache holds a parsed
document carrying the OLD account list and every other reader would
serve the pre-write value until the process restarted; the same line
every config-writing route ends on.
And it asks the poller to re-read that account on its next tick, so an
added or edited pointer produces a reading in seconds rather than after
a three minute floor nobody can see.

AND FOUR ROUTES SWITCH WHICH ACCOUNT NEW SESSIONS USE (issue #151), and
they handle no credential either. The active account is a POINTER per
provider in config.json (``src/core/account_switch/``); a switch writes an
account id, links the profile's transcripts to the shared ones when they
are absent, and nothing else. A running session keeps its account until
it is restarted, which the user does through the existing restart path.

Mounted under ``/api/v1`` from ``src/api/routes.py``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from src.api.auth import require_auth
from src.config import settings
from src.config.provider_accounts import ProviderAccount, pointer_field_for, profile_dir_for
from src.core import session_change_notice
from src.core.provider_ledger import accounts_store, managed_profiles, poller, poller_scan
from src.api.enrollment_gate import is_local_request
from src.core.provider_ledger.login_command import login_env_for, login_profile_dir
from src.core.provider_ledger.login_guard import live_login_session
from src.core.account_switch import auto_switch, ledger_hook, pane_account, profile_setup, shared_links, store
from src.config.provider_account_switch import MIN_THRESHOLD_PERCENT
from src.core.account_switch.active import PROVIDERS, effective_active, find_account, pointer_for
from src.core.account_switch.decide import rank_candidates
from src.models.account_switch import (
    AccountActivated,
    AccountSwitchState,
    AccountSwitchWrite,
    ActiveAccountState,
    RunningElsewhere,
)
from src.models.provider_ledger import (
    LedgerSnapshot,
    ProviderAccountWrite,
    ProviderLoginStarted,
    ProviderSetupResult,
)

logger = structlog.get_logger()

router = APIRouter(tags=["provider-ledger"])


def _config_path() -> Path:
    return Path(settings.auth_config_file).expanduser()


def _unreadable(exc: Exception) -> HTTPException:
    """The 500 this module answers when config.json cannot be used.

    Description: REPORTED, NEVER DEFAULTED. Answering an empty account
      list for a file that could not be read would be indistinguishable
      from an install that has configured nothing, and a settings screen
      would then offer to "add your first account" over a file it is
      about to overwrite.
    Inputs: exc (Exception) - the FileNotFoundError or ValueError raised.
    Output: HTTPException - 500, carrying a code and a detail.
    Example: raise _unreadable(exc)
    """
    return HTTPException(
        status_code=500,
        detail={
            "code": "unavailable",
            "detail": "this install's configuration could not be read",
        },
    )


def _managed_dir_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "managed_dir_unavailable", "detail": str(exc)},
    )


async def _stored_accounts() -> List[ProviderAccount]:
    try:
        return await asyncio.to_thread(accounts_store.list_accounts, _config_path())
    except (FileNotFoundError, ValueError) as exc:
        logger.error("provider_accounts_unreadable", error=str(exc))
        raise _unreadable(exc) from exc


def _account_or_404(accounts: List[ProviderAccount], account_id: str) -> ProviderAccount:
    account = next((a for a in accounts if a.id == account_id), None)
    if account is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "not_found",
                "detail": f"no provider account is configured with the id {account_id}",
            },
        )
    return account


async def _stored_account(account_id: str) -> Optional[ProviderAccount]:
    accounts = await _stored_accounts()
    return next((a for a in accounts if a.id == account_id), None)


@router.get(
    "/provider-ledger",
    response_model=LedgerSnapshot,
    dependencies=[Depends(require_auth)],
)
async def get_provider_ledger() -> LedgerSnapshot:
    """Every configured account's last reading, the total, and loop liveness.

    ANSWERED FROM MEMORY. The background poller owns the schedule and the
    requests; this route reads what it last measured. ``loop.alive`` and
    the rows' ``fetched_at`` are deliberately separate facts, because a
    live loop with old readings and a dead loop with the same readings
    need different actions from the person looking at them.
    """
    return poller.snapshot()


@router.get(
    "/provider-ledger/accounts",
    response_model=List[ProviderAccount],
    dependencies=[Depends(require_auth)],
)
async def list_provider_accounts() -> List[ProviderAccount]:
    """The configured accounts, in the order the file holds them.

    A READ WRITES NOTHING, the missing block included: materialising it
    would turn "never configured" into "configured with nothing".

    Raises:
        HTTPException(500): config.json is missing or is not readable
            JSON.
    """
    return await _stored_accounts()


@router.put(
    "/provider-ledger/accounts/{account_id}",
    response_model=ProviderAccount,
    dependencies=[Depends(require_auth)],
)
async def put_provider_account(
    account_id: str, body: ProviderAccountWrite
) -> ProviderAccount:
    """Add an account, or replace the one that already holds this id.

    THE PATH CARRIES THE ID and the body may repeat it, but the two must
    agree: two ids in one request is an ambiguity, and picking one
    silently would let a client believe it edited a row it never
    touched.

    A POINTER THAT WAS NOT STATED IS OMITTED rather than sent as null, so
    :class:`ProviderAccount` applies its own default and that default
    stays written in exactly one place.

    A DEMOTION SAYS WHERE THE ROW NOW POINTS. Taking ``managed`` off a
    row that has it drops the derived pointer with it, and an unstated
    pointer is not "leave it alone" on a whole-row replace: it is the
    model's own default, ``~/.claude``, which is the PRIMARY login. That
    row would then report the primary identity and the next login started
    from it would run against the primary profile, so the demotion is
    refused unless the body states the directory the row now reads.

    Raises:
        HTTPException(422): the body's id disagrees with the path; the
            body states no ``managed`` flag, which on a whole-row replace
            would demote a managed row silently; a demotion states no
            pointer; or the account the two of them describe is not a
            valid one - a non-slug id, a blank name, or a provider whose
            own pointer is empty. An unknown key, ``token`` included, is
            refused one layer earlier by the body model itself.
        HTTPException(500): config.json is missing or is not readable
            JSON.
    """
    if body.id is not None and body.id != account_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "id_mismatch",
                "detail": "the id in the body must match the id in the path",
            },
        )

    stated = {
        key: value
        for key, value in body.model_dump(exclude={"id"}).items()
        if value is not None
    }
    stored = await _stored_account(account_id)
    if (
        "short_name" not in body.model_fields_set
        and stored is not None
        and stored.short_name is not None
    ):
        stated["short_name"] = stored.short_name

    # could not
    if stated.get("managed"):
        try:
            profile_dir = await asyncio.to_thread(
                managed_profiles.ensure_managed_dir, account_id
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_account", "detail": str(exc)},
            ) from exc
        except managed_profiles.ManagedProfileError as exc:
            logger.warning(
                "provider_account_managed_dir_unavailable", account_id=account_id
            )
            raise _managed_dir_unavailable(exc) from exc
        stated[pointer_field_for(stated.get("provider"))] = profile_dir
    elif stored is not None and stored.managed:
        pointer_field = pointer_field_for(stated.get("provider"))
        if pointer_field not in stated:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "pointer_required",
                    "detail": (
                        "taking a managed account off its own profile "
                        "directory has to say which directory it reads "
                        f"instead: state {pointer_field}"
                    ),
                },
            )

    try:
        account = ProviderAccount(id=account_id, **stated)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_account",
                "detail": exc.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            },
        ) from exc

    try:
        await asyncio.to_thread(
            accounts_store.upsert_account, _config_path(), account
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("provider_accounts_unwritable", error=str(exc))
        raise _unreadable(exc) from exc

    settings._auth_config_cache = None
    poller.poll_soon(account.id)
    return account


@router.post(
    "/provider-ledger/accounts/{account_id}/login",
    response_model=ProviderLoginStarted,
    dependencies=[Depends(require_auth)],
)
async def start_provider_account_login(
    account_id: str, request: Request
) -> ProviderLoginStarted:
    """Open a pane and start this account's own provider login in it.

    THE ORDER IS LOAD BEARING. The profile directory is created FIRST
    and the pane is spawned SECOND, because Codex does not create
    ``CODEX_HOME`` for you: its own documentation says the directory has
    to exist already, so a build that spawned first would produce a
    login that fails for a reason nobody would look for.

    IT NEVER TOUCHES A CREDENTIAL. It makes a directory, sets one
    environment variable and starts a shell. The provider's own CLI, in
    a pane the user is watching, is what mints the token, and the ledger
    learns about it the same way it learns everything: by reading the
    live store on its next pass, hurried here by ``poll_soon``.

    WHAT WAITS ON THE ATTACH IS AN ACCOUNT ID. The command text is
    resolved server side at flush time
    (``SessionManager.flush_pending_login``), so nothing a client sent
    is ever typed into a pane.

    EVERY SESSION BELONGS TO A PROJECT, so the pane runs IN the profile
    directory and the ordinary create path resolves one for it: the
    session is attributed to the DEEPEST EXISTING project whose root
    contains that directory, and a project is minted AT the directory
    only when no existing project contains it
    (``session_project_binding.resolve_project_binding``, called with
    ``allow_create=True`` from ``session_create_persist``). On a box with
    a project at the home directory, every login pane therefore joins
    that project and no per-profile project is created. Either way the
    directory is permanent, which is what a project's directory must be.

    Raises:
        HTTPException(404): no account holds this id. A 200 would tell
            the screen it started something it did not.
        HTTPException(409): the session this route started for this
            account is still live, named in the detail so the client
            navigates to it rather than racing a second login into the
            same store; or the managed profile directory could not be
            created.
        HTTPException(500): config.json is missing or is not readable
            JSON.
    """
    account = _account_or_404(await _stored_accounts(), account_id)

    manager = request.app.state.session_manager
    existing = live_login_session(manager, account_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "login_in_progress",
                "detail": f"a login for {account_id} is already running",
                "session_id": existing[0],
                "tmux_session": existing[1],
            },
        )

    if account.managed:
        try:
            await asyncio.to_thread(
                managed_profiles.ensure_managed_dir, account_id
            )
        except managed_profiles.ManagedProfileError as exc:
            logger.warning(
                "provider_login_dir_unavailable", account_id=account_id
            )
            raise _managed_dir_unavailable(exc) from exc

    profile_dir = login_profile_dir(account)
    device_auth = account.provider == "codex" and not is_local_request(request)
    session = await manager.create_session(
        session_id=f"ses_{uuid.uuid4().hex[:8]}",
        working_dir=profile_dir,
        auto_start_claude=False,
        project_name=f"login_{account_id}",
        label=f"log in: {account.name}",
        extra_env=login_env_for(account, profile_dir),
    )

    manager._sidecars.set_pending_login(session.id, account_id, device_auth)

    poller.poll_soon(account_id)

    session_change_notice.publish(
        request.app.state,
        session_change_notice.build_structural_notice("created"),
    )

    logger.info(
        "provider_login_started",
        account_id=account_id,
        provider=account.provider,
        session_id=session.id,
        tmux_session=getattr(session, "tmux_session", None),
        managed=account.managed,
        device_auth=device_auth,
    )
    return ProviderLoginStarted(
        session_id=session.id,
        tmux_session=getattr(session, "tmux_session", None),
        device_auth=device_auth,
    )


@router.post(
    "/provider-ledger/accounts/{account_id}/setup",
    response_model=ProviderSetupResult,
    dependencies=[Depends(require_auth)],
)
async def finish_provider_account_setup(account_id: str) -> ProviderSetupResult:
    """Do the next step of a claude profile's first-run setup (issue #1010).

    Description: what the "needs one-time setup" pill calls. It runs the
      same :func:`profile_setup.converge` every ledger pass and the
      activate route run, for this one account, now: that marks
      ``hasCompletedOnboarding`` only in a MANAGED profile whose login the
      ledger reads ``ok`` and whose file already carries the login. It
      never touches a credential, never refreshes a token and never
      switches the active account. The answer names what the caller does
      next (see :class:`ProviderSetupResult`); ``poll_soon`` makes the
      ledger re-read the row so the pill clears on its next read.

    Raises:
        HTTPException(404): no account holds this id.
        HTTPException(409): ``profile_not_managed``, a profile this app did
            not log in, which it never writes (the activate route refuses
            the same row the same way).
        HTTPException(500): config.json is missing or not readable JSON.
    """
    try:
        accounts = await asyncio.to_thread(accounts_store.list_accounts, _config_path())
    except (FileNotFoundError, ValueError) as exc:
        raise _unreadable(exc) from exc
    account = next((a for a in accounts if a.id == account_id), None)
    if account is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_account", "detail": "no account holds this id"},
        )
    if account.provider != "claude" or not account.managed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "profile_not_managed",
                "detail": "only a claude account this app logged in can be set up here",
            },
        )
    rows = poller.snapshot().accounts
    await asyncio.to_thread(profile_setup.converge, rows, [account])
    poller.poll_soon(account_id)
    if await asyncio.to_thread(profile_setup.setup_done, account):
        outcome = "done"
    else:
        row = next((r for r in rows if r.id == account_id), None)
        outcome = "pending" if row is not None and row.credential_state == "ok" else "login"
    logger.info("provider_setup_step", account_id=account_id, outcome=outcome)
    return ProviderSetupResult(outcome=outcome)




def _switch_state_now(path: Path) -> AccountSwitchState:
    """Read the switch block and resolve each provider's active account.

    Description: BLOCKING, run through ``asyncio.to_thread``. The
      default-login rung reads ``.claude.json``'s two uuids and nothing
      else; no credential store is opened.
    Inputs: path (Path) - config.json.
    Output: AccountSwitchState.
    Raises: FileNotFoundError, ValueError - config.json unusable.
    """
    switch = store.read_switch(path)
    accounts = poller_scan.with_auto_default(accounts_store.list_accounts(path))
    rows = poller.snapshot().accounts
    now = datetime.now(timezone.utc)
    active = []
    for provider in PROVIDERS:
        current = effective_active(accounts, switch, provider)
        order = rank_candidates(
            rows,
            provider=provider,
            active_account_id=current.account_id,
            threshold_percent=switch.threshold_percent,
            now=now,
        )
        order = [
            r for r in order
            if auto_switch._linkable(find_account(accounts, r.id, provider))
        ]
        active.append(ActiveAccountState(**asdict(current), next_order=[r.id for r in order]))
    return AccountSwitchState(
        auto_switch=switch.auto_switch,
        threshold_percent=switch.threshold_percent,
        active=active,
        last_switch=auto_switch.last_switch(),
        restarts_running_sessions=switch.auto_switch,
    )


async def _switch_state() -> AccountSwitchState:
    try:
        return await asyncio.to_thread(_switch_state_now, _config_path())
    except (FileNotFoundError, ValueError) as exc:
        logger.error("provider_account_switch_unreadable", error=type(exc).__name__)
        raise _unreadable(exc) from exc


async def _running_elsewhere(request: Request) -> List[RunningElsewhere]:
    """Running agent sessions still on an account other than the active one.

    Description: FAIL-SOFT to an empty list: this is advice beside a switch
      that already landed, and a listing that could not be taken must not
      turn the switch into an error.
    Inputs: request (Request) - carries the session manager.
    Output: list[RunningElsewhere].
    """
    manager = getattr(request.app.state, "session_manager", None)
    if manager is None:
        return []
    path = _config_path()
    try:
        switch = await asyncio.to_thread(store.read_switch, path)
        accounts = poller_scan.with_auto_default(
            await asyncio.to_thread(accounts_store.list_accounts, path)
        )
        active = {
            provider: await asyncio.to_thread(effective_active, accounts, switch, provider)
            for provider in PROVIDERS
        }
        infos = await manager.list_session_infos()
        rows = await pane_account.running_elsewhere(
            infos, socket=manager._tmux_socket_name(), accounts=accounts, active=active
        )
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        logger.warning("provider_account_running_unavailable", error=type(exc).__name__)
        return []
    return [RunningElsewhere(**row) for row in rows]


@router.get(
    "/provider-ledger/switch",
    response_model=AccountSwitchState,
    dependencies=[Depends(require_auth)],
)
async def get_account_switch() -> AccountSwitchState:
    """The auto-switch toggle, its threshold, and each provider's active account."""
    return await _switch_state()


@router.put(
    "/provider-ledger/switch",
    response_model=AccountSwitchState,
    dependencies=[Depends(require_auth)],
)
async def put_account_switch(body: AccountSwitchWrite, request: Request) -> AccountSwitchState:
    """Turn auto-switch on or off, and optionally set its threshold.

    TURNING IT ON EVALUATES AT ONCE, against the readings the poller
    already holds, so an account that is already past the threshold moves
    now rather than on the next reading that happens to change. Nothing
    is fetched for it.

    Raises:
        HTTPException(422): a threshold outside 50 to 100.
        HTTPException(500): config.json is missing or not readable JSON.
    """
    threshold = body.threshold_percent
    if threshold is not None and not MIN_THRESHOLD_PERCENT <= threshold <= 100:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_switch", "detail": "threshold must be 50 to 100"},
        )
    try:
        await asyncio.to_thread(
            store.set_auto,
            _config_path(),
            enabled=body.auto_switch,
            threshold_percent=threshold,
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("provider_account_switch_unwritable", error=type(exc).__name__)
        raise _unreadable(exc) from exc
    if body.auto_switch:
        await ledger_hook.after_ledger_pass(poller.snapshot(), request.app.state)
    return await _switch_state()


@router.get(
    "/provider-ledger/switch/running",
    response_model=List[RunningElsewhere],
    dependencies=[Depends(require_auth)],
)
async def get_running_elsewhere(request: Request) -> List[RunningElsewhere]:
    """Running sessions whose account is not their provider's active one.

    What the providers page offers "restart to switch" for. A session whose
    account cannot be read is left out rather than guessed at.
    """
    return await _running_elsewhere(request)


@router.post(
    "/provider-ledger/accounts/{account_id}/activate",
    response_model=AccountActivated,
    dependencies=[Depends(require_auth)],
)
async def activate_provider_account(account_id: str, request: Request) -> AccountActivated:
    """Make this account the one its provider's NEW sessions launch under.

    THE PROFILE IS MADE READY FIRST, THE POINTER SECOND (issue #671). A
    managed profile whose login the ledger reads ``ok`` is converged
    (first-run setup marked done, the default login's MCP servers merged)
    before anything else; one whose Claude Code first-run setup is still
    not done would open every session on the sign-in screen, so the switch
    is refused with a 409 ``profile_needs_setup``.

    THE LINKS COME FIRST, THE POINTER SECOND. A profile whose transcript
    directory cannot be linked to the shared one could not resume a
    conversation started elsewhere, so the switch is refused with a 409
    ``profile_not_shared`` and the pointer is left where it was.

    A RUNNING SESSION IS NOT TOUCHED. The answer lists the running
    sessions of that provider still on another account, so the page can
    offer to restart them; the restart itself is the user's, through the
    existing restart picker.

    Raises:
        HTTPException(404): no account holds this id.
        HTTPException(409): ``profile_needs_setup``, ``profile_not_shared``.
        HTTPException(500): config.json is missing or not readable JSON.
    """
    path = _config_path()
    try:
        configured = await asyncio.to_thread(accounts_store.list_accounts, path)
        before = await asyncio.to_thread(store.read_switch, path)
    except (FileNotFoundError, ValueError) as exc:
        raise _unreadable(exc) from exc
    accounts = poller_scan.with_auto_default(configured)
    account = next((a for a in accounts if a.id == account_id), None)
    if account is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_account", "detail": "no account holds this id"},
        )
    if account.provider not in PROVIDERS:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "provider_not_switchable",
                "detail": "switching is not available for this provider yet",
            },
        )
    default = shared_links.is_default_profile(account.provider, profile_dir_for(account))
    if not account.managed and not default:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "profile_not_managed",
                "detail": "only an account this app logged in can be switched to",
            },
        )
    await asyncio.to_thread(profile_setup.converge, poller.snapshot().accounts, [account])
    if not default and not await asyncio.to_thread(profile_setup.setup_done, account):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "profile_needs_setup",
                "detail": (
                    "claude's one-time setup is not done on this account yet, so a "
                    "session moved onto it would open on the sign-in screen"
                ),
            },
        )
    report = await asyncio.to_thread(
        shared_links.ensure_shared_links,
        profile_dir_for(account),
        account.provider,
        managed=account.managed,
    )
    if not report.resume_safe:
        logger.warning(
            "provider_account_activate_refused",
            account_id=account.id,
            provider=account.provider,
            required=report.entries.get(shared_links.REQUIRED_ENTRY[account.provider]),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "profile_not_shared",
                "detail": (
                    "this account's profile keeps its own conversation history, so "
                    "a session moved onto it could not resume"
                ),
            },
        )
    previous = await asyncio.to_thread(
        effective_active, accounts, before, account.provider
    )
    try:
        status, _ = await asyncio.to_thread(
            store.set_active, path, account.provider, pointer_for(account)
        )
    except (FileNotFoundError, ValueError) as exc:
        raise _unreadable(exc) from exc
    if previous.account_id != account.id:
        auto_switch.record_switch(
            request.app.state,
            provider=account.provider,
            from_account_id=previous.account_id,
            to_account_id=account.id,
            reason="manual",
        )
    return AccountActivated(
        state=await _switch_state(),
        running_elsewhere=await _running_elsewhere(request),
    )
