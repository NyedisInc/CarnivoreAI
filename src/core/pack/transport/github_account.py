"""Which GitHub account a project uses, and how a call asks for its token (P3, #1516; docs/pack.md 9.3).

Every Carnivore gh or https-git call for a project then uses that account EXPLICITLY at call time: ``gh auth token -u
<account>`` read in memory and handed to the child in its ENVIRONMENT (``GH_TOKEN``). Never the machine's active account,
never ``gh auth switch``, never argv, a file or a log line. An account name is validated to a strict pattern because it is
interpolated into the per-repo credential helper (``gh_helper``).
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import structlog

from src.core.pack.transport import ladder

logger = structlog.get_logger()

SOURCE_PROJECT, SOURCE_COMPANY, SOURCE_REMOTE_OWNER, SOURCE_NONE, SOURCE_AIR_GAP = (
    "project", "company", "remote_owner", "none", "air_gap")
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,38}$")
_OWNER_RE = re.compile(r"github\.com[:/](?P<owner>[A-Za-z0-9_-]+)/", re.IGNORECASE)
_GH_CANDIDATES = ("/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh")


class AccountError(Exception):
    """A GitHub account could not be used; ``code`` is the stable reason and the message never carries a token."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Resolution:

    account: Optional[str]
    source: str

    @property
    def needs_card(self) -> bool:
        return self.account is None and self.source == SOURCE_NONE


def valid_account(name: object) -> bool:
    return isinstance(name, str) and bool(_ACCOUNT_RE.match(name))


def gh_path() -> Optional[str]:
    found = shutil.which("gh")
    if found:
        return found
    return next((p for p in _GH_CANDIDATES if os.access(p, os.X_OK)), None)


def remote_owner(url: Optional[str]) -> Optional[str]:
    found = _OWNER_RE.search(url or "")
    return found.group("owner") if found else None


def logged_in_accounts() -> List[str]:
    gh = gh_path()
    if gh is None:
        return []
    done = ladder.run([gh, "auth", "status", "--hostname", "github.com", "--json", "hosts", "--jq",
                       '.hosts["github.com"][].login'], air_gap=False, timeout=30.0)
    if done.returncode != 0:
        return []
    return [ln.strip() for ln in done.stdout.decode("utf-8", "replace").splitlines() if valid_account(ln.strip())]


def resolve(*, air_gap: bool, project_account: Optional[str], company_account: Optional[str], origin_url: Optional[str],
            logged_in: Callable[[], List[str]] = logged_in_accounts) -> Resolution:
    if air_gap:
        return Resolution(None, SOURCE_AIR_GAP)
    if valid_account(project_account):
        return Resolution(project_account, SOURCE_PROJECT)
    if valid_account(company_account):
        return Resolution(company_account, SOURCE_COMPANY)
    owner = remote_owner(origin_url)
    if owner:
        for name in logged_in():
            if name.lower() == owner.lower():
                return Resolution(name, SOURCE_REMOTE_OWNER)
    return Resolution(None, SOURCE_NONE)


def token_env(account: str) -> Dict[str, str]:
    if not valid_account(account):
        raise AccountError("bad_account", "that is not a GitHub account name")
    gh = gh_path()
    if gh is None:
        raise AccountError("gh_missing", "gh is not installed on this computer")
    done = ladder.run([gh, "auth", "token", "--hostname", "github.com", "--user", account], air_gap=False, timeout=30.0)
    token = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or not token:
        raise AccountError("account_not_logged_in", f"gh is not logged in as {account} on this computer")
    return {"GH_TOKEN": token}


def store_project_account(conn: sqlite3.Connection, project_id: int, account: Optional[str]) -> None:
    if account is not None and not valid_account(account):
        raise AccountError("bad_account", "that is not a GitHub account name")
    conn.execute("UPDATE projects SET github_account = ? WHERE id = ?", (account, project_id))
