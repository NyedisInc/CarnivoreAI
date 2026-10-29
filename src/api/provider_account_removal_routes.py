
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.provider_ledger_routes import _account_or_404, _config_path, _stored_accounts, _unreadable
from src.config import settings
from src.core import config_writer
from src.core.provider_ledger import (
    accounts_store,
    managed_profiles,
    poller,
    profile_logout,
)
from src.config.provider_account_switch import pointer_field
from src.core.account_switch import pane_account
from src.core.account_switch import store as switch_store
from src.core.provider_ledger.login_guard import live_login_session

logger = structlog.get_logger()

router = APIRouter(tags=["provider-ledger"])


@router.delete(
    "/provider-ledger/accounts/{account_id}",
    dependencies=[Depends(require_auth)],
)
async def delete_provider_account(account_id: str, request: Request) -> dict:
    """Remove one account. A MANAGED one loses its login and its directory.

    AN ID THAT WAS NEVER CONFIGURED IS A 404, not a pretend success. A
    200 would tell a settings screen it had deleted a row that was never
    in the file, and the screen would repaint from a state nobody wrote.

    **AN UNMANAGED ROW IS UNCHANGED, AND THAT IS THE FENCE.** It names a
    directory the user made, very often the primary ``~/.claude``, and
    removing a pointer must never take what it points at. It answers
    ``logout: skipped`` and ``directory: kept``.

    **THE ORDER IS A CRASH-SAFETY CONTRACT: LOG OUT, THEN THE DIRECTORY,
    THEN THE ROW.** A crash between any two of them leaves a row
    pointing at nothing, which the user can remove again, rather than a
    directory with no row, which nothing on screen can reach. The logout
    has to be first for a second reason: it runs UNDER the profile
    directory, so a logout after the delete would be pointed at
    something that is no longer there.

    Raises:
        HTTPException(404): no account holds this id.
        HTTPException(409): a login pane for this account is measurably
            alive. Deleting a directory out from under a sign in that is
            in flight is how a half-written credential store happens.
        HTTPException(500): config.json is missing or is not readable
            JSON.
    """
    accounts = await _stored_accounts()

    account = _account_or_404(accounts, account_id)

    logout = profile_logout.LOGOUT_SKIPPED
    directory = managed_profiles.DIRECTORY_KEPT
    if account.managed:
        existing = live_login_session(request.app.state.session_manager, account_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "login_in_progress",
                    "detail": (
                        f"a login for {account_id} is still running; close "
                        "that pane before removing the account"
                    ),
                    "session_id": existing[0],
                    "tmux_session": existing[1],
                },
            )
        in_use = await _sessions_on(request, accounts, account_id)
        if in_use:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "account_in_use",
                    "detail": (
                        f"{len(in_use)} running session(s) use {account_id}; "
                        "restart them on another account or close them first"
                    ),
                    "tmux_sessions": in_use,
                },
            )
        await _clear_pointer(account)
        logout = await profile_logout.log_out_profile(account)
        outcome = await asyncio.to_thread(
            managed_profiles.remove_managed_dir, account_id
        )
        directory = outcome.status

    try:
        status, _ = await asyncio.to_thread(
            accounts_store.remove_account, _config_path(), account_id
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("provider_accounts_unwritable", error=str(exc))
        raise _unreadable(exc) from exc

    if status == config_writer.UNCHANGED:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "not_found",
                "detail": f"no provider account is configured with the id {account_id}",
            },
        )

    if not account.managed:
        await _clear_pointer(account)
    settings._auth_config_cache = None
    poller.forget_account(account_id)
    logger.info(
        "provider_account_removed",
        account_id=account_id,
        managed=account.managed,
        logout=logout,
        directory=directory,
    )
    return {"removed": account_id, "logout": logout, "directory": directory}


async def _sessions_on(request: Request, accounts, account_id: str) -> list:
    """Running agent panes on this account's profile. See pane_account.

    Description: a listing that cannot be taken refuses the removal rather
      than proceeding blind, the same direction as an unreadable pane.
    Inputs: request; accounts (the configured rows); account_id.
    Output: list[str] - tmux names.
    Raises: HTTPException(409) - the running sessions could not be listed.
    """
    manager = getattr(request.app.state, "session_manager", None)
    if manager is None:
        return []
    try:
        infos = await manager.list_session_infos()
    except (OSError, RuntimeError) as exc:
        logger.warning("provider_account_removal_listing_failed", error=type(exc).__name__)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "account_in_use",
                "detail": "the running sessions could not be checked; try again",
            },
        ) from exc
    return await pane_account.sessions_on_account(
        infos, socket=manager._tmux_socket_name(), accounts=accounts, account_id=account_id
    )


async def _clear_pointer(account) -> None:
    field = pointer_field(account.provider) if account.provider in ("claude", "codex") else None
    if field is None:
        return
    try:
        await asyncio.to_thread(
            switch_store.set_active,
            _config_path(),
            account.provider,
            None,
            expect={field: account.id},
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("provider_account_pointer_clear_failed", error=type(exc).__name__)
