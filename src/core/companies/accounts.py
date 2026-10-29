
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Mapping

import structlog

from src.core.companies import store
from src.core.db import transaction
from src.core.message_model_secrets import scan_text
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

ACCOUNT_KEYS = ("github", "github_login", "aws", "gcp")
MAX_VALUE_CHARS = 120


class AccountsInvalid(ValueError):
    pass


def clean_accounts(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, Mapping):
        raise AccountsInvalid("accounts must be an object")
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if key not in ACCOUNT_KEYS:
            raise AccountsInvalid(f"unknown account field {str(key)[:40]!r}; use {', '.join(ACCOUNT_KEYS)}")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str) or len(value.strip()) > MAX_VALUE_CHARS or "\n" in value:
            raise AccountsInvalid(f"{key} must be one line of text, at most {MAX_VALUE_CHARS} characters")
        if scan_text(value):
            logger.warning("company_accounts_secret_refused", field=key)
            raise AccountsInvalid(f"{key} looks like a secret; store a pointer (a name or an id), never a credential")
        out[key] = value.strip()
    return out


def get_accounts(conn: sqlite3.Connection, company_id: int) -> Dict[str, str]:
    row = conn.execute("SELECT accounts FROM companies WHERE id = ?", (company_id,)).fetchone()
    if row is None:
        raise store.CompanyNotFound(str(company_id))
    try:
        found = json.loads(row[0] or "{}")
    except ValueError:
        logger.warning("company_accounts_unreadable", company_id=company_id)
        return {}
    return {k: v for k, v in found.items() if k in ACCOUNT_KEYS and isinstance(v, str)} if isinstance(found, dict) else {}


def set_accounts(conn: sqlite3.Connection, company_id: int, accounts: Mapping[str, Any]) -> Dict[str, str]:
    clean = clean_accounts(accounts)
    with transaction(conn):
        cur = conn.execute("UPDATE companies SET accounts = ?, updated_at = ? WHERE id = ?",
                           (json.dumps(clean, sort_keys=True), utc_now(), company_id))
        if cur.rowcount == 0:
            raise store.CompanyNotFound(str(company_id))
    logger.info("company_accounts_set", company_id=company_id, fields=sorted(clean))
    return clean
