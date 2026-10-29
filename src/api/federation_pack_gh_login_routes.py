
from __future__ import annotations

import asyncio
from typing import Dict, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.api.peer_auth import Principal, require_peer
from src.core.pack.machines import capabilities as pack_capabilities, config_state, restrictions as restrictions_mod
from src.core.pack.relay import consent as consent_mod
from src.core.pack.transport import github_account, ladder

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack", tags=["federation"])
_require_credentials = require_peer("credentials")
pack_capabilities.register("pack.gh_login")
_NO_STORE = {"Cache-Control": "no-store"}
_TOKEN_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
MAX_TOKEN_CHARS = 512


def _accounts(gh: str) -> Dict[str, str]:
    done = ladder.run([gh, "auth", "status", "--hostname", "github.com", "--json", "hosts", "--jq",
                       '.hosts["github.com"][] | [.login, .tokenSource] | @tsv'], air_gap=False, timeout=30.0,
                      env={k: "" for k in _TOKEN_ENV})
    out: Dict[str, str] = {}
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        login, _, source = line.partition("\t")
        if github_account.valid_account(login):
            out[login] = source.strip()
    return out


def _login(account: str, token: str) -> Tuple[bool, str]:
    gh = github_account.gh_path()
    if gh is None:
        return False, "gh_missing"
    clean = {k: "" for k in _TOKEN_ENV}
    before = _accounts(gh)
    done = ladder.run([gh, "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--with-token"],
                      air_gap=False, stdin=(token + "\n").encode(), env=clean, timeout=60.0)
    if done.returncode != 0:
        logger.warning("pack_gh_login_failed", status=done.returncode, stderr_bytes=len(done.stderr))
        return False, "gh_login_failed"
    after = _accounts(gh)
    named = next((login for login in after if login.lower() == account.lower()), None)
    if named is None:
        for login in set(after) - set(before):
            ladder.run([gh, "auth", "logout", "--hostname", "github.com", "--user", login], air_gap=False, env=clean, timeout=30.0)
        return False, "account_mismatch"
    if after[named] != "keyring":
        ladder.run([gh, "auth", "logout", "--hostname", "github.com", "--user", named], air_gap=False, env=clean, timeout=30.0)
        return False, "gh_insecure_storage"
    return True, "ok"


@router.post("/gh-login")
async def receive_gh_login(request: Request, principal: Principal = Depends(_require_credentials),
                           _allowed: None = Depends(restrictions_mod.require_peer_allowed(
                               restrictions_mod.ACTION_RECEIVE_CREDENTIALS))) -> JSONResponse:
    """Log this machine's gh into ``account`` with the pushed token. Output: {account, ok: true} (never the token).

    Raises: HTTPException 403 not a peer, 422 ``bad_account`` / ``bad_token``, 409 ``account_mismatch`` /
    ``gh_insecure_storage`` / ``gh_missing`` / ``gh_login_failed`` (nothing logged in is left behind).
    """
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer carries a gh login"})
    consent = await asyncio.to_thread(config_state.default().relay_consent)
    if consent.mode != consent_mod.MODE_ALL:
        raise HTTPException(403, {"code": "relay_not_accepted", "detail": "this computer's owner has not allowed logins from the pack"})
    try:
        raw = await request.json()
    except ValueError:
        raise HTTPException(422, {"code": "bad_token", "detail": "the body is not valid"}) from None
    account, token = (raw.get("account"), raw.get("token")) if isinstance(raw, dict) and set(raw) == {"account", "token"} else (None, None)
    if not github_account.valid_account(account):
        raise HTTPException(422, {"code": "bad_account", "detail": "that is not a GitHub account name"})
    if not isinstance(token, str) or not 20 <= len(token) <= MAX_TOKEN_CHARS or any(c.isspace() for c in token):
        raise HTTPException(422, {"code": "bad_token", "detail": "the body is not valid"})
    ok, code = await asyncio.to_thread(_login, account, token)
    del token, raw
    if not ok:
        raise HTTPException(409, {"code": code, "detail": "gh was not logged in"})
    logger.info("pack_gh_login_received", account=account, sender=principal.grant.peer_install_id)
    return JSONResponse({"account": account, "ok": True}, headers=_NO_STORE)
