
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

WRITE_LOCK = threading.Lock()
MODE_ALL, MODE_LIST, MODE_NONE = "all", "list", "none"
MODES = (MODE_ALL, MODE_LIST, MODE_NONE)
MAX_ACCOUNTS = 32
_ACCOUNT_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
SENDER_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
_LABEL_MAX = 64


@dataclass(frozen=True)
class Consent:

    mode: Optional[str] = None
    accounts: Tuple[str, ...] = ()
    answered: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode, "accounts": list(self.accounts), "answered": list(self.answered)}


def offer_key(sender_install_id: str, account_key: str) -> str:
    return f"{sender_install_id}:{account_key}"


def clean_offers(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw[:MAX_ACCOUNTS] if isinstance(raw, list) else []:
        key, label = (item.get("account_key"), item.get("label")) if isinstance(item, dict) else (None, None)
        if isinstance(key, str) and _ACCOUNT_RE.fullmatch(key):
            out.append({"account_key": key, "label": " ".join(str(label or key).split())[:_LABEL_MAX] or key})
    return out


def from_dict(raw: Any) -> Consent:
    if isinstance(raw, dict) and raw.get("mode") in MODES:
        def keys(name: str) -> Tuple[str, ...]:
            value = raw.get(name)
            return tuple(dict.fromkeys(k for k in value if isinstance(k, str) and 0 < len(k) <= 200))[:MAX_ACCOUNTS * 8] \
                if isinstance(value, list) else ()
        return Consent(raw["mode"], keys("accounts"), keys("answered"))
    return Consent()


def accepts(consent: Consent, sender_install_id: str, account_key: str) -> bool:
    if consent.mode == MODE_ALL:
        return True
    return consent.mode == MODE_LIST and offer_key(sender_install_id, account_key) in consent.accounts


def revoked(before: Consent, after: Consent, offered_keys: Iterable[str]) -> List[str]:
    def took(c: Consent, key: str) -> bool:
        return c.mode == MODE_ALL or (c.mode == MODE_LIST and key in c.accounts)
    return [k for k in dict.fromkeys([*offered_keys, *before.accounts]) if took(before, k) and not took(after, k)]


def pending(consent: Consent, offered_keys: Iterable[str]) -> List[str]:
    if consent.mode in (MODE_ALL, MODE_NONE):
        return []
    return [k for k in offered_keys if k not in consent.answered]


def answer(mode: str, accounts: List[str], offered_keys: List[str]) -> Consent:
    if mode not in MODES:
        raise ValueError("bad_mode")
    names = tuple(dict.fromkeys(accounts))
    if mode != MODE_LIST:
        if names:
            raise ValueError("accounts_not_allowed")
        return Consent(mode, (), tuple(offered_keys))
    if not names:
        raise ValueError("empty_list")
    if not set(names) <= set(offered_keys):
        raise ValueError("account_not_offered")
    return Consent(MODE_LIST, names, tuple(dict.fromkeys(offered_keys)))


def published(consent: Consent) -> Dict[str, Any]:
    return {"mode": consent.mode or MODE_NONE, "accounts": list(consent.accounts)}


def peer_accepts(published_doc: Any, self_install_id: str, account_key: str) -> bool:
    if not isinstance(published_doc, dict):
        return True
    if published_doc.get("mode") == MODE_ALL:
        return True
    accounts = published_doc.get("accounts")
    return published_doc.get("mode") == MODE_LIST and isinstance(accounts, list) and offer_key(self_install_id, account_key) in accounts
